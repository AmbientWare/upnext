"""initial schema

Revision ID: d65ee82c4afb
Revises:
Create Date: 2026-02-13 20:13:00.376995

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d65ee82c4afb"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all tables."""
    # Auth tables
    op.create_table(
        "users",
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
        sa.Column("username", sa.String(255), unique=True, nullable=False),
        sa.Column("is_admin", sa.Boolean, nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "api_keys",
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
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("key_prefix", sa.String(12), nullable=False),
        sa.Column("name", sa.String(255), nullable=False, server_default="default"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        # Indexes
        sa.Index("ix_api_keys_user_id", "user_id"),
        sa.Index("ix_api_keys_key_hash", "key_hash"),
    )

    # Job tables
    op.create_table(
        "job_history",
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
        # Job identity
        sa.Column("function", sa.String(255), nullable=False),
        sa.Column("function_name", sa.String(255), nullable=False),
        sa.Column("job_type", sa.String(20), nullable=False, server_default="task"),
        # Status
        sa.Column("status", sa.String(20), nullable=False),
        # Timing
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("queue_wait_ms", sa.Float, nullable=True),
        # Execution
        sa.Column("attempts", sa.Integer, nullable=False, server_default="1"),
        sa.Column("max_retries", sa.Integer, nullable=False, server_default="0"),
        sa.Column("timeout", sa.Float, nullable=True),
        sa.Column("worker_id", sa.String(64), nullable=True),
        sa.Column("parent_id", sa.String(36), nullable=True),
        sa.Column("root_id", sa.String(36), nullable=False),
        # Progress
        sa.Column("progress", sa.Float, nullable=False, server_default="0.0"),
        # Data (JSON)
        sa.Column("kwargs", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("schedule", sa.String(120), nullable=True),
        sa.Column("cron_window_at", sa.Float, nullable=True),
        sa.Column("startup_reconciled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("startup_policy", sa.String(32), nullable=True),
        sa.Column("checkpoint", sa.JSON, nullable=True),
        sa.Column("checkpoint_at", sa.String(64), nullable=True),
        sa.Column("dlq_replayed_from", sa.String(64), nullable=True),
        sa.Column("dlq_failed_at", sa.String(64), nullable=True),
        sa.Column("event_pattern", sa.String(255), nullable=True),
        sa.Column("event_handler_name", sa.String(255), nullable=True),
        sa.Column("result", sa.JSON, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        # Single-column indexes
        sa.Index("ix_job_history_function", "function"),
        sa.Index("ix_job_history_function_name", "function_name"),
        sa.Index("ix_job_history_job_type", "job_type"),
        sa.Index("ix_job_history_status", "status"),
        sa.Index("ix_job_history_created_at", "created_at"),
        sa.Index("ix_job_history_worker_id", "worker_id"),
        sa.Index("ix_job_history_parent_id", "parent_id"),
        sa.Index("ix_job_history_root_id", "root_id"),
        # Compound indexes
        sa.Index("ix_job_history_function_status", "function", "status"),
        sa.Index("ix_job_history_created_at_status", "created_at", "status"),
        # Status CHECK constraint (inline = SQLite-safe)
        sa.CheckConstraint(
            "status IN ('pending', 'queued', 'active', 'complete', 'failed', 'cancelled', 'retrying')",
            name="ck_job_history_status",
        ),
    )

    op.create_table(
        "artifacts",
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
        # FK to job_history
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("job_history.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Artifact identity
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        # Content metadata
        sa.Column("size_bytes", sa.Integer, nullable=True),
        sa.Column("content_type", sa.String(120), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("storage_backend", sa.String(20), nullable=False),
        sa.Column("storage_key", sa.String(700), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="available"),
        sa.Column("error", sa.Text, nullable=True),
        # Indexes
        sa.Index("ix_artifacts_job_id", "job_id"),
        sa.Index("ix_artifacts_name", "name"),
        sa.Index("ix_artifacts_storage", "storage_backend", "storage_key"),
    )

    op.create_table(
        "pending_artifacts",
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
        # Job linkage (no FK — allows pre-job buffering)
        sa.Column("job_id", sa.String(36), nullable=False),
        # Artifact identity
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        # Content metadata
        sa.Column("size_bytes", sa.Integer, nullable=True),
        sa.Column("content_type", sa.String(120), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("storage_backend", sa.String(20), nullable=False),
        sa.Column("storage_key", sa.String(700), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("error", sa.Text, nullable=True),
        # Indexes
        sa.Index("ix_pending_artifacts_job_id", "job_id"),
        sa.Index("ix_pending_artifacts_created_at", "created_at"),
    )


def downgrade() -> None:
    """Drop all tables."""
    op.drop_table("pending_artifacts")
    op.drop_table("artifacts")
    op.drop_table("job_history")
    op.drop_table("api_keys")
    op.drop_table("users")
