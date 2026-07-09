"""initial siteops schema"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

user_role = postgresql.ENUM("super_admin", "admin", "project_manager", "supervisor", name="user_role", create_type=False)
task_status = postgresql.ENUM("pending", "in_progress", "submitted", "completed", "rejected", "delayed", "blocked", name="task_status", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("users"):
        return
    op.execute("create extension if not exists pgcrypto")
    user_role.create(op.get_bind(), checkfirst=True)
    task_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("supabase_user_id", sa.Uuid()),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "vendors",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("contact_person", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=False),
        sa.Column("whatsapp", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("client_name", sa.Text(), nullable=False),
        sa.Column("site_address", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("target_handover_date", sa.Date(), nullable=False),
        sa.Column("project_manager_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("supervisor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "task_templates",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("day_no", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("vendor_category", sa.Text()),
        sa.Column("default_notes", sa.Text()),
        sa.Column("description", sa.Text()),
        sa.Column("supervisor_instruction", sa.Text()),
        sa.Column("pm_instruction", sa.Text()),
        sa.Column("proof_required", sa.Text()),
        sa.Column("dependency_note", sa.Text()),
        sa.UniqueConstraint("day_no", "sort_order", "title", name="uq_task_templates_day_order_title"),
    )
    op.create_table(
        "project_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("template_task_id", sa.Uuid(), sa.ForeignKey("task_templates.id")),
        sa.Column("day_no", sa.Integer(), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date()),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("vendor_id", sa.Uuid(), sa.ForeignKey("vendors.id")),
        sa.Column("status", task_status, nullable=False, server_default="pending"),
        sa.Column("description", sa.Text()),
        sa.Column("supervisor_instruction", sa.Text()),
        sa.Column("pm_instruction", sa.Text()),
        sa.Column("proof_required", sa.Text()),
        sa.Column("dependency_note", sa.Text()),
        sa.Column("admin_note", sa.Text()),
        sa.Column("supervisor_note", sa.Text()),
        sa.Column("delay_reason", sa.Text()),
        sa.Column("proof_url", sa.Text()),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.Text(), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_project_tasks_project_date", "project_tasks", ["project_id", "scheduled_date"])
    op.create_index("idx_project_tasks_status", "project_tasks", ["status"])
    op.create_index("idx_projects_supervisor", "projects", ["supervisor_id"])
    op.create_index("idx_projects_pm", "projects", ["project_manager_id"])


def downgrade() -> None:
    op.drop_table("password_reset_tokens")
    op.drop_table("project_tasks")
    op.drop_table("task_templates")
    op.drop_table("projects")
    op.drop_table("vendors")
    op.drop_table("users")
    task_status.drop(op.get_bind(), checkfirst=True)
    user_role.drop(op.get_bind(), checkfirst=True)

