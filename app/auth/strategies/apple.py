from datetime import datetime, timedelta, timezone
from typing import Callable

import httpx
from fastapi import Depends, Form, HTTPException, status
from jose import JWTError, jwt as jose_jwt
from sqlalchemy.orm import Session

from app.auth.state import verify_state
from app.auth.strategies.base import BaseStrategy
from app.config import settings
from app.database import get_db
from app.models.socio import Socio

_TOKEN_URL = "https://appleid.apple.com/auth/token"
_JWKS_URL = "https://appleid.apple.com/auth/keys"


def _generate_client_secret() -> str:
    """Apple requires the client_secret to be an ES256-signed JWT."""
    now = datetime.now(timezone.utc)
    payload = {
        "iss": settings.apple_team_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=10)).timestamp()),
        "aud": "https://appleid.apple.com",
        "sub": settings.apple_client_id,
    }
    return jose_jwt.encode(
        payload,
        settings.apple_private_key,
        algorithm="ES256",
        headers={"kid": settings.apple_key_id},
    )


def _get_apple_jwks() -> dict:
    try:
        resp = httpx.get(_JWKS_URL, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except (httpx.TimeoutException, httpx.HTTPError):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Apple unavailable, retry")


def _exchange_code(code: str) -> dict:
    try:
        resp = httpx.post(
            _TOKEN_URL,
            data={
                "client_id": settings.apple_client_id,
                "client_secret": _generate_client_secret(),
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": f"{settings.base_url}/auth/apple/callback",
            },
            timeout=10,
        )
    except httpx.TimeoutException:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Apple unavailable, retry")

    if resp.status_code != 200:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Apple code exchange failed")

    id_token = resp.json().get("id_token")
    if not id_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Apple did not return id_token")

    jwks = _get_apple_jwks()
    try:
        payload = jose_jwt.decode(
            id_token,
            jwks,
            algorithms=["RS256"],
            audience=settings.apple_client_id or None,
            options={"verify_aud": bool(settings.apple_client_id)},
        )
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid Apple id_token")

    return payload


class AppleStrategy(BaseStrategy):
    def as_dependency(self) -> Callable:
        # Apple sends code + state as form fields (response_mode=form_post)
        def callback(
            code: str | None = Form(None),
            state: str | None = Form(None),
            error: str | None = Form(None),
            db: Session = Depends(get_db),
        ) -> Socio:
            if error:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Apple OAuth error: {error}")
            if not code or not state:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing code or state")
            verify_state(state)
            payload = _exchange_code(code)
            email = payload.get("email")
            if not email:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Apple token missing email")
            socio = db.query(Socio).filter(Socio.email == email).first()
            if not socio:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="no account found for this email; register first",
                )
            return socio

        return callback
