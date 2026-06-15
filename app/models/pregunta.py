import enum

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ClavePregunta(str, enum.Enum):
    producto_deseado = "que_producto_te_gustaria_que_sumemos"
    parte_favorita = "que_parte_de_panacea_es_tu_favorita"
    origen = "de_donde_son"


class PreguntaPorSocio(Base):
    __tablename__ = "preguntas_por_socios"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    socio_id: Mapped[int] = mapped_column(ForeignKey("socios.id", ondelete="CASCADE"), nullable=False, index=True)
    clave: Mapped[ClavePregunta] = mapped_column(Enum(ClavePregunta), nullable=False)
    valor: Mapped[str] = mapped_column(Text, nullable=False)

    socio: Mapped["Socio"] = relationship("Socio", back_populates="preguntas")  # noqa: F821
