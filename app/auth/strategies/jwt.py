from typing import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import ExpiredSignatureError, JWTError
from sqlalchemy.orm import Session

from app.auth.strategies.base import BaseStrategy
from app.auth.utils import decode_token
from app.database import get_db
from app.models.socio import Socio

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


class JWTStrategy(BaseStrategy):
    def as_dependency(self) -> Callable:
        def authenticate(
            token: str = Depends(_oauth2_scheme),
            db: Session = Depends(get_db),
        ) -> Socio:
            try:
                payload = decode_token(token)
            except ExpiredSignatureError:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="token expired",
                    headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
                )
            except JWTError:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="invalid token",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            socio = db.get(Socio, int(payload["sub"]))
            if not socio:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="user not found",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return socio

        return authenticate
