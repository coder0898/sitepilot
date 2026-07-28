"""Add controlled access request and approval workflow.

Revision ID: 0020_access_requests
Revises: 0019_supabase_auth
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0020_access_requests"
down_revision: Union[str, None] = "0019_supabase_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    user_role = postgresql.ENUM(
        "super_admin", "admin", "project_manager", "supervisor", "internal_employee",
        name="user_role", create_type=False,
    )
    op.create_table(
        "access_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text()),
        sa.Column("employee_code", sa.Text(), nullable=False),
        sa.Column("designation", sa.Text(), nullable=False),
        sa.Column("department", sa.Text()),
        sa.Column("requested_role", user_role, nullable=False),
        sa.Column("project_reference", sa.Text()),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending_email_verification"),
        sa.Column("email_verified_at", sa.DateTime(timezone=True)),
        sa.Column("supabase_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("submitted_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status in ('pending_email_verification', 'pending_approval', 'approved', 'rejected', 'expired', 'cancelled')",
            name="ck_access_request_status",
        ),
    )
    op.create_index("ix_access_requests_status_created", "access_requests", ["status", "created_at"])
    op.create_index("ix_access_requests_supabase_user_id", "access_requests", ["supabase_user_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_access_requests_open_email "
        "ON access_requests (lower(email)) "
        "WHERE status IN ('pending_email_verification', 'pending_approval')"
    )

    op.create_table(
        "access_request_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("access_request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("access_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_access_request_events_request_created", "access_request_events", ["access_request_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_access_request_events_request_created", table_name="access_request_events")
    op.drop_table("access_request_events")
    op.drop_index("uq_access_requests_open_email", table_name="access_requests")
    op.drop_index("ix_access_requests_supabase_user_id", table_name="access_requests")
    op.drop_index("ix_access_requests_status_created", table_name="access_requests")
    op.drop_table("access_requests")