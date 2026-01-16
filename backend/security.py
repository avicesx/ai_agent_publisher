import os
import base64
from cryptography.fernet import Fernet

# Получаем ключ шифрования из .env
SECRET_KEY = os.getenv("ENCRYPTION_KEY")
if not SECRET_KEY:
    raise ValueError("ENCRYPTION_KEY must be set in .env")

# Приводим к корректному base64-формату для Fernet (32 байта → base64)
if len(SECRET_KEY) == 32:
    # Сырой 32-байтный ключ → кодируем
    key_bytes = SECRET_KEY.encode("utf-8")
elif len(SECRET_KEY) == 44 and SECRET_KEY.endswith("="):
    # Уже base64 — используем как есть
    key_bytes = base64.urlsafe_b64decode(SECRET_KEY.encode("utf-8"))
else:
    # Пытаемся дополнить до 32 байт
    key_bytes = SECRET_KEY.encode("utf-8").ljust(32, b"\0")[:32]

fernet_key = base64.urlsafe_b64encode(key_bytes)
fernet = Fernet(fernet_key)


def encrypt_key(api_key: str) -> str:
    """Шифрует строку API-ключа"""
    return fernet.encrypt(api_key.encode("utf-8")).decode("utf-8")


def decrypt_key(encrypted_key: str) -> str:
    """Расшифровывает строку API-ключа"""
    return fernet.decrypt(encrypted_key.encode("utf-8")).decode("utf-8")