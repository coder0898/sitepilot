"""complete execution approval workflow"""
from alembic import op
import sqlalchemy as sa
revision = "0008_execution_approval_workflow"
down_revision = "0007_material_reminders"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("execution_tasks", sa.Column("proof_required", sa.Text()))
    op.add_column("execution_tasks", sa.Column("submitted_at", sa.DateTime(timezone=True)))
    op.add_column("execution_tasks", sa.Column("reviewed_at", sa.DateTime(timezone=True)))
    op.add_column("execution_tasks", sa.Column("reviewed_by", sa.Uuid(), sa.ForeignKey("users.id")))
    op.add_column("execution_tasks", sa.Column("rejection_reason", sa.Text()))

def downgrade():
    op.drop_column("execution_tasks", "rejection_reason")
    op.drop_column("execution_tasks", "reviewed_by")
    op.drop_column("execution_tasks", "reviewed_at")
    op.drop_column("execution_tasks", "submitted_at")
    op.drop_column("execution_tasks", "proof_required")
