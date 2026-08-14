"""Backfill the execution layer for projects activated before U8/U9 landed.

U9 dates every task at activation and U8 instantiates a project's external
approvals there too. Both units also shipped a `backfill()` for the projects
that were already active when they landed - and neither backfill had a caller
outside its own tests, so on a database with pre-existing projects the code
was complete and the data was not: tasks with no `planned_start_date`, and
planning-layer gates with no runtime approval to decide.

The consequence is quiet rather than loud. Nothing errors; the timeline
reports "no dated tasks", every variance reads "not measured", the overdue
tile stays at zero, and readiness never names an approval as a blocker -
each of which looks like a healthy project rather than missing data.

This is a one-shot operational script rather than an API route on purpose. It
is a migration, not a feature: exposing it as an endpoint would leave a
permanent surface whose only correct number of uses is one per database.

Both backfills are idempotent by construction - they write only differences
and skip what already exists - so re-running is safe and reports zeros.

Usage, from the backend container:

    python -m scripts.backfill_execution_schedule --dry-run
    python -m scripts.backfill_execution_schedule
    python -m scripts.backfill_execution_schedule --project-id <uuid>
"""

from __future__ import annotations

import argparse
import sys
import uuid

from app.database import SessionLocal
from app.services.project_baseline import ProjectApprovalInstantiationService
from app.services.project_schedule_dates import ProjectScheduleDateService


def _format(title: str, report: dict) -> str:
    body = "\n".join(f"    {key.replace('_', ' ')}: {value}" for key, value in report.items())
    return f"  {title}\n{body}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill execution-layer schedule dates and external approvals.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Compute and report what would change, then roll back instead of committing.",
    )
    parser.add_argument(
        "--project-id", type=uuid.UUID, default=None,
        help="Limit the backfill to one project. Omit to cover every eligible project.",
    )
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        # Dates first: an approval's coverage does not depend on them, but a
        # reader looking at the result of a partial run is better served by
        # dated tasks with no approvals than approvals over undated tasks.
        dates = ProjectScheduleDateService(db).backfill(project_id=args.project_id)
        approvals = ProjectApprovalInstantiationService(db).backfill(project_id=args.project_id)

        if args.dry_run:
            db.rollback()
        else:
            db.commit()

    print("Schedule-date backfill" + (" (dry run - nothing written)" if args.dry_run else ""))
    print(_format("dates", dates))
    print(_format("approvals", approvals))
    if args.dry_run:
        print("\nRolled back. Re-run without --dry-run to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
