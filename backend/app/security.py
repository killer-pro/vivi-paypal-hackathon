"""Hachage des mots de passe (scrypt) et des jetons à usage unique (SHA-256)."""

import hashlib
import hmac
import secrets

PASSWORD_MIN = 8
PASSWORD_MAX = 128

_SCHEMA = "scrypt"
_SCRYPT_PARAMS = {"n": 2**14, "r": 8, "p": 1}
_SEL_OCTETS = 16


def _derive(password: str, sel: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=sel, dklen=32, **_SCRYPT_PARAMS)


def hash_password(password: str) -> str:
    """Retourne `scrypt$<sel hex>$<hash hex>`, avec un sel aléatoire à chaque appel."""
    sel = secrets.token_bytes(_SEL_OCTETS)
    return f"{_SCHEMA}${sel.hex()}${_derive(password, sel).hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Compare en temps constant. Retourne `False` si `stored` est malformé, sans lever d'exception."""
    try:
        schema, sel_hex, digest_hex = stored.split("$")
        if schema != _SCHEMA:
            return False
        sel = bytes.fromhex(sel_hex)
        digest = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    return hmac.compare_digest(_derive(password, sel), digest)


def token_hash(token: str) -> str:
    """Empreinte SHA-256 hexadécimale d'un jeton ; seule l'empreinte est stockée en base."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> tuple[str, str]:
    """Retourne `(jeton clair, empreinte)`. Le jeton clair n'est remis qu'une fois à son titulaire."""
    token = secrets.token_urlsafe(32)
    return token, token_hash(token)
