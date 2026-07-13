"""backfill execution task contractor mappings"""
from alembic import op

revision = "0009_task_vendor_map"
down_revision = "0008_execution_approval_workflow"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        insert into execution_project_contractors (id, project_id, contractor_id, scope, created_by, created_at)
        select gen_random_uuid(), t.project_id, t.assigned_contractor_id, 'Task assignment', t.created_by, now()
        from execution_tasks t
        where t.assigned_contractor_id is not null
        on conflict (project_id, contractor_id) do nothing
    """)


def downgrade():
    pass

