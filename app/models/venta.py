from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RegistroVenta(Base):
    __tablename__ = "registro_ventas"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    socio_id: Mapped[int | None] = mapped_column(ForeignKey("socios.id", ondelete="SET NULL"), index=True)
    fecha: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    lugar: Mapped[str | None] = mapped_column(String(200))
    importe: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    socio: Mapped["Socio | None"] = relationship("Socio", back_populates="ventas")  # noqa: F821
    detalles: Mapped[list["DetalleRegistroVenta"]] = relationship(
        "DetalleRegistroVenta", back_populates="venta", cascade="all, delete-orphan"
    )


class DetalleRegistroVenta(Base):
    __tablename__ = "detalle_registro_ventas"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    registro_venta_id: Mapped[int] = mapped_column(
        ForeignKey("registro_ventas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    producto_id: Mapped[str] = mapped_column(String(100), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    venta: Mapped["RegistroVenta"] = relationship("RegistroVenta", back_populates="detalles")
