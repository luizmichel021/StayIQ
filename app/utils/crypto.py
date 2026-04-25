import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

def get_fernet():
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        raise ValueError("ENCRYPTION_KEY não encontrada no .env")
    return Fernet(key.encode())

def encrypt_token(token_str: str) -> bytes:
    """Criptografa uma string (geralmente JSON) e retorna bytes."""
    f = get_fernet()
    return f.encrypt(token_str.encode('utf-8'))

def decrypt_token(encrypted_token: bytes) -> str:
    """Descriptografa bytes de volta para a string original."""
    if not encrypted_token:
        return None
    f = get_fernet()
    return f.decrypt(encrypted_token).decode('utf-8')
