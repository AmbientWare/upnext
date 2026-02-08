"""add job function_name column

Revision ID: 9f3a1d4c2b88
Revises: 6c7d9e2f1a10
Create Date: 2026-02-08 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9f3a1d4c2b88"
down_revision: Union[str, Sequence[str], None] = "6c7d9e2f1a10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("job_history") as batch_op:
        batch_op.add_column(sa.Column("function_name", sa.String(length=255), nullable=True))

    op.execute(
        "UPDATE job_history SET function_name = function "
        "WHERE function_name IS NULL OR function_name = ''"
    )

    with op.batch_alter_table("job_history") as batch_op:
        batch_op.alter_column(
            "function_name",
            existing_type=sa.String(length=255),
            nullable=False,
        )
        batch_op.create_index(
            "ix_job_history_function_name",
            ["function_name"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("job_history") as batch_op:
        batch_op.drop_index("ix_job_history_function_name")
        batch_op.drop_column("function_name")
