"""engagement workflow and role module permissions"""
from alembic import op
import sqlalchemy as sa
revision = "0005_workflow_permissions"
down_revision = "0004_contractor_profiles"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("vendors", sa.Column("engagement_type", sa.Text(), nullable=False, server_default="main"))
    op.execute("update vendors set engagement_type = 'exclusive_subcontractor' where id in (select subcontractor_id from contractor_relationships)")
    op.create_table(
        "role_module_permissions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("module_key", sa.Text(), nullable=False),
        sa.Column("can_view", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("role", "module_key", name="uq_role_module_permission"),
    )
    defaults = (("admin", "execution"), ("admin", "communication"), ("admin", "users"), ("project_manager", "execution"), ("project_manager", "communication"), ("supervisor", "execution"), ("supervisor", "communication"))
    for role, module in defaults:
        op.execute(f"insert into role_module_permissions (id, role, module_key, can_view) values (gen_random_uuid(), '{role}', '{module}', true)")


def downgrade():
    op.drop_table("role_module_permissions")
    op.drop_column("vendors", "engagement_type")