"""add job lineage columns

Revision ID: 6c7d9e2f1a10
Revises: 3f2b7a9d4c1e
Create Date: 2026-02-07 00:00:01.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6c7d9e2f1a10"
down_revision: Union[str, Sequence[str], None] = "3f2b7a9d4c1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("job_history") as batch_op:
        batch_op.add_column(sa.Column("parent_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("root_id", sa.String(length=36), nullable=True))
        batch_op.create_index(
            "ix_job_history_parent_id", ["parent_id"], unique=False
        )
        batch_op.create_index("ix_job_history_root_id", ["root_id"], unique=False)

    # Ensure all rows have a lineage root.
    op.execute("UPDATE job_history SET root_id = id WHERE root_id IS NULL")

    with op.batch_alter_table("job_history") as batch_op:
        batch_op.alter_column(
            "root_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("job_history") as batch_op:
        batch_op.drop_index("ix_job_history_root_id")
        batch_op.drop_index("ix_job_history_parent_id")
        batch_op.drop_column("root_id")
        batch_op.drop_column("parent_id")
