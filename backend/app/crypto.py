"""Chiffrement au repos des clés API stockées en base (Fernet, clé dérivée de `SECRET_KEY`).

Une valeur chiffrée porte le préfixe `enc:v1:` ; une valeur sans préfixe (base antérieure à la migration 0011) est lue
telle quelle. Changer `SECRET_KEY` rend les clés chiffrées illisibles : `decrypt` renvoie alors « » (clé absente).
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

PREFIX = "enc:v1:"


def _fernet() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest()))


def is_encrypted(value: str) -> bool:
    return value.startswith(PREFIX)


def encrypt(value: str) -> str:
    return value if not value or is_encrypted(value) else PREFIX + _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if not is_encrypted(value):
        return value
    try:
        return _fernet().decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken:
        return ""
