"""sistema de puntos: reglas, ledger, beneficios, canjes y configuración

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-06 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "socios",
        sa.Column("saldo_puntos", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "reglas_puntos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("monto_por_punto", sa.Numeric(12, 2), nullable=False),
        sa.Column("multiplicador", sa.Numeric(5, 2), nullable=False, server_default="1"),
        sa.Column("tope_por_compra", sa.Integer(), nullable=True),
        sa.Column("vigente_desde", sa.Date(), nullable=False),
        sa.Column("vigente_hasta", sa.Date(), nullable=True),
        sa.Column("motivo", sa.String(200), nullable=False),
        sa.Column("creado_por", sa.String(200), nullable=True),
        sa.Column("creado_en", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("monto_por_punto > 0", name="ck_reglas_monto_positivo"),
        sa.CheckConstraint("multiplicador > 0", name="ck_reglas_multiplicador_positivo"),
        sa.CheckConstraint("vigente_hasta IS NULL OR vigente_hasta > vigente_desde", name="ck_reglas_vigencia"),
    )
    op.create_index("ix_reglas_puntos_vigente_desde", "reglas_puntos", ["vigente_desde"])

    op.create_table(
        "beneficios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nombre", sa.String(120), nullable=False),
        sa.Column("descripcion", sa.String(500), nullable=True),
        sa.Column("imagen_url", sa.String(500), nullable=True),
        sa.Column("costo_puntos", sa.Integer(), nullable=False),
        sa.Column("porcentaje_descuento", sa.Numeric(5, 2), nullable=False),
        sa.Column("tope_descuento", sa.Numeric(12, 2), nullable=True),
        sa.Column("dias_validez_cupon", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("limite_por_socio", sa.Integer(), nullable=True),
        sa.Column("stock", sa.Integer(), nullable=True),
        sa.Column("vigente_desde", sa.Date(), nullable=False),
        sa.Column("vigente_hasta", sa.Date(), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("creado_en", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("costo_puntos > 0", name="ck_beneficios_costo_positivo"),
        sa.CheckConstraint("porcentaje_descuento > 0 AND porcentaje_descuento <= 100", name="ck_beneficios_porcentaje"),
        sa.CheckConstraint("stock IS NULL OR stock >= 0", name="ck_beneficios_stock"),
    )

    op.create_table(
        "canjes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("socio_id", sa.Integer(), sa.ForeignKey("socios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("beneficio_id", sa.Integer(), sa.ForeignKey("beneficios.id"), nullable=False),
        sa.Column("codigo", sa.String(20), nullable=False, unique=True),
        sa.Column("origen", sa.String(10), nullable=False, server_default="CANJE"),
        sa.Column("titulo", sa.String(120), nullable=False),
        sa.Column("costo_puntos", sa.Integer(), nullable=False),
        sa.Column("porcentaje_descuento", sa.Numeric(5, 2), nullable=False),
        sa.Column("tope_descuento", sa.Numeric(12, 2), nullable=True),
        sa.Column("estado", sa.String(10), nullable=False, server_default="EMITIDO"),
        sa.Column("expira_en", sa.DateTime(), nullable=False),
        sa.Column("venta_id", sa.Integer(), sa.ForeignKey("registro_ventas.id", ondelete="SET NULL"), nullable=True, unique=True),
        sa.Column("monto_descontado", sa.Numeric(12, 2), nullable=True),
        sa.Column("creado_en", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("usado_en", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_canjes_socio_id", "canjes", ["socio_id"])
    op.create_index("ix_canjes_beneficio_id", "canjes", ["beneficio_id"])
    op.create_index("ix_canjes_estado", "canjes", ["estado"])

    op.create_table(
        "movimientos_puntos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("socio_id", sa.Integer(), sa.ForeignKey("socios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("puntos", sa.Integer(), nullable=False),
        sa.Column("venta_id", sa.Integer(), sa.ForeignKey("registro_ventas.id", ondelete="SET NULL"), nullable=True),
        sa.Column("canje_id", sa.Integer(), sa.ForeignKey("canjes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("regla_id", sa.Integer(), sa.ForeignKey("reglas_puntos.id"), nullable=True),
        sa.Column("monto_base", sa.Numeric(12, 2), nullable=True),
        sa.Column("descripcion", sa.String(300), nullable=True),
        sa.Column("creado_por", sa.String(200), nullable=True),
        sa.Column("creado_en", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_movimientos_puntos_socio_id", "movimientos_puntos", ["socio_id"])
    op.create_index(
        "ux_mov_venta_tipo", "movimientos_puntos", ["venta_id", "tipo"],
        unique=True, postgresql_where=sa.text("venta_id IS NOT NULL"),
    )
    op.create_index(
        "ux_mov_canje_tipo", "movimientos_puntos", ["canje_id", "tipo"],
        unique=True, postgresql_where=sa.text("canje_id IS NOT NULL"),
    )

    op.create_table(
        "config_programa",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("meses_expiracion_puntos", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("costo_juego_maquina", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("programa_activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("actualizado_en", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.execute("INSERT INTO config_programa (id) VALUES (1)")


def downgrade() -> None:
    op.drop_table("config_programa")
    op.drop_index("ux_mov_canje_tipo", table_name="movimientos_puntos")
    op.drop_index("ux_mov_venta_tipo", table_name="movimientos_puntos")
    op.drop_index("ix_movimientos_puntos_socio_id", table_name="movimientos_puntos")
    op.drop_table("movimientos_puntos")
    op.drop_table("canjes")
    op.drop_table("beneficios")
    op.drop_index("ix_reglas_puntos_vigente_desde", table_name="reglas_puntos")
    op.drop_table("reglas_puntos")
    op.drop_column("socios", "saldo_puntos")
