import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from jose import JWTError, jwt

from app.config import settings

_EXPIRE_MINUTES = 10
_ALGO = "HS256"


def generate_state() -> str:
    payload = {
        "jti": secrets.token_urlsafe(16),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=_ALGO)


def verify_state(state: str) -> None:
    try:
        jwt.decode(state, settings.secret_key, algorithms=[_ALGO])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid or expired OAuth state",
        )
