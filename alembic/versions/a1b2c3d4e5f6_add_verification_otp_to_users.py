"""add verification_otp for email signup

Revision ID: a1b2c3d4e5f6
Revises: 92ed7c493253
Create Date: 2026-05-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "92ed7c493253"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("verification_otp", sa.String(length=10), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("verification_otp_expiry", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "verification_otp_expiry")
    op.drop_column("users", "verification_otp")
