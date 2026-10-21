from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class RankingComprasResponse(BaseModel):
    socio_id: int
    nombre_apellido: str
    dni: str
    telefono: str | None
    email: str | None
    cantidad_compras: int
    total_compras: Decimal
    ultima_compra: datetime | None


class CumpleanioResponse(BaseModel):
    socio_id: int
    nombre_apellido: str
    dni: str
    telefono: str | None
    email: str | None
    fecha_nacimiento: date
    fecha_cumple: date
    edad: int
