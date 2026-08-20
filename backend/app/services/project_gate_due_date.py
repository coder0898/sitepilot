"""Phase 5: resolving a planning-layer gate's due-by rule into a real date.

`V2ProjectExternalGate.required_by_type`/`required_by_value` encode one of
two mutually exclusive rules (`project_manual_gate.py` writes the same
convention this module reads):

- `required_by_type == "date"`: `required_by_value` is an ISO date string
  written directly by whoever created the gate.
- `required_by_type == "project_day"`: `required_by_value` is a plain
  integer string (`str(day)`), a day offset resolved into a calendar date
  the exact same way `project_schedule_dates.py` resolves
  `Task.planned_start_day`/`planned_end_day` - reusing
  `planned_date_for_day` rather than reimplementing the offset arithmetic,
  so the "day 1 is the start date itself" rule (KTD4) cannot drift between
  the two call sites.

Anything else - a null type, a null value, or a `project_day` gate whose
project has no `start_date` yet - resolves to `None`. This function never
raises and never invents a date: a gate legitimately has no due date when
its source data does not support one (e.g. a manually-created gate with no
`required_by_type` set at all).
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import ProjectExternalApproval
from app.project_models import V2Project, V2ProjectExternalGate
from app.services.project_schedule_dates import planned_date_for_day


def resolve_gate_due_at(
    required_by_type: str | None,
    required_by_value: str | None,
    project_start_date: date | None,
) -> date | None:
    """Resolve one gate's due-by rule into a calendar date, or None.

    Pure - takes plain values rather than a row - so it can be called both
    while `project_baseline.py` is still building an in-flight approval and
    from the backfill below, which joins back to already-persisted rows.
    """
    if not required_by_type or not required_by_value:
        return None
    if required_by_type == "date":
        try:
            return date.fromisoformat(required_by_value)
        except ValueError:
            return None
    if required_by_type == "project_day":
        if project_start_date is None:
            return None
        try:
            day = int(required_by_value)
        except ValueError:
            return None
        return planned_date_for_day(project_start_date, day)
    return None


class ProjectGateDueDateService:
    """Populates `due_at` for approvals activated before this unit existed.

    Mirrors `ProjectScheduleDateService.backfill()`'s shape: it never
    commits (the caller owns the transaction), and it is idempotent by
    construction - only `due_at IS NULL` rows are touched, so an approval
    that already carries a due date (or was correctly resolved to none by a
    prior run and then had its gate's rule change) is never silently
    overwritten by a stale re-run.
    """

    def __init__(self, db: Session):
        self.db = db

    def backfill(self, *, project_id: uuid.UUID | None = None) -> dict:
        """Resolve `due_at` for every already-activated approval missing it.

        Scoped to approvals with `due_at IS NULL`, joined back to their gate
        for `required_by_type`/`required_by_value` and to their project for
        `start_date`. An approval that resolves to `None` again (e.g. a
        manually-created gate with no `required_by_type`) is left untouched
        and not counted as updated - there is nothing to distinguish "not
        yet resolved" from "resolved to no due date" other than re-deriving
        it, which is exactly what happens here.
        """
        statement = (
            select(ProjectExternalApproval, V2ProjectExternalGate, V2Project)
            .join(V2ProjectExternalGate, V2ProjectExternalGate.id == ProjectExternalApproval.project_gate_id)
            .join(V2Project, V2Project.id == ProjectExternalApproval.project_id)
            .where(ProjectExternalApproval.due_at.is_(None))
            .order_by(ProjectExternalApproval.id)
        )
        if project_id is not None:
            statement = statement.where(ProjectExternalApproval.project_id == project_id)

        rows = list(self.db.execute(statement).all())
        approvals_updated = 0
        for approval, gate, project in rows:
            due_at = resolve_gate_due_at(gate.required_by_type, gate.required_by_value, project.start_date)
            if due_at is None:
                continue
            approval.due_at = due_at
            approvals_updated += 1
        if approvals_updated:
            self.db.flush()
        return {
            "approvals_scanned": len(rows),
            "approvals_updated": approvals_updated,
        }
