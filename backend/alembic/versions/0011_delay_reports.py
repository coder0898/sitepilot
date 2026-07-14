"""supervisor delay reports and PM confirmation"""
from alembic import op
import sqlalchemy as sa

revision = "0011_delay_reports"
down_revision = "0010_task_reschedule"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "execution_task_delay_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("execution_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("proposed_date", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("reviewed_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_execution_task_delay_reports_task_id", "execution_task_delay_reports", ["task_id"])
    op.create_index("ix_execution_task_delay_reports_status", "execution_task_delay_reports", ["status"])


def downgrade():
    op.drop_index("ix_execution_task_delay_reports_status", table_name="execution_task_delay_reports")
    op.drop_index("ix_execution_task_delay_reports_task_id", table_name="execution_task_delay_reports")
    op.drop_table("execution_task_delay_reports")