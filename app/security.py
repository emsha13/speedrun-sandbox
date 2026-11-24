import hashlib
import hmac
import secrets

from datetime import timedelta

import bcrypt
import jwt

from app.models import now
from app.settings import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


# What a sign-in to an address nobody has is checked against, so that it takes as long as a
# sign-in to a real one and the time of the answer says nothing.
NOBODYS_HASH = hash_password(secrets.token_urlsafe(16))


def digest(value: str) -> str:
    """A keyed digest of a secret that is random already — a refresh token, a mailed code."""
    return hmac.new(settings.SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


def random_code() -> str:
    return f'{secrets.randbelow(10 ** 6):06d}'


def random_token() -> str:
    return secrets.token_urlsafe(32)


def create_access_token(user_id: int, session_id: int) -> str:
    issued = now()
    payload = {
        'sub': str(user_id),
        'sid': session_id,
        'iat': issued,
        'exp': issued + timedelta(minutes=settings.ACCESS_TOKEN_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')


def read_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
    except jwt.PyJWTError:
        return None
