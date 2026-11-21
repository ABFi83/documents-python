from cryptography.fernet import Fernet
from flask import current_app


class CryptoNotConfigured(Exception):
    pass


def _fernet():
    key = current_app.config.get('ENCRYPTION_KEY')
    if not key:
        raise CryptoNotConfigured('ENCRYPTION_KEY non configurata')
    return Fernet(key)


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
