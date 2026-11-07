from datetime import date, datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, Field, field_serializer, model_validator


def _utc(dt: datetime | None) -> datetime | None:
    """Los timestamps se guardan en UTC naive; se exponen con zona (sufijo Z)."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ── Socio: recompensas ─────────────────────────────────────────────────────────

class PorVencer(BaseModel):
    puntos: int
    fecha: datetime


class CreditosResponse(BaseModel):
    saldo: int
    por_vencer: PorVencer | None = None
    proxima_recompensa: int | None = None


class MovimientoResponse(BaseModel):
    id: int
    tipo: str
    puntos: int
    descripcion: str | None
    fecha: datetime

    @field_serializer("fecha")
    def _ser_fecha(self, v: datetime):
        return _utc(v)


class ReglaVigenteResponse(BaseModel):
    monto_por_punto: float
    multiplicador: float
    tope_por_compra: int | None
    vigente_desde: date


class BeneficioSocioResponse(BaseModel):
    id: int
    nombre: str
    descripcion: str | None
    imagen_url: str | None
    costo_puntos: int
    porcentaje_descuento: float
    tope_descuento: float | None
    dias_validez_cupon: int
    canjeable: bool


class CuponResponse(BaseModel):
    """Forma que consume la wallet de cupones del frontend."""
    id: int
    codigo: str
    title: str
    porcentaje_descuento: float
    tope_descuento: float | None
    status: str  # ACTIVE | USED | EXPIRED
    expires: datetime
    origen: str

    @field_serializer("expires")
    def _ser_expires(self, v: datetime):
        return _utc(v)


class CanjeResponse(BaseModel):
    cupon: CuponResponse
    saldo: int


class MaquinaResponse(BaseModel):
    cost: int
    enabled: bool


class JugarResponse(BaseModel):
    coupon: CuponResponse
    saldo: int


class ValidarCuponResponse(BaseModel):
    valido: bool
    descuento: float = 0
    porcentaje_descuento: float | None = None
    motivo: str | None = None


# ── Mostrador: beneficios usables en una venta ─────────────────────────────────

class BeneficioUsableResponse(BaseModel):
    id: int
    nombre: str
    descripcion: str | None
    imagen_url: str | None
    costo_puntos: int
    porcentaje_descuento: float
    tope_descuento: float | None
    usable: bool
    # SALDO_INSUFICIENTE | LIMITE_ALCANZADO | PROGRAMA_INACTIVO | SIN_STOCK | BENEFICIO_NO_DISPONIBLE
    motivo: str | None = None
    descuento_estimado: float | None = None  # solo si se informó `importe`


class BeneficiosDisponiblesResponse(BaseModel):
    socio_id: int
    saldo_puntos: int
    beneficios: list[BeneficioUsableResponse]


# ── Admin ──────────────────────────────────────────────────────────────────────

class BeneficioBase(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=120)
    descripcion: str | None = Field(None, max_length=500)
    imagen_url: str | None = Field(None, max_length=500)
    costo_puntos: int = Field(..., gt=0)
    porcentaje_descuento: Decimal = Field(..., gt=0, le=100, decimal_places=2)
    tope_descuento: Decimal | None = Field(None, gt=0, decimal_places=2)
    dias_validez_cupon: int = Field(30, gt=0)
    limite_por_socio: int | None = Field(None, gt=0)
    stock: int | None = Field(None, ge=0)
    vigente_desde: date
    vigente_hasta: date | None = None
    activo: bool = True

    @model_validator(mode="after")
    def _vigencia(self):
        if self.vigente_hasta and self.vigente_hasta < self.vigente_desde:
            raise ValueError("vigente_hasta debe ser posterior a vigente_desde")
        return self


class BeneficioCreate(BeneficioBase):
    pass


class BeneficioUpdate(BaseModel):
    nombre: str | None = Field(None, min_length=1, max_length=120)
    descripcion: str | None = Field(None, max_length=500)
    imagen_url: str | None = Field(None, max_length=500)
    costo_puntos: int | None = Field(None, gt=0)
    porcentaje_descuento: Decimal | None = Field(None, gt=0, le=100, decimal_places=2)
    tope_descuento: Decimal | None = Field(None, gt=0, decimal_places=2)
    dias_validez_cupon: int | None = Field(None, gt=0)
    limite_por_socio: int | None = Field(None, gt=0)
    stock: int | None = Field(None, ge=0)
    vigente_desde: date | None = None
    vigente_hasta: date | None = None
    activo: bool | None = None


class BeneficioAdminResponse(BaseModel):
    id: int
    nombre: str
    descripcion: str | None
    imagen_url: str | None
    costo_puntos: int
    porcentaje_descuento: float
    tope_descuento: float | None
    dias_validez_cupon: int
    limite_por_socio: int | None
    stock: int | None
    vigente_desde: date
    vigente_hasta: date | None
    activo: bool
    canjes_realizados: int = 0

    model_config = {"from_attributes": True}


class ReglaCreate(BaseModel):
    monto_por_punto: Decimal = Field(..., gt=0, decimal_places=2)
    multiplicador: Decimal = Field(Decimal("1"), gt=0, le=10, decimal_places=2)
    tope_por_compra: int | None = Field(None, gt=0)
    vigente_desde: date
    motivo: str = Field(..., min_length=3, max_length=200)


class ReglaResponse(BaseModel):
    id: int
    monto_por_punto: float
    multiplicador: float
    tope_por_compra: int | None
    vigente_desde: date
    vigente_hasta: date | None
    motivo: str
    creado_por: str | None

    model_config = {"from_attributes": True}


class ConfigProgramaSchema(BaseModel):
    meses_expiracion_puntos: int = Field(..., ge=0, le=120)
    costo_juego_maquina: int = Field(..., ge=0)
    programa_activo: bool

    model_config = {"from_attributes": True}


class SaldoSocioResponse(BaseModel):
    socio_id: int
    saldo: int


class AjusteCreate(BaseModel):
    socio_id: int
    puntos: int
    motivo: str = Field(..., min_length=3, max_length=200)

    @model_validator(mode="after")
    def _no_cero(self):
        if self.puntos == 0:
            raise ValueError("puntos no puede ser 0")
        return self
