from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


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


class VentaBase(BaseModel):
    socio_id: int | None = Field(None, examples=[1])
    fecha: datetime = Field(..., examples=["2024-06-15T20:30:00"])
    lugar: str | None = Field(None, max_length=200, examples=["Local Palermo"])
    importe: Decimal = Field(..., gt=0, decimal_places=2, examples=[["700.00"]])


class VentaCreate(VentaBase):
    detalles: list[DetalleCreate] = Field(default_factory=list)


class VentaUpdate(BaseModel):
    socio_id: int | None = None
    fecha: datetime | None = None
    lugar: str | None = Field(None, max_length=200)
    importe: Decimal | None = Field(None, gt=0, decimal_places=2)


class VentaResponse(VentaBase):
    id: int
    detalles: list[DetalleResponse] = []

    model_config = {"from_attributes": True}


class VentaDetailResponse(BaseModel):
    categoria: str | None
    producto: str | None
    subtotal: Decimal | None
    cantidad: Decimal | None


class ComprasSemanalResponse(BaseModel):
    fecha: date
    total: Decimal


class ComprasPorCategoriaResponse(BaseModel):
    name: str | None
    value: int | None
