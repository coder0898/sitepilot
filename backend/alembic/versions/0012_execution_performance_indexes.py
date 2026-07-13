"""execution workspace performance indexes"""

from alembic import op


revision = "0012_exec_perf_indexes"
down_revision = "0011_delay_reports"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_execution_projects_project_manager_id", "execution_projects", ["project_manager_id"])
    op.create_index("ix_execution_projects_supervisor_id", "execution_projects", ["supervisor_id"])
    op.create_index("ix_execution_days_project_id", "execution_days", ["project_id"])
    op.create_index("ix_execution_tasks_project_id", "execution_tasks", ["project_id"])
    op.create_index("ix_notification_outbox_task_id", "notification_outbox", ["task_id"])
    op.create_index("ix_execution_template_tasks_template_id", "execution_template_tasks", ["template_id"])


def downgrade():
    op.drop_index("ix_execution_template_tasks_template_id", table_name="execution_template_tasks")
    op.drop_index("ix_notification_outbox_task_id", table_name="notification_outbox")
    op.drop_index("ix_execution_tasks_project_id", table_name="execution_tasks")
    op.drop_index("ix_execution_days_project_id", table_name="execution_days")
    op.drop_index("ix_execution_projects_supervisor_id", table_name="execution_projects")
    op.drop_index("ix_execution_projects_project_manager_id", table_name="execution_projects")
