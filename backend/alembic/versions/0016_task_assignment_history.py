"""Add auditable task assignment events for Phase 3.

Revision ID: 0016_task_assignment_history
Revises: 0015_remove_notifications
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0016_task_assignment_history"
down_revision: Union[str, None] = "0015_remove_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "execution_task_assignment_history",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("execution_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("from_contractor_id", sa.Uuid(), sa.ForeignKey("vendors.id", ondelete="SET NULL")),
        sa.Column("from_subcontractor_id", sa.Uuid(), sa.ForeignKey("vendors.id", ondelete="SET NULL")),
        sa.Column("to_contractor_id", sa.Uuid(), sa.ForeignKey("vendors.id", ondelete="SET NULL")),
        sa.Column("to_subcontractor_id", sa.Uuid(), sa.ForeignKey("vendors.id", ondelete="SET NULL")),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("changed_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_task_assignment_history_task", "execution_task_assignment_history", ["task_id", "created_at"])
    op.execute("""
        insert into execution_task_assignment_history (
            id, task_id, event_type, to_contractor_id, to_subcontractor_id, reason, changed_by, created_at
        )
        select gen_random_uuid(), id, 'TASK_ASSIGNED', assigned_contractor_id, assigned_subcontractor_id,
               'Existing assignment migrated into Phase 3 audit history', created_by, coalesce(updated_at, created_at)
        from execution_tasks
        where assigned_contractor_id is not null or assigned_subcontractor_id is not null
    """)


def downgrade() -> None:
    op.drop_index("ix_task_assignment_history_task", table_name="execution_task_assignment_history")
    op.drop_table("execution_task_assignment_history")