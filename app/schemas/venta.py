from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class DetalleCreate(BaseModel):
    producto_id: str = Field(..., max_length=100, examples=["CERVEZA-IPA-500ML"])
    cantidad: int = Field(..., gt=0, examples=[2])
    subtotal: Decimal = Field(..., gt=0, decimal_places=2, examples=[["350.00"]])


class DetalleResponse(BaseModel):
    id: int
    registro_venta_id: int
    producto_id: str
    cantidad: int
    subtotal: Decimal

    model_config = {"from_attributes": True}


def _coerce_to_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str) and "T" in v:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).date()
    return v


class VentaBase(BaseModel):
    socio_id: int | None = Field(None, examples=[1])
    fecha: date = Field(..., examples=["2024-06-15"])
    lugar: str | None = Field(None, max_length=200, examples=["Local Palermo"])
    importe: Decimal = Field(..., gt=0, decimal_places=2, examples=[["700.00"]])

    @field_validator("fecha", mode="before")
    @classmethod
    def parse_fecha(cls, v):
        return _coerce_to_date(v)


class VentaCreate(VentaBase):
    detalles: list[DetalleCreate] = Field(default_factory=list)


class VentaUpdate(BaseModel):
    socio_id: int | None = None
    fecha: date | None = None
    lugar: str | None = Field(None, max_length=200)
    importe: Decimal | None = Field(None, gt=0, decimal_places=2)

    @field_validator("fecha", mode="before")
    @classmethod
    def parse_fecha(cls, v):
        return _coerce_to_date(v)


class VentaResponse(VentaBase):
    id: int
    detalles: list[DetalleResponse] = []

    model_config = {"from_attributes": True}
