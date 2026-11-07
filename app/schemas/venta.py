from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


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
    # Un solo cupón por compra. Si viene, `importe` es el monto ANTES del descuento
    # y se registra el neto (importe - descuento).
    cupon_codigo: str | None = Field(None, max_length=20, examples=["K7M3PQ9X"])
    # Beneficio elegido en el mostrador: descuenta sus puntos y aplica el descuento en la
    # misma operación. Requiere socio y excluye cupon_codigo (un beneficio por compra).
    beneficio_id: int | None = Field(None, examples=[3])

    @model_validator(mode="after")
    def _un_beneficio_por_compra(self):
        if self.beneficio_id is not None:
            if self.socio_id is None:
                raise ValueError("beneficio_id requiere socio_id")
            if self.cupon_codigo:
                raise ValueError("Solo se puede usar un beneficio por compra: enviar beneficio_id o cupon_codigo, no ambos")
        return self


class VentaUpdate(BaseModel):
    socio_id: int | None = None
    fecha: datetime | None = None
    lugar: str | None = Field(None, max_length=200)
    importe: Decimal | None = Field(None, gt=0, decimal_places=2)


class VentaResponse(VentaBase):
    id: int
    detalles: list[DetalleResponse] = []

    model_config = {"from_attributes": True}


class VentaCreateResponse(VentaResponse):
    descuento: Decimal = Decimal("0")
    puntos_generados: int = 0
    puntos_canjeados: int = 0
    saldo_puntos: int | None = None  # saldo final del socio (None si la venta no tiene socio)


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
