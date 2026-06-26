from typing import Callable

import httpx
from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.state import verify_state
from app.auth.strategies.base import BaseStrategy
from app.config import settings
from app.database import get_db
from app.models.socio import Socio

_TOKEN_URL = "https://graph.facebook.com/v18.0/oauth/access_token"
_USERINFO_URL = "https://graph.facebook.com/me"


def _exchange_code(code: str) -> dict:
    try:
        token_resp = httpx.get(
            _TOKEN_URL,
            params={
                "client_id": settings.facebook_app_id,
                "client_secret": settings.facebook_app_secret,
                "redirect_uri": f"{settings.base_url}/auth/facebook/callback",
                "code": code,
            },
            timeout=10,
        )
    except httpx.TimeoutException:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Facebook unavailable, retry")

    if token_resp.status_code != 200:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Facebook code exchange failed")

    access_token = token_resp.json().get("access_token")
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Facebook did not return access_token")

    try:
        info_resp = httpx.get(
            _USERINFO_URL,
            params={"access_token": access_token, "fields": "email,name"},
            timeout=10,
        )
    except httpx.TimeoutException:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Facebook unavailable, retry")

    if info_resp.status_code != 200:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not fetch Facebook user info")

    data = info_resp.json()
    email = data.get("email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Facebook account has no verified email; grant email permission",
        )

    return {"email": email, "name": data.get("name", "")}


class FacebookStrategy(BaseStrategy):
    def as_dependency(self) -> Callable:
        def callback(
            code: str | None = Query(None),
            state: str | None = Query(None),
            error: str | None = Query(None),
            db: Session = Depends(get_db),
        ) -> Socio:
            if error:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Facebook OAuth error: {error}")
            if not code or not state:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing code or state")
            verify_state(state)
            profile = _exchange_code(code)
            socio = db.query(Socio).filter(Socio.email == profile["email"]).first()
            if not socio:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="no account found for this email; register first",
                )
            return socio

        return callback
