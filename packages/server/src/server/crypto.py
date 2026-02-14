"""Fernet encryption utilities for secrets management."""

import base64
import hashlib
import json

from cryptography.fernet import Fernet

from server.config import get_settings


def _derive_fernet_key(secret_key: str) -> bytes:
    """Derive a 32-byte Fernet key from an arbitrary string using PBKDF2."""
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        secret_key.encode(),
        salt=b"upnext-secrets-v1",
        iterations=480_000,
    )
    return base64.urlsafe_b64encode(dk)


def get_fernet() -> Fernet:
    """Get a Fernet instance using the server's secret_key."""
    settings = get_settings()
    key = _derive_fernet_key(settings.secret_key)
    return Fernet(key)


def encrypt_data(data: dict[str, str]) -> str:
    """Encrypt a dict of key-value pairs to a Fernet token string."""
    f = get_fernet()
    plaintext = json.dumps(data).encode()
    return f.encrypt(plaintext).decode()


def decrypt_data(encrypted: str) -> dict[str, str]:
    """Decrypt a Fernet token string back to a dict."""
    f = get_fernet()
    plaintext = f.decrypt(encrypted.encode())
    return json.loads(plaintext)
