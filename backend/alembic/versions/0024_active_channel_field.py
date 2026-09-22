"""Add active_channel to employee_profiles.

Revision ID: 0024_active_channel_field
Revises: 0023_telegram_identity_field

U5 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md,
KTD1): the vendor-contact half of this same field is added by a separate
supabase SQL migration
(`supabase/migrations/202609160004_v2_vendor_contact_active_channel.sql`),
since that table lives in the domain schema alembic does not own.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0024_active_channel_field"
down_revision: Union[str, None] = "0023_telegram_identity_field"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "employee_profiles",
        sa.Column("active_channel", sa.Text(), nullable=False, server_default="whatsapp"),
    )
    op.create_check_constraint(
        "ck_employee_profile_active_channel", "employee_profiles", "active_channel in ('whatsapp', 'telegram')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_employee_profile_active_channel", "employee_profiles", type_="check")
    op.drop_column("employee_profiles", "active_channel")
