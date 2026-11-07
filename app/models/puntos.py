"""Sistema de puntos de lealtad.

- `ReglaPuntos`: tabla de conversión monto → puntos, versionada por vigencia.
- `MovimientoPuntos`: ledger inmutable; el saldo es la suma de los movimientos
  (cacheado en `socios.saldo_puntos`, actualizado en la misma transacción).
- `Beneficio`: catálogo de descuentos canjeables con puntos.
- `Canje`: cupón emitido al canjear (snapshot de costo y %).
- `ConfigPrograma`: parámetros globales (fila única id=1).

Fechas: `vigente_desde`/`vigente_hasta` son fechas locales (America/Argentina/Cordoba).
En reglas `vigente_hasta` es EXCLUSIVO (= `vigente_desde` de la regla siguiente);
en beneficios `vigente_hasta` es INCLUSIVO. Los timestamps se guardan en UTC naive,
igual que `registro_ventas.fecha`.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TipoMovimiento:
    ACUMULACION = "ACUMULACION"
    CANJE = "CANJE"
    JUEGO = "JUEGO"
    REVERSO_COMPRA = "REVERSO_COMPRA"
    EXPIRACION = "EXPIRACION"
    AJUSTE = "AJUSTE"
    MIGRACION = "MIGRACION"
    DEVOLUCION_CANJE = "DEVOLUCION_CANJE"  # puntos devueltos al anular una venta con beneficio de mostrador


class EstadoCanje:
    EMITIDO = "EMITIDO"
    USADO = "USADO"
    EXPIRADO = "EXPIRADO"
    CANCELADO = "CANCELADO"


class OrigenCanje:
    CANJE = "CANJE"
    MAQUINA = "MAQUINA"
    MOSTRADOR = "MOSTRADOR"  # beneficio elegido por el personal al registrar la venta


class ReglaPuntos(Base):
    __tablename__ = "reglas_puntos"

    id: Mapped[int] = mapped_column(primary_key=True)
    monto_por_punto: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    multiplicador: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("1"))
    tope_por_compra: Mapped[int | None] = mapped_column(Integer)
    vigente_desde: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    vigente_hasta: Mapped[date | None] = mapped_column(Date)
    motivo: Mapped[str] = mapped_column(String(200), nullable=False)
    creado_por: Mapped[str | None] = mapped_column(String(200))
    creado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class Beneficio(Base):
    __tablename__ = "beneficios"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(500))
    imagen_url: Mapped[str | None] = mapped_column(String(500))
    costo_puntos: Mapped[int] = mapped_column(Integer, nullable=False)
    porcentaje_descuento: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    tope_descuento: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    dias_validez_cupon: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    limite_por_socio: Mapped[int | None] = mapped_column(Integer)
    stock: Mapped[int | None] = mapped_column(Integer)
    vigente_desde: Mapped[date] = mapped_column(Date, nullable=False)
    vigente_hasta: Mapped[date | None] = mapped_column(Date)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class Canje(Base):
    __tablename__ = "canjes"

    id: Mapped[int] = mapped_column(primary_key=True)
    socio_id: Mapped[int] = mapped_column(ForeignKey("socios.id", ondelete="CASCADE"), nullable=False, index=True)
    beneficio_id: Mapped[int] = mapped_column(ForeignKey("beneficios.id"), nullable=False, index=True)
    codigo: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    origen: Mapped[str] = mapped_column(String(10), nullable=False, default=OrigenCanje.CANJE)
    # Snapshot del beneficio al momento del canje
    titulo: Mapped[str] = mapped_column(String(120), nullable=False)
    costo_puntos: Mapped[int] = mapped_column(Integer, nullable=False)
    porcentaje_descuento: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    tope_descuento: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    estado: Mapped[str] = mapped_column(String(10), nullable=False, default=EstadoCanje.EMITIDO, index=True)
    expira_en: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Un cupón por compra: venta_id es único
    venta_id: Mapped[int | None] = mapped_column(
        ForeignKey("registro_ventas.id", ondelete="SET NULL"), unique=True
    )
    monto_descontado: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    creado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    usado_en: Mapped[datetime | None] = mapped_column(DateTime)

    beneficio: Mapped["Beneficio"] = relationship("Beneficio")


class MovimientoPuntos(Base):
    __tablename__ = "movimientos_puntos"
    __table_args__ = (
        # Idempotencia: como máximo un movimiento por (origen, tipo)
        Index("ux_mov_venta_tipo", "venta_id", "tipo", unique=True, postgresql_where=text("venta_id IS NOT NULL")),
        Index("ux_mov_canje_tipo", "canje_id", "tipo", unique=True, postgresql_where=text("canje_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    socio_id: Mapped[int] = mapped_column(ForeignKey("socios.id", ondelete="CASCADE"), nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    puntos: Mapped[int] = mapped_column(Integer, nullable=False)
    venta_id: Mapped[int | None] = mapped_column(ForeignKey("registro_ventas.id", ondelete="SET NULL"))
    canje_id: Mapped[int | None] = mapped_column(ForeignKey("canjes.id", ondelete="SET NULL"))
    regla_id: Mapped[int | None] = mapped_column(ForeignKey("reglas_puntos.id"))
    monto_base: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    descripcion: Mapped[str | None] = mapped_column(String(300))
    creado_por: Mapped[str | None] = mapped_column(String(200))
    creado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class ConfigPrograma(Base):
    __tablename__ = "config_programa"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    meses_expiracion_puntos: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    costo_juego_maquina: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    programa_activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
