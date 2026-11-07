"""Perfil de gustos y preferencias de cada socio, generado con IA a partir de sus compras."""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EstadoLote:
    ENVIADO = "ENVIADO"      # enviado a la Message Batches API, sin procesar
    PROCESADO = "PROCESADO"  # resultados guardados
    ERROR = "ERROR"          # no se pudo procesar (inexistente o demasiado viejo)


class EstadoItem:
    PENDIENTE = "PENDIENTE"
    OK = "OK"
    ERROR = "ERROR"


class PerfilSocio(Base):
    """Uno por socio; se reemplaza entero en cada regeneración."""
    __tablename__ = "perfiles_socio"

    socio_id: Mapped[int] = mapped_column(ForeignKey("socios.id", ondelete="CASCADE"), primary_key=True)
    resumen: Mapped[str] = mapped_column(Text, nullable=False)
    etiquetas: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    categorias_favoritas: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    productos_favoritos: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    ventas_analizadas: Mapped[int] = mapped_column(Integer, nullable=False)
    productos_analizados: Mapped[int] = mapped_column(Integer, nullable=False)
    periodo_desde: Mapped[date] = mapped_column(Date, nullable=False)
    periodo_hasta: Mapped[date] = mapped_column(Date, nullable=False)
    # Fecha (UTC naive) de la última venta considerada: define si hay compras nuevas
    ultima_venta_fecha: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    modelo: Mapped[str] = mapped_column(String(60), nullable=False)
    generado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class LotePerfiles(Base):
    __tablename__ = "lotes_perfiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    estado: Mapped[str] = mapped_column(String(10), nullable=False, default=EstadoLote.ENVIADO, index=True)
    modelo: Mapped[str] = mapped_column(String(60), nullable=False)
    socios: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exitosos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errores: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    creado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    procesado_en: Mapped[datetime | None] = mapped_column(DateTime)


class LotePerfilItem(Base):
    """Un socio dentro de un lote, con la base que se envió (para procesar el resultado)."""
    __tablename__ = "lote_perfil_items"
    __table_args__ = (UniqueConstraint("lote_id", "socio_id", name="ux_lote_perfil_item"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    lote_id: Mapped[int] = mapped_column(ForeignKey("lotes_perfiles.id", ondelete="CASCADE"), nullable=False, index=True)
    socio_id: Mapped[int] = mapped_column(ForeignKey("socios.id", ondelete="CASCADE"), nullable=False, index=True)
    ultima_venta_fecha: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ventas_analizadas: Mapped[int] = mapped_column(Integer, nullable=False)
    productos_analizados: Mapped[int] = mapped_column(Integer, nullable=False)
    periodo_desde: Mapped[date] = mapped_column(Date, nullable=False)
    periodo_hasta: Mapped[date] = mapped_column(Date, nullable=False)
    productos_enviados: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    estado: Mapped[str] = mapped_column(String(10), nullable=False, default=EstadoItem.PENDIENTE)
    error: Mapped[str | None] = mapped_column(String(300))
