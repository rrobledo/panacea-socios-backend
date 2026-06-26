from typing import Callable

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.strategies.base import BaseStrategy
from app.auth.utils import hash_password
from app.database import get_db
from app.models.socio import Socio
from app.schemas.auth import RegisterRequest


class RegisterStrategy(BaseStrategy):
    def as_dependency(self) -> Callable:
        def authenticate(
            body: RegisterRequest,
            db: Session = Depends(get_db),
        ) -> Socio:
            socio = Socio(
                nombre_apellido=body.nombre_apellido,
                email=body.email,
                dni=body.dni,
                telefono=body.telefono,
                fecha_nacimiento=body.fecha_nacimiento,
                password_hash=hash_password(body.password),
                email_verified=False,
            )
            db.add(socio)
            try:
                db.commit()
                db.refresh(socio)
            except IntegrityError:
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="email or DNI already registered",
                )
            return socio

        return authenticate
