"""notification delivery lifecycle and audit"""

import sqlalchemy as sa
from alembic import op


revision = "0013_notification_delivery"
down_revision = "0012_exec_perf_indexes"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("notification_outbox", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("notification_outbox", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("notification_outbox", sa.Column("next_attempt_at", sa.DateTime(timezone=True)))
    op.add_column("notification_outbox", sa.Column("last_attempt_at", sa.DateTime(timezone=True)))
    op.add_column("notification_outbox", sa.Column("sent_at", sa.DateTime(timezone=True)))
    op.add_column("notification_outbox", sa.Column("delivered_at", sa.DateTime(timezone=True)))
    op.add_column("notification_outbox", sa.Column("failure_reason", sa.Text()))
    op.add_column("notification_outbox", sa.Column("provider_message_id", sa.Text()))
    op.add_column("notification_outbox", sa.Column("idempotency_key", sa.Text()))
    op.add_column("notification_outbox", sa.Column("locked_at", sa.DateTime(timezone=True)))
    op.add_column("notification_outbox", sa.Column("lock_token", sa.Uuid()))
    op.add_column("notification_outbox", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))

    op.execute("""
        update notification_outbox
        set idempotency_key = md5(id::text || ':' || task_id::text || ':' || recipient_type || ':' || notification_type),
            status = case when phone is null or btrim(phone) = '' then 'failed' else 'scheduled' end,
            failure_reason = case when phone is null or btrim(phone) = '' then 'Recipient phone number is missing.' else null end
    """)
    op.alter_column("notification_outbox", "idempotency_key", nullable=False)
    op.create_index("uq_notification_outbox_idempotency_key", "notification_outbox", ["idempotency_key"], unique=True)
    op.create_index("ix_notification_outbox_delivery_due", "notification_outbox", ["status", "next_attempt_at", "scheduled_for"])

    op.create_table(
        "notification_delivery_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("notification_id", sa.Uuid(), sa.ForeignKey("notification_outbox.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False, server_default="mock"),
        sa.Column("provider_message_id", sa.Text()),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("notification_id", "attempt_no", name="uq_notification_delivery_attempt"),
    )
    op.create_index("ix_notification_delivery_attempts_notification_id", "notification_delivery_attempts", ["notification_id"])

    op.create_table(
        "mock_notification_receipts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column("provider_message_id", sa.Text(), nullable=False, unique=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade():
    op.drop_table("mock_notification_receipts")
    op.drop_index("ix_notification_delivery_attempts_notification_id", table_name="notification_delivery_attempts")
    op.drop_table("notification_delivery_attempts")
    op.drop_index("ix_notification_outbox_delivery_due", table_name="notification_outbox")
    op.drop_index("uq_notification_outbox_idempotency_key", table_name="notification_outbox")
    for column in (
        "updated_at", "lock_token", "locked_at", "idempotency_key", "provider_message_id",
        "failure_reason", "delivered_at", "sent_at", "last_attempt_at", "next_attempt_at",
        "max_attempts", "attempt_count",
    ):
        op.drop_column("notification_outbox", column)
