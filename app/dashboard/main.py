import os
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.calendar.google_auth import get_auth_url, exchange_code_for_token, get_calendar_service
from app.storage.storage import Storage
from app.services.scheduler_service import iniciar_scheduler
from app.utils.logger import Logger
from app.dashboard.responses import login_error_html, oauth_error_html, dashboard_error_html
import uvicorn

log     = Logger(name="dashboard")
storage = Storage()

app = FastAPI(title="StayIQ Dashboard")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "stayiq_super_secret_key"))

base_path = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(base_path, "static")), name="static")

templates = Jinja2Templates(directory=os.path.join(base_path, "templates"))

BRT = ZoneInfo("America/Sao_Paulo")


def format_dt(value):
    if not value:
        return ""
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if hasattr(value, 'tzinfo') and value.tzinfo:
            value = value.astimezone(BRT)
        return value.strftime("%d/%m às %H:%M")
    except Exception:
        return str(value)

templates.env.filters["format_dt"] = format_dt


@app.on_event("startup")
async def startup_event():
    iniciar_scheduler()
    log.info("🚀 StayIQ Dashboard iniciado.")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if request.session.get("user_email"):
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse(request, "index.html")


@app.get("/login")
async def login(request: Request):
    try:
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost:8000"
        scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
        redirect_uri = f"{scheme}://{host}/oauth/callback"

        auth_url, state, verifier = get_auth_url(redirect_uri=redirect_uri)

        request.session["oauth_state"]    = state
        request.session["oauth_verifier"] = verifier
        request.session["redirect_uri"]   = redirect_uri

        return RedirectResponse(url=auth_url)
    except Exception as e:
        log.error(f"Erro ao gerar URL de login: {e}")
        return HTMLResponse(login_error_html(e))


@app.get("/oauth/callback")
async def oauth_callback(request: Request, code: str = None, state: str = None, error: str = None):
    if error or not code:
        log.warning(f"OAuth cancelado/erro: {error}")
        return RedirectResponse(url="/?error=cancelled")

    saved_state  = request.session.get("oauth_state")
    redirect_uri = request.session.get("redirect_uri")
    verifier     = request.session.get("oauth_verifier")

    if not saved_state or saved_state != state:
        log.warning("State mismatch ou sessão expirada.")

    try:
        _, email, _ = exchange_code_for_token(
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=verifier
        )
        request.session["user_email"] = email
        request.session.pop("oauth_state", None)
        request.session.pop("oauth_verifier", None)
        request.session.pop("redirect_uri", None)
        log.info(f"Login OAuth concluído: {email}")

        user = storage.get_user(email)
        if not user or not user.get("phone_number"):
            return RedirectResponse(url="/setup", status_code=303)

        return RedirectResponse(url="/dashboard", status_code=303)

    except Exception as e:
        log.error(f"Erro no callback OAuth: {type(e).__name__}: {e}")
        return HTMLResponse(oauth_error_html(e, redirect_uri))


@app.get("/setup", response_class=HTMLResponse)
async def setup_get(request: Request):
    if not request.session.get("user_email"):
        return RedirectResponse(url="/")
    return templates.TemplateResponse(request, "setup.html", {"error": None})


