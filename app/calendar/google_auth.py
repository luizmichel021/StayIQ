import os
import json
import base64

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from dotenv import load_dotenv

from app.storage.storage import Storage
from app.utils.logger import Logger

load_dotenv()

SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
]

log = Logger(name='google_auth')


def _get_creds_config() -> dict:
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise ValueError("GOOGLE_CREDENTIALS_JSON não encontrada no .env")
    return json.loads(creds_json)


def _get_redirect_uri() -> str:
    return os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/oauth/callback")


def get_auth_url(redirect_uri: str = None) -> tuple[str, str, str]:
    """Returns (auth_url, state, code_verifier) for PKCE flow."""
    uri  = redirect_uri or _get_redirect_uri()
    flow = Flow.from_client_config(_get_creds_config(), scopes=SCOPES, redirect_uri=uri)
    auth_url, state = flow.authorization_url(access_type='offline', prompt='consent')
    log.info(f"URL auth gerada. redirect_uri={uri}")
    return auth_url, state, flow.code_verifier


def exchange_code_for_token(code: str, redirect_uri: str = None, code_verifier: str = None) -> tuple[Credentials, str, str]:
    uri  = redirect_uri or _get_redirect_uri()
    flow = Flow.from_client_config(_get_creds_config(), scopes=SCOPES, redirect_uri=uri)
    flow.fetch_token(code=code, code_verifier=code_verifier)
    creds = flow.credentials

    email, name = _extrair_info_do_token(creds)
    log.info(f"Token obtido. Usuário: {name} <{email}>")

    Storage().save_google_token(email, creds.to_json(), name=name)
    return creds, email, name


def get_calendar_service(email: str):
    """
    Returns an authenticated Google Calendar service.
    Strategy: DB cache (1h) → refresh_token → raise RuntimeError.
    Never opens a browser.
    """
    if not email:
        raise ValueError("Email obrigatório para autenticação silenciosa.")

    storage = Storage()

    token_str = storage.get_google_token(email)
    if token_str:
        try:
            creds = Credentials.from_authorized_user_info(json.loads(token_str), SCOPES)
            if creds and creds.valid:
                return build('calendar', 'v3', credentials=creds), email
        except Exception as e:
            log.warning(f"Token em cache corrompido para {email}: {e}")

    user = storage.get_user(email)
    if user and user.get('token_enc'):
        try:
            from app.utils.crypto import decrypt_token
            token_raw = decrypt_token(bytes(user['token_enc']))
            creds     = Credentials.from_authorized_user_info(json.loads(token_raw), SCOPES)
            if creds and creds.refresh_token:
                creds.refresh(Request())
                storage.save_google_token(email, creds.to_json())
                return build('calendar', 'v3', credentials=creds), email
        except Exception as e:
            log.error(f"Falha ao renovar token para {email}: {e}")

    raise RuntimeError(
        f"Token de {email} expirado e sem refresh_token válido. "
        "O usuário precisa reautenticar via /login."
    )


def _extrair_info_do_token(creds: Credentials) -> tuple[str, str]:
    try:
        id_token = getattr(creds, 'id_token', None)
        if id_token:
            payload_b64 = id_token.split('.')[1]
            payload_b64 += '=' * (4 - len(payload_b64) % 4)
            payload = json.loads(base64.b64decode(payload_b64))
            return payload.get('email', ''), payload.get('name', '')
    except Exception as e:
        log.warning(f"Não foi possível extrair info do id_token: {e}")
    return '', ''