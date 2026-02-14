"""add secrets table

Revision ID: a1b2c3d4e5f6
Revises: d65ee82c4afb
Create Date: 2026-02-13 22:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str]] = "d65ee82c4afb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create secrets table."""
    op.create_table(
        "secrets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("name", sa.String(255), unique=True, nullable=False),
        sa.Column("encrypted_data", sa.Text, nullable=False),
    )
    op.create_index("ix_secrets_name", "secrets", ["name"])


def downgrade() -> None:
    """Drop secrets table."""
    op.drop_index("ix_secrets_name", "secrets")
    op.drop_table("secrets")
