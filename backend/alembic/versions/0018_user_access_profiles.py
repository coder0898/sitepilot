"""Add Internal Employee and auditable employee profiles.

Revision ID: 0018_user_access_profiles
Revises: 0017_template_lifecycle
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0018_user_access_profiles"
down_revision: Union[str, None] = "0017_template_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'internal_employee'")

    op.create_table(
        "employee_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("employee_code", sa.Text(), nullable=False, unique=True),
        sa.Column("designation", sa.Text(), nullable=False),
        sa.Column("department", sa.Text()),
        sa.Column("availability", sa.Text(), nullable=False, server_default="available"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("availability in ('available', 'restricted', 'unavailable')", name="ck_employee_profile_availability"),
    )
    op.create_table(
        "user_account_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("from_role", sa.Text()),
        sa.Column("to_role", sa.Text()),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_user_account_events_user_created", "user_account_events", ["user_id", "created_at"])
    op.execute("""
        insert into employee_profiles (id, user_id, employee_code, designation, availability)
        select gen_random_uuid(), id, 'EMP-' || upper(substr(replace(id::text, '-', ''), 1, 8)),
               case role::text when 'admin' then 'Administrator' when 'project_manager' then 'Project Manager' else 'Site Supervisor' end,
               'available'
        from users where role::text in ('admin', 'project_manager', 'supervisor')
        on conflict (user_id) do nothing
    """)


def downgrade() -> None:
    op.drop_index("ix_user_account_events_user_created", table_name="user_account_events")
    op.drop_table("user_account_events")
    op.drop_table("employee_profiles")
    # PostgreSQL enum values are intentionally retained for safe downgrade.
