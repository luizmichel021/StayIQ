from datetime import datetime, timezone, timedelta
from app.calendar.google_auth import get_calendar_service
from app.utils.logger import Logger

log = Logger(name="calendar_service")

# ──────────────────────────────────────────────────────────────
# Para filtrar apenas alguns tipos de evento, descomente e edite:
# KEYWORD_FILTER = ['check', 'reserva', 'airbnb', 'booking']
# ──────────────────────────────────────────────────────────────
KEYWORD_FILTER = []  # lista vazia = sincroniza TODOS os eventos


class CalendarService:
    def __init__(self, email: str):
        self.email = email
        self.service, _ = get_calendar_service(email)

    def buscar_eventos(self) -> list:
        """
        Busca todos os eventos de TODOS os calendários do usuário.
        Janela: hoje (00:00) → +7 dias.
        Se KEYWORD_FILTER estiver preenchido, filtra por palavras-chave no título.
        """
        agora = datetime.now(timezone.utc)
        inicio = agora.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        fim    = (agora + timedelta(days=7)).isoformat()

        log.info(f"[{self.email}] Buscando eventos: {inicio[:10]} → {(agora + timedelta(days=7)).strftime('%d/%m')}")

        # Lista todos os calendários do usuário
        try:
            cal_list   = self.service.calendarList().list().execute()
            calendarios = cal_list.get('items', [])
        except Exception as e:
            log.error(f"[{self.email}] Erro ao listar calendários: {e}")
            return []

        todos_eventos = []
        ids_vistos    = set()

        for cal in calendarios:
            cal_id   = cal.get('id')
            cal_nome = cal.get('summary', 'sem nome')

            try:
                resultado = self.service.events().list(
                    calendarId=cal_id,
                    timeMin=inicio,
                    timeMax=fim,
                    singleEvents=True,
                    orderBy='startTime'
                ).execute()

                for ev in resultado.get('items', []):
                    ev_id = ev.get('id')
                    if ev_id in ids_vistos:
                        continue
                    ids_vistos.add(ev_id)

                    titulo = ev.get('summary', '').strip()
                    if not titulo:
                        continue

                    # Aplica filtro por palavra-chave se configurado
                    if KEYWORD_FILTER:
                        titulo_lower = titulo.lower()
                        if not any(kw in titulo_lower for kw in KEYWORD_FILTER):
                            continue

                    # Extrai datetime de início e fim
                    start_raw = ev.get('start', {}).get('dateTime') or ev.get('start', {}).get('date')
                    end_raw   = ev.get('end', {}).get('dateTime')   or ev.get('end', {}).get('date')

                    start_dt = _parse_dt(start_raw)
                    end_dt   = _parse_dt(end_raw)

                    if not start_dt:
                        continue

                    todos_eventos.append({
                        'google_event_id': ev_id,
                        'title':           titulo,
                        'start_time':      start_dt,
                        'end_time':        end_dt,
                    })

            except Exception as e:
                log.warning(f"[{self.email}] Erro ao acessar calendário '{cal_nome}': {e}")

        log.info(f"[{self.email}] Total de eventos encontrados: {len(todos_eventos)}")
        return todos_eventos


def _parse_dt(value: str | None) -> datetime | None:
    """Converte string ISO do Google Calendar para datetime com timezone."""
    if not value:
        return None
    try:
        if 'T' in value:
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        else:
            # Evento de dia inteiro — trata como meia-noite UTC
            d = datetime.fromisoformat(value)
            return d.replace(tzinfo=timezone.utc)
    except Exception:
        return None
