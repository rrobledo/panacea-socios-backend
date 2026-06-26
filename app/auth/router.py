from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from app.auth import passport
from app.auth.state import generate_state, verify_state
from app.auth.utils import create_token
from app.config import settings
from app.models.socio import Socio
from app.schemas.auth import TokenResponse

router = APIRouter(prefix="/auth", tags=["Auth"])


def _validate_redirect_uri(redirect_uri: str | None) -> str | None:
    if redirect_uri is None:
        return None
    normalized = redirect_uri.rstrip("/")
    if normalized not in settings.frontend_urls_set:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="redirect_uri not in allowed list",
        )
    return normalized


def _finish(socio: Socio, redirect_uri: str | None = None) -> TokenResponse | RedirectResponse:
    token = create_token(socio.id, socio.email)
    target = redirect_uri or (next(iter(settings.frontend_urls_set), None))
    if target:
        return RedirectResponse(f"{target}?token={token}&socio_id={socio.id}")
    return TokenResponse(access_token=token, socio_id=socio.id)


@router.post("/register", response_model=TokenResponse, status_code=201, summary="Register with email + password")
def register(socio: Socio = passport.authenticate("register")):
    return TokenResponse(access_token=create_token(socio.id, socio.email), socio_id=socio.id)


@router.post("/token", response_model=TokenResponse, summary="Login with email + password (OAuth2 password grant)")
def login_local(socio: Socio = passport.authenticate("local")):
    return TokenResponse(access_token=create_token(socio.id, socio.email), socio_id=socio.id)


# ── Google ────────────────────────────────────────────────────────────────────

@router.get("/google", summary="Initiate Google Authorization Code flow", include_in_schema=True)
def google_initiate(redirect_uri: str | None = Query(None)):
    validated = _validate_redirect_uri(redirect_uri)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": f"{settings.base_url}/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": generate_state(validated),
        "access_type": "online",
    }
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}")


@router.get("/google/callback", response_model=TokenResponse, summary="Google OAuth2 callback")
def google_callback(
    state: str | None = Query(None),
    socio: Socio = passport.authenticate("google"),
):
    redirect_uri = verify_state(state) if state else None
    return _finish(socio, redirect_uri)


# ── Facebook ──────────────────────────────────────────────────────────────────

@router.get("/facebook", summary="Initiate Facebook Authorization Code flow")
def facebook_initiate(redirect_uri: str | None = Query(None)):
    validated = _validate_redirect_uri(redirect_uri)
    params = {
        "client_id": settings.facebook_app_id,
        "redirect_uri": f"{settings.base_url}/auth/facebook/callback",
        "response_type": "code",
        "scope": "email",
        "state": generate_state(validated),
    }
    return RedirectResponse(f"https://www.facebook.com/v18.0/dialog/oauth?{urlencode(params)}")


@router.get("/facebook/callback", response_model=TokenResponse, summary="Facebook OAuth2 callback")
def facebook_callback(
    state: str | None = Query(None),
    socio: Socio = passport.authenticate("facebook"),
):
    redirect_uri = verify_state(state) if state else None
    return _finish(socio, redirect_uri)


# ── Apple (callback is POST — Apple uses response_mode=form_post) ─────────────

@router.get("/apple", summary="Initiate Apple Sign In Authorization Code flow")
def apple_initiate(redirect_uri: str | None = Query(None)):
    validated = _validate_redirect_uri(redirect_uri)
    params = {
        "client_id": settings.apple_client_id,
        "redirect_uri": f"{settings.base_url}/auth/apple/callback",
        "response_type": "code",
        "scope": "name email",
        "state": generate_state(validated),
        "response_mode": "form_post",
    }
    return RedirectResponse(f"https://appleid.apple.com/auth/authorize?{urlencode(params)}")


@router.post("/apple/callback", response_model=TokenResponse, summary="Apple Sign In callback (form_post)")
def apple_callback(
    state: str | None = Form(None),
    socio: Socio = passport.authenticate("apple"),
):
    redirect_uri = verify_state(state) if state else None
    return _finish(socio, redirect_uri)
