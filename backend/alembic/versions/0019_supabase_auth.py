"""Move authentication ownership to Supabase Auth.

Revision ID: 0019_supabase_auth
Revises: 0018_user_access_profiles
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0019_supabase_auth"
down_revision: Union[str, None] = "0018_user_access_profiles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("users", "password_hash", existing_type=sa.Text(), nullable=True)
    op.create_index("uq_users_supabase_user_id", "users", ["supabase_user_id"], unique=True)
    op.drop_table("password_reset_tokens")


def downgrade() -> None:
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.Text(), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.drop_index("uq_users_supabase_user_id", table_name="users")
    op.execute("UPDATE users SET password_hash = 'supabase-managed' WHERE password_hash IS NULL")
    op.alter_column("users", "password_hash", existing_type=sa.Text(), nullable=False)
