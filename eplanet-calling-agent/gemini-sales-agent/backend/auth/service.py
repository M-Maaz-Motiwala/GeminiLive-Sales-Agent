from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from backend.config import get_settings

settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode(
        {"sub": subject, "exp": expire, "type": "access"},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    return jwt.encode(
        {"sub": subject, "exp": expire, "type": "refresh"},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def create_state_token(subject: str, token_type: str = "oauth_state", expires_minutes: int = 5) -> str:
    """Short-lived signed token for OAuth `state` binding (e.g. Google Calendar).

    Reuses the access-token secret so the callback can re-derive the user
    without trusting a raw user_id in the query string.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    return jwt.encode(
        {"sub": subject, "exp": expire, "type": token_type},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        return payload
    except JWTError:
        return None
