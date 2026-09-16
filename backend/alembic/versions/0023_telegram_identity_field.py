"""Add telegram_chat_id to employee_profiles.

Revision ID: 0023_telegram_identity_field
Revises: 0022_drop_legacy_tables

U4 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md):
`employee_profiles` lives in the `public` schema (this repo's baseline
schema, migrated via alembic) - the equivalent column on
`siteops_v2.vendor_contacts` is added by a separate supabase SQL migration
(`supabase/migrations/202609160003_v2_vendor_contact_telegram_chat_id.sql`),
since that table belongs to the domain schema alembic does not own.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0023_telegram_identity_field"
down_revision: Union[str, None] = "0022_drop_legacy_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("employee_profiles", sa.Column("telegram_chat_id", sa.Text()))
    op.create_index(
        "uq_employee_profiles_telegram_chat_id", "employee_profiles", ["telegram_chat_id"], unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_employee_profiles_telegram_chat_id", table_name="employee_profiles")
    op.drop_column("employee_profiles", "telegram_chat_id")
