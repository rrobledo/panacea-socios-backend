"""change_fecha_to_datetime_in_registro_ventas

Revision ID: 66e6d297a76b
Revises: 0002
Create Date: 2026-06-16 23:05:56.305008

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '66e6d297a76b'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'registro_ventas', 'fecha',
        existing_type=sa.DATE(),
        type_=sa.DateTime(),
        existing_nullable=False,
        postgresql_using='fecha::timestamp',
    )


def downgrade() -> None:
    op.alter_column(
        'registro_ventas', 'fecha',
        existing_type=sa.DateTime(),
        type_=sa.DATE(),
        existing_nullable=False,
        postgresql_using='fecha::date',
    )
