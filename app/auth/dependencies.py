from fastapi import Depends, HTTPException, status

from app.auth import passport
from app.config import settings
from app.models.socio import Socio


def require_admin(current_socio: Socio = passport.authenticate("jwt")) -> Socio:
    if current_socio.email.lower() not in settings.admin_emails_set:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin access required")
    return current_socio
