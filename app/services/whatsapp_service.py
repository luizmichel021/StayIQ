import os
import requests
import json
from twilio.rest import Client
from app.utils.logger import Logger
from dotenv import load_dotenv

load_dotenv()
log = Logger(name="messenger")

class WhatsAppService:
    """
    Serviço híbrido para gerenciar envios de mensagens.
    Suporta Twilio (Oficial) ou Evolution API (Local/Próprio WhatsApp).
    """

    def __init__(self):
        # Configs Evolution API (Local)
        self.evo_url  = os.getenv('EVOLUTION_API_URL')
        self.evo_key  = os.getenv('EVOLUTION_API_KEY')
        self.instance = os.getenv('EVOLUTION_INSTANCE', 'StayIQ')

        # Configs Twilio
        self.account_sid = os.getenv('TWILIO_ACCOUNT_SID')
        self.auth_token = os.getenv('TWILIO_AUTH_TOKEN')
        self.from_number = os.getenv('TWILIO_WHATSAPP_NUMBER')
        
        self.twilio_client = None
        if self.account_sid and self.auth_token:
            self.twilio_client = Client(self.account_sid, self.auth_token)

    @staticmethod
    def formatar_aviso_checkin(nome_usuario, checkins):
        if not checkins: return None
        msg = f"Olá *{nome_usuario}*! 🏠\n\nIdentificamos {len(checkins)} check-in(s) para hoje no seu StayIQ:\n"
        for c in checkins:
            msg += f"\n📌 *{c['titulo']}*\n🕒 Horário: {c['inicio']}\n"
        msg += "\nBoa recepção! 🚀"
        return msg

    def enviar_mensagem(self, telefone, texto):
        if not telefone or not texto:
            return False

        # --- PRIORIDADE 1: EVOLUTION API (Se estiver configurada) ---
        if self.evo_url:
            return self._enviar_evolution(telefone, texto)

        # --- PRIORIDADE 2: TWILIO (Se estiver configurado) ---
        if self.twilio_client:
            return self._enviar_twilio(telefone, texto)

        # --- FALLBACK: SIMULAÇÃO ---
        log.info(f"--- MODO SIMULAÇÃO ---")
        log.info(f"MENSAGEM PARA {telefone}: {texto}")
        return True

    def _enviar_evolution(self, telefone, texto):
        """Envia usando sua própria conta de WhatsApp via Docker."""
        url = f"{self.evo_url}/message/sendText/{self.instance}"
        headers = {
            "Content-Type": "application/json",
            "apikey": self.evo_key
        }
        # A Evolution API espera o número com @s.whatsapp.net
        payload = {
            "number": telefone,
            "text": texto,
            "linkPreview": False
        }
        
        try:
            res = requests.post(url, json=payload, headers=headers)
            if res.status_code in [200, 201]:
                log.info(f"✅ Mensagem enviada via Evolution API para {telefone}")
                return True
            else:
                log.warning(f"⚠️ Evolution API retornou erro: {res.text}")
                # Se o erro for que a instância não existe, poderíamos criar aqui
                return False
        except Exception as e:
            log.error(f"❌ Falha na Evolution API: {e}")
            return False

    def _enviar_twilio(self, telefone, texto):
        """Envia via Twilio oficial."""
        if not telefone.startswith('+'): telefone = f"+{telefone}"
        try:
            self.twilio_client.messages.create(
                from_=f"whatsapp:{self.from_number}",
                body=texto,
                to=f"whatsapp:{telefone}"
            )
            log.info(f"✅ Mensagem Twilio enviada!")
            return True
        except Exception as e:
            log.error(f"❌ Erro Twilio: {e}")
            return False
