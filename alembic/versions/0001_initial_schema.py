"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "socios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre_apellido", sa.String(length=200), nullable=False),
        sa.Column("telefono", sa.String(length=30), nullable=True),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("fecha_nacimiento", sa.Date(), nullable=True),
        sa.Column("dni", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("dni"),
    )
    op.create_index("ix_socios_id", "socios", ["id"])
    op.create_index("ix_socios_email", "socios", ["email"])
    op.create_index("ix_socios_dni", "socios", ["dni"])

    op.create_table(
        "preguntas_por_socios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("socio_id", sa.Integer(), nullable=False),
        sa.Column(
            "clave",
            sa.Enum(
                "que_producto_te_gustaria_que_sumemos",
                "que_parte_de_panacea_es_tu_favorita",
                "de_donde_son",
                name="clavepregunta",
            ),
            nullable=False,
        ),
        sa.Column("valor", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["socio_id"], ["socios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_preguntas_por_socios_id", "preguntas_por_socios", ["id"])
    op.create_index("ix_preguntas_por_socios_socio_id", "preguntas_por_socios", ["socio_id"])

    op.create_table(
        "registro_ventas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("socio_id", sa.Integer(), nullable=True),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("lugar", sa.String(length=200), nullable=True),
        sa.Column("importe", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.ForeignKeyConstraint(["socio_id"], ["socios.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_registro_ventas_id", "registro_ventas", ["id"])
    op.create_index("ix_registro_ventas_socio_id", "registro_ventas", ["socio_id"])

    op.create_table(
        "detalle_registro_ventas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("registro_venta_id", sa.Integer(), nullable=False),
        sa.Column("producto_id", sa.String(length=100), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.ForeignKeyConstraint(
            ["registro_venta_id"], ["registro_ventas.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_detalle_registro_ventas_id", "detalle_registro_ventas", ["id"])
    op.create_index(
        "ix_detalle_registro_ventas_registro_venta_id",
        "detalle_registro_ventas",
        ["registro_venta_id"],
    )


def downgrade() -> None:
    op.drop_table("detalle_registro_ventas")
    op.drop_table("registro_ventas")
    op.drop_table("preguntas_por_socios")
    op.drop_table("socios")
    op.execute("DROP TYPE IF EXISTS clavepregunta")
