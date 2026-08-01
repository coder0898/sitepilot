"""Track first-time account activation.

Revision ID: 0021_user_activation
Revises: 0020_access_requests
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0021_user_activation"
down_revision: Union[str, None] = "0020_access_requests"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("""
        UPDATE users AS u
        SET activated_at = CASE
            WHEN u.last_login_at IS NULL AND EXISTS (
                SELECT 1 FROM access_requests AS ar
                WHERE ar.supabase_user_id = u.supabase_user_id
                  AND ar.status = 'approved'
            ) THEN NULL
            ELSE COALESCE(u.last_login_at, u.created_at, now())
        END
    """)


def downgrade() -> None:
    op.drop_column("users", "activated_at")