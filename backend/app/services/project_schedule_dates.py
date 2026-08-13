"""U9: resolve baseline day offsets into real calendar dates.

The template plans in day offsets (`planned_start_day` / `planned_end_day`),
which are portable across projects but mean nothing on a site calendar. This
module is the single place those offsets become dates, so the rule cannot
drift between activation and any later backfill.

Three decisions are pinned here:

- **Day 1 is the start date itself** (KTD4), so the arithmetic is
  `start_date + (day - 1)`. This matches `derive_target_handover_date` in
  `app/routes/projects_v2.py` - a 45-day project starting 11 Aug hands over
  on 24 Sep, start + 44 - and the `plannedDate` helper already shipped in
  `frontend/src/features/projects/components/PhaseOverviewDrawer.jsx`.
- **Calendar days, not working days** (KTD4, user-directed). No weekend or
  holiday calendar is consulted. `timedelta` therefore needs no calendar
  awareness, and month and year boundaries fall out of `date` arithmetic
  for free.
- **The day offsets are never written** (R13). They are the frozen baseline
  the whole variance track is measured against; only the derived
  `planned_start_date` / `planned_end_date` columns are assigned here.

Pre-activation tasks get no dates. They sit outside the execution window,
carry no day offsets in a valid template, and a date invented for them would
read as a commitment nobody made.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import Task
from app.project_models import V2Project

PRE_ACTIVATION = "pre_activation"


def planned_date_for_day(start_date: date, day: int | None) -> date | None:
    """Return the calendar date for a 1-based day offset, or None.

    Day 1 is `start_date` itself, so the offset applied is `day - 1`. A null
    offset yields a null date rather than a guess: the template validator
    only permits null days on a pre-activation task, and those are
    deliberately undated.
    """
    if day is None:
        return None
    return start_date + timedelta(days=day - 1)


def resolve_planned_dates(
    start_date: date | None,
    schedule_classification: str | None,
    planned_start_day: int | None,
    planned_end_day: int | None,
) -> tuple[date | None, date | None]:
    """Resolve one task's day offsets into its (start, end) calendar dates.

    Returns `(None, None)` for a pre-activation task or a project with no
    start date, both of which are outside the execution window this unit
    dates. Pure - takes plain values rather than a row - so activation can
    call it on a task it is still building, before that task is flushed.
    """
    if start_date is None or schedule_classification == PRE_ACTIVATION:
        return None, None
    return (
        planned_date_for_day(start_date, planned_start_day),
        planned_date_for_day(start_date, planned_end_day),
    )


class ProjectScheduleDateService:
    """Writes derived calendar dates onto already-instantiated execution tasks.

    Activation writes dates inline as it builds each `Task` (see
    `ProjectBaselineService.lock_and_instantiate`), so this service exists
    for the projects activated before U9 landed. It never commits: the
    caller owns the transaction, matching `lock_and_instantiate`.
    """

    def __init__(self, db: Session):
        self.db = db

    def generate_for_project(self, project: V2Project) -> int:
        """Set the derived dates on this project's execution tasks.

        Returns the number of tasks actually changed, which is 0 on a second
        run - the rule is deterministic, so a task already carrying the right
        dates is skipped and no UPDATE is emitted for it. That is what makes
        the backfill safe to re-run.
        """
        tasks = list(self.db.scalars(select(Task).where(Task.project_id == project.id)))
        changed = 0
        for task in tasks:
            start, end = resolve_planned_dates(
                project.start_date,
                task.schedule_classification,
                task.planned_start_day,
                task.planned_end_day,
            )
            if task.planned_start_date == start and task.planned_end_date == end:
                continue
            task.planned_start_date = start
            task.planned_end_date = end
            changed += 1
        if changed:
            self.db.flush()
        return changed

    def backfill(self, *, project_id: uuid.UUID | None = None) -> dict:
        """Date every activated project that predates this unit.

        Scoped to projects that already have execution tasks, since a project
        with no instantiated tasks has nothing to date and will be dated at
        its own activation. Idempotent by construction: it delegates to
        `generate_for_project`, which writes only differences, so a second
        run reports zero updates and creates no rows.
        """
        statement = select(V2Project).where(
            V2Project.id.in_(select(Task.project_id).distinct())
        ).order_by(V2Project.id)
        if project_id is not None:
            statement = statement.where(V2Project.id == project_id)

        projects = list(self.db.scalars(statement))
        tasks_updated = 0
        projects_updated = 0
        for project in projects:
            changed = self.generate_for_project(project)
            if changed:
                projects_updated += 1
                tasks_updated += changed
        return {
            "projects_scanned": len(projects),
            "projects_updated": projects_updated,
            "tasks_updated": tasks_updated,
        }
