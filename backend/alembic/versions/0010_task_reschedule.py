"""task overdue rescheduling and audit history"""
from alembic import op
import sqlalchemy as sa

revision = "0010_task_reschedule"
down_revision = "0009_task_vendor_map"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("execution_tasks", sa.Column("rescheduled_date", sa.Date()))
    op.add_column("execution_tasks", sa.Column("delay_reason", sa.Text()))
    op.add_column("execution_tasks", sa.Column("rescheduled_at", sa.DateTime(timezone=True)))
    op.add_column("execution_tasks", sa.Column("rescheduled_by", sa.Uuid(), sa.ForeignKey("users.id")))
    op.add_column("execution_tasks", sa.Column("reschedule_count", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "execution_task_reschedules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("execution_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("previous_date", sa.Date(), nullable=False),
        sa.Column("new_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_execution_task_reschedules_task_id", "execution_task_reschedules", ["task_id"])


def downgrade():
    op.drop_index("ix_execution_task_reschedules_task_id", table_name="execution_task_reschedules")
    op.drop_table("execution_task_reschedules")
    op.drop_column("execution_tasks", "reschedule_count")
    op.drop_column("execution_tasks", "rescheduled_by")
    op.drop_column("execution_tasks", "rescheduled_at")
    op.drop_column("execution_tasks", "delay_reason")
    op.drop_column("execution_tasks", "rescheduled_date")