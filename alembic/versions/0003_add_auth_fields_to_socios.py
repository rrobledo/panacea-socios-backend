"""add auth fields to socios

Revision ID: 0003
Revises: 66e6d297a76b
Create Date: 2026-06-25 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "66e6d297a76b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("socios", sa.Column("password_hash", sa.String(200), nullable=True))
    op.add_column(
        "socios",
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("socios", "email_verified")
    op.drop_column("socios", "password_hash")
