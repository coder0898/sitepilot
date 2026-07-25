"""Add execution template lifecycle timestamps.

Revision ID: 0017_template_lifecycle
Revises: 0016_task_assignment_history
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0017_template_lifecycle"
down_revision: Union[str, None] = "0016_task_assignment_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "execution_templates",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_column("execution_templates", "updated_at")