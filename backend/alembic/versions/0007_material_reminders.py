"""template-first execution and material reminders"""
from alembic import op
import sqlalchemy as sa
revision = "0007_material_reminders"
down_revision = "0006_execution_v2"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("execution_template_tasks", sa.Column("materials_required", sa.Text()))
    op.add_column("execution_template_tasks", sa.Column("material_reminder", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("execution_template_tasks", sa.Column("reminder_lead_days", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("execution_tasks", sa.Column("template_task_id", sa.Uuid(), sa.ForeignKey("execution_template_tasks.id", ondelete="SET NULL")))
    op.add_column("execution_tasks", sa.Column("materials_required", sa.Text()))
    op.add_column("execution_tasks", sa.Column("material_reminder", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("execution_tasks", sa.Column("reminder_lead_days", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("notification_outbox", sa.Column("notification_type", sa.Text(), nullable=False, server_default="task_assignment"))
    op.add_column("notification_outbox", sa.Column("scheduled_for", sa.DateTime(timezone=True)))

def downgrade():
    op.drop_column("notification_outbox", "scheduled_for")
    op.drop_column("notification_outbox", "notification_type")
    op.drop_column("execution_tasks", "reminder_lead_days")
    op.drop_column("execution_tasks", "material_reminder")
    op.drop_column("execution_tasks", "materials_required")
    op.drop_column("execution_tasks", "template_task_id")
    op.drop_column("execution_template_tasks", "reminder_lead_days")
    op.drop_column("execution_template_tasks", "material_reminder")
    op.drop_column("execution_template_tasks", "materials_required")