@app.post("/setup")
async def setup_post(request: Request, phone: str = Form(...)):
    email = request.session.get("user_email")
    if not email:
        return RedirectResponse(url="/")

    phone = phone.strip().replace(" ", "").replace("-", "").replace("+", "")
    if not phone.isdigit() or len(phone) < 10:
        return templates.TemplateResponse(request, "setup.html", {
            "error": "Número inválido. Use o formato: 5511999999999"
        })

    storage.update_user_phone(email, phone)
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/setup/skip")
async def setup_skip(request: Request):
    if not request.session.get("user_email"):
        return RedirectResponse(url="/")
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    email = request.session.get("user_email")
    if not email:
        return RedirectResponse(url="/")

    try:
        user      = storage.get_user(email)
        user_name = (user.get("name") or email.split("@")[0]) if user else "Usuário"
        phone     = user.get("phone_number") if user else None

        prefs_str    = user.get('default_alerts') or "60min,30min,15min,5min"
        default_prefs = prefs_str.split(',')

        alertas_raw = storage.get_alerts_for_user(email)

        eventos_map = defaultdict(lambda: {"alertas": []})
        for row in alertas_raw:
            eid = row["event_id"]
            if "event_title" not in eventos_map[eid]:
                eventos_map[eid].update({
                    "event_id":    eid,
                    "event_title": row["event_title"],
                    "event_start": row["event_start"],
                })
            eventos_map[eid]["alertas"].append({
                "alert_id":   row["alert_id"],
                "alert_type": row["alert_type"],
                "is_active":  row["is_active"],
                "sent":       row["sent"],
            })

        return templates.TemplateResponse(request, "dashboard.html", {
            "email":         email,
            "user_name":     user_name,
            "phone":         phone,
            "default_prefs": default_prefs,
            "eventos":       list(eventos_map.values()),
        })

    except Exception as e:
        import traceback
        erro_completo = traceback.format_exc()
        log.error(f"Erro no dashboard para {email}: {type(e).__name__}: {e}\n{erro_completo}")
        return HTMLResponse(dashboard_error_html(e, erro_completo), status_code=500)


@app.post("/api/sync")
async def manual_sync(request: Request):
    email = request.session.get("user_email")
    if not email:
        return JSONResponse({"ok": False, "error": "não autenticado"}, status_code=401)
    try:
        from app.calendar.calendar_service import CalendarService
        cal     = CalendarService(email)
        eventos = cal.buscar_eventos()

        db_map        = storage.get_user_events_map(email)
        google_ids    = {ev['google_event_id'] for ev in eventos}
        ids_deletados = set(db_map.keys()) - google_ids
        for gid in ids_deletados:
            storage.delete_event_by_id(db_map[gid])

        novos_alertas = 0
        for ev in eventos:
            resultado    = storage.upsert_event(
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
        log.info(f"[MANUAL SYNC] {email}: {len(eventos)} eventos, {len(ids_deletados)} removidos, {novos_alertas} alertas.")
        return JSONResponse({"ok": True, "eventos": len(eventos), "removidos": len(ids_deletados), "novos_alertas": novos_alertas})
    except Exception as e:
        log.error(f"Erro no sync manual: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/toggle-alert/{alert_id}")
async def toggle_alert(alert_id: int, request: Request):
    if not request.session.get("user_email"):
        return JSONResponse({"ok": False, "error": "não autenticado"}, status_code=401)
    try:
        body      = await request.json()
        is_active = bool(body.get("is_active", True))
        ok        = storage.toggle_alert(alert_id, is_active)
        return JSONResponse({"ok": ok})
    except Exception as e:
        log.error(f"Erro ao alternar alerta {alert_id}: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/update-phone")
async def update_phone(request: Request):
    email = request.session.get("user_email")
    if not email:
        return JSONResponse({"ok": False}, status_code=401)
    try:
        body  = await request.json()
        phone = str(body.get("phone", "")).strip().replace(" ", "").replace("-", "").replace("+", "")
        if not phone.isdigit() or len(phone) < 10:
            return JSONResponse({"ok": False, "error": "número inválido"}, status_code=400)
        ok = storage.update_user_phone(email, phone)
        return JSONResponse({"ok": ok})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/preferences")
async def update_preferences(request: Request):
    email = request.session.get("user_email")
    if not email:
        return JSONResponse({"ok": False}, status_code=401)
    try:
        body   = await request.json()
        alerts = body.get("alerts", [])
        ok     = storage.update_user_preferences(email, alerts)
        return JSONResponse({"ok": ok})
    except Exception as e:
        log.error(f"Erro ao salvar preferências para {email}: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/unlink")
async def unlink(request: Request):
    email = request.session.get("user_email")
    if email:
        storage.delete_user(email)
        log.info(f"Usuário desvinculado: {email}")
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")


if __name__ == "__main__":
    uvicorn.run("app.dashboard.main:app", host="0.0.0.0", port=8000, reload=True)
