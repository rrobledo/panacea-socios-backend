from typing import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.auth.strategies.base import BaseStrategy
from app.auth.utils import verify_password
from app.database import get_db
from app.models.socio import Socio


class LocalStrategy(BaseStrategy):
    def as_dependency(self) -> Callable:
        def authenticate(
            form: OAuth2PasswordRequestForm = Depends(),
            db: Session = Depends(get_db),
        ) -> Socio:
            socio = db.query(Socio).filter(Socio.email == form.username).first()
            if not socio or not socio.password_hash:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="invalid credentials",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            if not verify_password(form.password, socio.password_hash):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="invalid credentials",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return socio

        return authenticate
