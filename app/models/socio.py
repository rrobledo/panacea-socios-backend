from datetime import date

from sqlalchemy import Boolean, Date, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Socio(Base):
    __tablename__ = "socios"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    nombre_apellido: Mapped[str] = mapped_column(String(200), nullable=False)
    telefono: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    fecha_nacimiento: Mapped[date | None] = mapped_column(Date)
    dni: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(200))
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    preguntas: Mapped[list["PreguntaPorSocio"]] = relationship(  # noqa: F821
        "PreguntaPorSocio", back_populates="socio", cascade="all, delete-orphan"
    )
    ventas: Mapped[list["RegistroVenta"]] = relationship(  # noqa: F821
        "RegistroVenta", back_populates="socio"
    )
