from app.storage.connection import ConnectionDatabase
from app.utils.logger import Logger
from app.utils.crypto import encrypt_token, decrypt_token
from datetime import datetime, timezone, timedelta

ALERT_TYPES = {
    '60min': 60,
    '30min': 30,
    '15min': 15,
    '5min':  5,
}


class Storage:
    def __init__(self):
        self.db  = ConnectionDatabase()
        self.log = Logger(name='storage')
        self._ensure_preferences_column()

    def _ensure_preferences_column(self):
        sql = "ALTER TABLE stayiq.users ADD COLUMN IF NOT EXISTS default_alerts TEXT DEFAULT '60min,30min,15min,5min'"
        self.db.execute_command(sql)

    # Users

    def get_user(self, email: str) -> dict | None:
        results = self.db.execute_query("SELECT * FROM stayiq.users WHERE email = %s", (email,))
        return results[0] if results else None

    def save_google_token(self, email: str, token_json: str, name: str = None) -> bool:
        encrypted_bytes = encrypt_token(token_json)
        sql = """
        INSERT INTO stayiq.users (email, name, token_enc, updated_at)
        VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (email)
        DO UPDATE SET
            token_enc  = EXCLUDED.token_enc,
            updated_at = CURRENT_TIMESTAMP,
            name       = COALESCE(EXCLUDED.name, stayiq.users.name)
        """
        return self.db.execute_command(sql, (email, name, encrypted_bytes))

    def get_google_token(self, email: str) -> str | None:
        """Returns None if token is older than 1h to force a refresh."""
        user = self.get_user(email)
        if not user or not user.get('token_enc'):
            return None

        updated_at = user.get('updated_at')
        if updated_at:
            agora = datetime.now(timezone.utc)
            if isinstance(updated_at, datetime) and not updated_at.tzinfo:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            if (agora - updated_at) >= timedelta(hours=1):
                return None

        try:
            return decrypt_token(bytes(user['token_enc']))
        except Exception as e:
            self.log.error(f"Erro ao descriptografar token de {email}: {e}")
            return None

    def update_user_phone(self, email: str, phone: str) -> bool:
        return self.db.execute_command(
            "UPDATE stayiq.users SET phone_number = %s WHERE email = %s", (phone, email)
        )

    def update_user_preferences(self, email: str, alerts_list: list) -> bool:
        return self.db.execute_command(
            "UPDATE stayiq.users SET default_alerts = %s WHERE email = %s",
            (",".join(alerts_list), email)
        )

    def get_all_users_with_phone(self) -> list:
        sql = """
        SELECT email, name, phone_number
        FROM stayiq.users
        WHERE phone_number IS NOT NULL AND token_enc IS NOT NULL
        """
        return self.db.execute_query(sql)

    def delete_user(self, email: str) -> bool:
        return self.db.execute_command("DELETE FROM stayiq.users WHERE email = %s", (email,))

    # Events

    def upsert_event(self, email: str, google_event_id: str, title: str,
                     start_time: datetime, end_time: datetime = None) -> dict:
        """Returns {'id': int, 'time_changed': bool}. time_changed=True triggers alert recreation."""
        existing = self.db.execute_query(
            "SELECT id, start_time FROM stayiq.events WHERE user_email = %s AND google_event_id = %s",
            (email, google_event_id)
        )

        time_changed = False
        if existing:
            old_start = existing[0]['start_time']
            if old_start and abs((old_start - start_time).total_seconds()) > 60:
                time_changed = True
                self.log.info(f"Horário alterado: '{title}' {old_start.strftime('%H:%M')} → {start_time.strftime('%H:%M')}")

        sql = """
        INSERT INTO stayiq.events (user_email, google_event_id, title, start_time, end_time, synced_at)
        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (user_email, google_event_id)
        DO UPDATE SET
            title      = EXCLUDED.title,
            start_time = EXCLUDED.start_time,
            end_time   = EXCLUDED.end_time,
            synced_at  = CURRENT_TIMESTAMP
        RETURNING id
        """
        results = self.db.execute_command_returning(sql, (email, google_event_id, title, start_time, end_time))
        if results:
            return {'id': results[0]['id'], 'time_changed': time_changed}
        return {'id': None, 'time_changed': False}

    def get_user_events_map(self, email: str) -> dict:
        """Returns {google_event_id: db_event_id} for diff-based sync."""
        rows = self.db.execute_query(
            "SELECT id, google_event_id FROM stayiq.events WHERE user_email = %s", (email,)
        )
        return {row['google_event_id']: row['id'] for row in rows}

    def delete_event_by_id(self, event_id: int) -> bool:
        return self.db.execute_command("DELETE FROM stayiq.events WHERE id = %s", (event_id,))

    def delete_unsent_alerts_for_event(self, event_id: int) -> bool:
        """Removes pending alerts when an event's time changes. Sent alerts are preserved."""
        return self.db.execute_command(
            "DELETE FROM stayiq.scheduled_alerts WHERE event_id = %s AND sent = FALSE", (event_id,)
        )

    def get_upcoming_events(self, email: str) -> list:
        sql = """
        SELECT id, title, start_time, end_time
        FROM stayiq.events
        WHERE user_email = %s
          AND start_time >= NOW()
          AND start_time <= NOW() + INTERVAL '7 days'
        ORDER BY start_time ASC
        """
        return self.db.execute_query(sql, (email,))

    def delete_past_events(self, email: str) -> bool:
        return self.db.execute_command(
            "DELETE FROM stayiq.events WHERE user_email = %s AND start_time < NOW()", (email,)
        )

    # Alerts

    def create_alerts_for_event(self, event_id: int, start_time: datetime, email: str) -> int:
        """Creates alerts per user preferences. Inactive if not in prefs."""
        user = self.get_user(email)
        prefs = (user.get('default_alerts') or "60min,30min,15min,5min").split(',')

        criados = 0
        for tipo, minutos in ALERT_TYPES.items():
            scheduled_time = start_time - timedelta(minutes=minutos)
            if scheduled_time <= datetime.now(timezone.utc):
                continue

            sql = """
            INSERT INTO stayiq.scheduled_alerts (user_email, event_id, alert_type, scheduled_time, is_active)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (event_id, alert_type) DO NOTHING
            """
            if self.db.execute_command(sql, (email, event_id, tipo, scheduled_time, tipo in prefs)):
                criados += 1

        return criados

    def get_alerts_for_user(self, email: str) -> list:
        sql = """
        SELECT
            sa.id          AS alert_id,
            sa.alert_type,
            sa.scheduled_time,
            sa.is_active,
            sa.sent,
            e.id           AS event_id,
            e.title        AS event_title,
            e.start_time   AS event_start
        FROM stayiq.scheduled_alerts sa
        JOIN stayiq.events e ON e.id = sa.event_id
        WHERE sa.user_email = %s
          AND e.start_time >= NOW()
          AND e.start_time <= NOW() + INTERVAL '7 days'
        ORDER BY e.start_time ASC, sa.scheduled_time ASC
        """
        return self.db.execute_query(sql, (email,))

    def toggle_alert(self, alert_id: int, is_active: bool) -> bool:
        return self.db.execute_command(
            "UPDATE stayiq.scheduled_alerts SET is_active = %s WHERE id = %s", (is_active, alert_id)
        )

    def get_pending_alerts(self) -> list:
        sql = """
        SELECT
            sa.id          AS alert_id,
            sa.alert_type,
            sa.user_email,
            e.title        AS event_title,
            e.start_time   AS event_start,
            u.name         AS user_name,
            u.phone_number AS phone
        FROM stayiq.scheduled_alerts sa
        JOIN stayiq.events e ON e.id = sa.event_id
        JOIN stayiq.users  u ON u.email = sa.user_email
        WHERE sa.is_active = TRUE
          AND sa.sent = FALSE
          AND sa.scheduled_time <= NOW()
          AND u.phone_number IS NOT NULL
        """
        return self.db.execute_query(sql)

    def mark_alert_sent(self, alert_id: int) -> bool:
        return self.db.execute_command(
            "UPDATE stayiq.scheduled_alerts SET sent = TRUE, sent_at = CURRENT_TIMESTAMP WHERE id = %s",
            (alert_id,)
        )
