from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from app.storage.storage import Storage
from app.calendar.calendar_service import CalendarService
from app.services.whatsapp_service import WhatsAppService
from app.utils.logger import Logger

log       = Logger(name="scheduler")
storage   = Storage()
messenger = WhatsAppService()

BRT = ZoneInfo("America/Sao_Paulo")

ALERT_LABELS = {
    '60min': '1 hora',
    '30min': '30 minutos',
    '15min': '15 minutos',
    '5min':  '5 minutos',
}


def sync_calendars():
    log.info("[SYNC] Iniciando sincronização de calendários")

    users = storage.get_all_users_with_phone()
    if not users:
        log.info("[SYNC] Nenhum usuário com telefone configurado.")
        return

    for user in users:
        email = user['email']
        log.info(f"[SYNC] Processando: {email}")

        try:
            cal     = CalendarService(email)
            eventos = cal.buscar_eventos()

            db_map        = storage.get_user_events_map(email)
            google_ids    = {ev['google_event_id'] for ev in eventos}
            ids_deletados = set(db_map.keys()) - google_ids

            for gid in ids_deletados:
                storage.delete_event_by_id(db_map[gid])
                log.info(f"[SYNC] Evento removido: {gid[:12]}...")

            novos_alertas = 0
            for ev in eventos:
                resultado = storage.upsert_event(
                    email           = email,
                    google_event_id = ev['google_event_id'],
                    title           = ev['title'],
                    start_time      = ev['start_time'],
                    end_time        = ev.get('end_time'),
                )
                event_id     = resultado['id']
                time_changed = resultado['time_changed']

                if not event_id:
                    continue

                if time_changed:
                    storage.delete_unsent_alerts_for_event(event_id)

                novos_alertas += storage.create_alerts_for_event(
                    event_id   = event_id,
                    start_time = ev['start_time'],
                    email      = email,
                )

            storage.delete_past_events(email)
            log.info(f"[SYNC] {email}: {len(eventos)} eventos, {len(ids_deletados)} removidos, {novos_alertas} alertas.")

        except Exception as e:
            log.error(f"[SYNC] Erro ao processar {email}: {e}")

    log.info("[SYNC] Sincronização concluída")


def dispatch_alerts():
    alertas = storage.get_pending_alerts()
    if not alertas:
        return

    log.info(f"[DISPATCH] {len(alertas)} alerta(s) para enviar.")

    for alerta in alertas:
        telefone  = alerta['phone']
        nome      = alerta['user_name'] or "Usuário"
        titulo_ev = alerta['event_title']
        tipo      = alerta['alert_type']
        alert_id  = alerta['alert_id']
        inicio    = alerta['event_start']
        label     = ALERT_LABELS.get(tipo, tipo)

        try:
            inicio_fmt = inicio.astimezone(BRT).strftime('%d/%m às %H:%M')
        except Exception:
            inicio_fmt = str(inicio)[:16]

        texto = (
            f"🔔 *StayIQ — Lembrete*\n\n"
            f"Olá *{nome}*!\n\n"
            f"Faltam *{label}* para o evento:\n"
            f"📌 *{titulo_ev}*\n"
            f"🕒 {inicio_fmt}\n\n"
            f"Boa recepção! 🏠"
        )

        try:
            if messenger.enviar_mensagem(telefone, texto):
                storage.mark_alert_sent(alert_id)
                log.info(f"[DISPATCH] Alerta '{tipo}' enviado para {nome} ({telefone})")
            else:
                log.warning(f"[DISPATCH] Falha ao enviar alerta {alert_id} para {telefone}")
        except Exception as e:
            log.error(f"[DISPATCH] Erro no alerta {alert_id}: {e}")


def iniciar_scheduler():
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(sync_calendars, 'interval', minutes=30, id='sync_calendars')
    scheduler.add_job(dispatch_alerts, 'interval', minutes=1,  id='dispatch_alerts')
    scheduler.start()
    log.info("Scheduler iniciado: sync (30min) + dispatch (1min)")

    import threading
    threading.Thread(target=sync_calendars, daemon=True).start()
