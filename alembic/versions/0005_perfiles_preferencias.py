"""perfiles de preferencias de socios generados con IA

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-07 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "perfiles_socio",
        sa.Column("socio_id", sa.Integer(), sa.ForeignKey("socios.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("resumen", sa.Text(), nullable=False),
        sa.Column("etiquetas", JSONB(), nullable=False, server_default="[]"),
        sa.Column("categorias_favoritas", JSONB(), nullable=False, server_default="[]"),
        sa.Column("productos_favoritos", JSONB(), nullable=False, server_default="[]"),
        sa.Column("ventas_analizadas", sa.Integer(), nullable=False),
        sa.Column("productos_analizados", sa.Integer(), nullable=False),
        sa.Column("periodo_desde", sa.Date(), nullable=False),
        sa.Column("periodo_hasta", sa.Date(), nullable=False),
        sa.Column("ultima_venta_fecha", sa.DateTime(), nullable=False),
        sa.Column("modelo", sa.String(60), nullable=False),
        sa.Column("generado_en", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "lotes_perfiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.String(100), nullable=False, unique=True),
        sa.Column("estado", sa.String(10), nullable=False, server_default="ENVIADO"),
        sa.Column("modelo", sa.String(60), nullable=False),
        sa.Column("socios", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("exitosos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errores", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("creado_en", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("procesado_en", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_lotes_perfiles_estado", "lotes_perfiles", ["estado"])
    op.create_table(
        "lote_perfil_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lote_id", sa.Integer(), sa.ForeignKey("lotes_perfiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("socio_id", sa.Integer(), sa.ForeignKey("socios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ultima_venta_fecha", sa.DateTime(), nullable=False),
        sa.Column("ventas_analizadas", sa.Integer(), nullable=False),
        sa.Column("productos_analizados", sa.Integer(), nullable=False),
        sa.Column("periodo_desde", sa.Date(), nullable=False),
        sa.Column("periodo_hasta", sa.Date(), nullable=False),
        sa.Column("productos_enviados", JSONB(), nullable=False, server_default="[]"),
        sa.Column("estado", sa.String(10), nullable=False, server_default="PENDIENTE"),
        sa.Column("error", sa.String(300), nullable=True),
        sa.UniqueConstraint("lote_id", "socio_id", name="ux_lote_perfil_item"),
    )
    op.create_index("ix_lote_perfil_items_lote_id", "lote_perfil_items", ["lote_id"])
    op.create_index("ix_lote_perfil_items_socio_id", "lote_perfil_items", ["socio_id"])


def downgrade() -> None:
    op.drop_index("ix_lote_perfil_items_socio_id", table_name="lote_perfil_items")
    op.drop_index("ix_lote_perfil_items_lote_id", table_name="lote_perfil_items")
    op.drop_table("lote_perfil_items")
    op.drop_index("ix_lotes_perfiles_estado", table_name="lotes_perfiles")
    op.drop_table("lotes_perfiles")
    op.drop_table("perfiles_socio")
