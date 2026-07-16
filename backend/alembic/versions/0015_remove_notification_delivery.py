"""Remove the deferred mock notification delivery subsystem.

Revision ID: 0015_remove_notifications
Revises: 0014_vendor_category_phase1
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0015_remove_notifications"
down_revision: Union[str, None] = "0014_vendor_category_phase1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("mock_notification_receipts")
    op.drop_table("notification_delivery_attempts")
    op.drop_table("notification_outbox")


def downgrade() -> None:
    op.create_table(
        "notification_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("execution_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_type", sa.Text(), nullable=False),
        sa.Column("recipient_name", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text()),
        sa.Column("message_preview", sa.Text(), nullable=False),
        sa.Column("notification_type", sa.Text(), nullable=False, server_default="task_assignment"),
        sa.Column("scheduled_for", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False, server_default="scheduled"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("provider_message_id", sa.Text()),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("lock_token", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_notification_outbox_task_id", "notification_outbox", ["task_id"])
    op.create_index("uq_notification_outbox_idempotency_key", "notification_outbox", ["idempotency_key"], unique=True)
    op.create_index("ix_notification_outbox_delivery_due", "notification_outbox", ["status", "next_attempt_at", "scheduled_for"])
    op.create_table(
        "notification_delivery_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("notification_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("notification_outbox.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False, server_default="mock"),
        sa.Column("provider_message_id", sa.Text()),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("notification_id", "attempt_no", name="uq_notification_delivery_attempt"),
    )
    op.create_index("ix_notification_delivery_attempts_notification_id", "notification_delivery_attempts", ["notification_id"])
    op.create_table(
        "mock_notification_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column("provider_message_id", sa.Text(), nullable=False, unique=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )