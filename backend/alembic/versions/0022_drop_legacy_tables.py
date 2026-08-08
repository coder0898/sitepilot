"""Drop the legacy vendor and execution tables.

Revision ID: 0022_drop_legacy_tables
Revises: 0021_user_activation

Completes the vendor consolidation. Two groups go here:

  * Legacy VENDOR tables. Vendor Hub (routes/communication.py,
    routes/vendors.py) now reads and writes `siteops_v2` vendor tables
    directly, which is what fixes the long-standing bug where a vendor
    created in the hub was invisible to every project-side feature until
    someone re-ran a one-time import by hand. `communication_logs` is
    replaced by `siteops_v2.vendor_notes`
    (202608080001_v2_vendor_notes.sql); the two-level `vendor_categories`
    tree is replaced by the flat, template-phase-derived
    `siteops_v2.capability_categories`, which is the vocabulary vendor
    delegation actually matches against.

  * Legacy EXECUTION tables. Superseded by `app.execution_models` /
    `siteops_v2` and holding zero rows at removal - all live project work
    is in `siteops_v2.project_tasks`. `execution_templates` and
    `execution_template_tasks` held only the boot-seeded "Interior Fit-out
    3 Day Standard" row, whose governed replacement lives in
    `siteops_v2.v2_templates`; `seed.py` no longer recreates it.

Deliberately NOT dropped: `users`, `employee_profiles`, `access_requests`,
`access_request_events`, `user_account_events`, `role_module_permissions`.
Those are the shared foundation - siteops_v2 carries foreign keys into
`users` and `employee_profiles` from nearly every table.

This migration is one-way. The dropped tables' data is not recoverable
from here; restore from a dump taken before it ran.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0022_drop_legacy_tables"
down_revision: Union[str, None] = "0021_user_activation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Ordered so every table is dropped before the tables it references.
LEGACY_TABLES = [
    # vendor satellites (reference vendors / vendor_categories / contacts)
    "communication_logs",
    "contractor_categories",
    "contractor_relationships",
    "vendor_status_history",
    "vendor_parent_migration_candidates",
    "vendor_contacts",
    # execution task satellites (reference execution_tasks)
    "execution_task_assignment_history",
    "execution_task_status_history",
    "execution_task_delay_reports",
    "execution_task_reschedules",
    # execution core
    "execution_tasks",
    "execution_days",
    "execution_project_contractors",
    "execution_projects",
    "execution_template_tasks",
    "execution_templates",
    # first-generation project/task tables
    "project_tasks",
    "project_vendors",
    "projects",
    "task_templates",
    # vendor roots last - everything above referenced them
    "vendors",
    "vendor_categories",
]


def upgrade() -> None:
    for table in LEGACY_TABLES:
        op.execute(f"drop table if exists public.{table}")


def downgrade() -> None:
    # One-way: these tables carried live foreign keys, check constraints and
    # data that this migration does not preserve. Recreating empty shells
    # would be misleading rather than a real downgrade - restore from a dump
    # taken before the upgrade instead.
    raise NotImplementedError(
        "0022 is not reversible. Restore the pre-migration database dump."
    )
