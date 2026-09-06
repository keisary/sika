"""Sécurité : hachage de PIN (pbkdf2, jamais en clair — REQ-NF-SEC-011)
et jetons d'accès signés HMAC (REQ-NF-SEC-003).
"""
import hashlib
import hmac
import secrets
import time

from .config import settings

_ITERATIONS = 200_000


def hash_pin(pin: str) -> str:
    """Retourne 'salt$hash' — REQ-NF-SEC-011 : jamais de PIN en clair."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), _ITERATIONS)
    return f"{salt}${digest.hex()}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        salt, expected = stored.split("$", 1)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), _ITERATIONS)
    return hmac.compare_digest(digest.hex(), expected)


def new_access_token(compte_id: str, secret: str | None = None, ttl: int | None = None) -> str:
    """Jeton 'compte_id.expiration.signature' — révocable par changement de clé."""
    secret = secret or settings.sika_secret_key
    ttl = ttl or settings.token_ttl_seconds
    exp = int(time.time()) + ttl
    payload = f"{compte_id}.{exp}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def decode_access_token(token: str, secret: str | None = None) -> str | None:
    """Retourne le compte_id si le jeton est valide et non expiré, sinon None."""
    secret = secret or settings.sika_secret_key
    try:
        payload, sig = token.rsplit(".", 1)
        compte_id, exp = payload.rsplit(".", 1)
    except ValueError:
        return None
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    if int(exp) < time.time():
        return None
    return compte_id
