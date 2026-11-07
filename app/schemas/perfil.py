from datetime import date, datetime, timezone

from pydantic import BaseModel, field_serializer


def _utc(dt: datetime | None) -> datetime | None:
    """Los timestamps se guardan en UTC naive; se exponen con zona (sufijo Z)."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class PerfilSocioResponse(BaseModel):
    socio_id: int
    resumen: str
    etiquetas: list[str]
    categorias_favoritas: list[str]
    productos_favoritos: list[str]
    ventas_analizadas: int
    productos_analizados: int
    periodo_desde: date
    periodo_hasta: date
    modelo: str
    generado_en: datetime

    model_config = {"from_attributes": True}

    @field_serializer("generado_en")
    def _ser_generado(self, v: datetime):
        return _utc(v)


class Coincidencia(BaseModel):
    campo: str  # etiqueta | producto | categoria | resumen
    valor: str


class SocioPorPreferenciaResponse(BaseModel):
    socio_id: int
    nombre_apellido: str
    dni: str
    telefono: str | None
    email: str
    relevancia: int
    coincidencias: list[Coincidencia]
    perfil_generado_en: datetime

    @field_serializer("perfil_generado_en")
    def _ser_generado(self, v: datetime):
        return _utc(v)


class EtiquetaConteoResponse(BaseModel):
    etiqueta: str
    socios: int
