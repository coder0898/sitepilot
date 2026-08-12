"""45-day POC U4: the single Python owner of the relative-day-to-date rule.

The 45-day template describes every task as a pair of day offsets into the
project. Three places need to turn one of those offsets into a real date -
the project's handover date, a task's target finish, and a task's planned
start - and if any two of them disagree by a day the delay measurement
built on top is quietly wrong. So they all come through here.

THE CONVENTION: day 1 is the project start date itself, inclusive. A task
planned to end on day 8 of a project starting 1 Aug ends on 8 Aug, not
9 Aug; a 45-day template starting 11 Aug hands over on 24 Sep. This
matches `plannedDate` in
frontend/src/features/projects/components/PhaseOverviewDrawer.jsx, which
is what a user already sees, so the server has to agree with it rather
than the other way round.

WHY TARGET FINISH IS NOT MIDNIGHT: `due_at` is compared with
`_overdue_tasks`' `due_at < now` in
backend/app/services/project_visibility.py. Storing midnight *of* the
target finish day would mark a task overdue at 00:00 on the very day it is
due - a full day early, on a dashboard tile this unit is the first to
populate. Target finish is therefore stored as the exclusive end of that
day: midnight at the start of the following day. A task is due "by the end
of day 8" and turns overdue as day 9 begins.

Planned start has the opposite need and keeps midnight: work started at
any moment during its planned start day is not early (U9), so the
comparison point is the start of the day.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone


def scheduled_date(start_date: date, day_offset: int | None) -> date | None:
    """The calendar date of a relative day offset, day 1 being `start_date`.

    Returns None for a null offset. That is the pre-activation case (R53):
    seven tasks per 45-day project carry no planned days, and they are
    instantiated like any other included task rather than being an error.
    """
    if day_offset is None:
        return None
    return start_date + timedelta(days=day_offset - 1)


def planned_start_at(start_date: date, planned_start_day: int | None) -> datetime | None:
    """Midnight UTC at the start of the planned start day."""
    scheduled = scheduled_date(start_date, planned_start_day)
    if scheduled is None:
        return None
    return datetime.combine(scheduled, time.min, tzinfo=timezone.utc)


def required_by_at(start_date: date, required_by_type: str | None, required_by_value: str | None) -> datetime | None:
    """R10: turn a gate's authored required-by into a real timestamp.

    Template gates express this either as a relative project day
    (`project_day`) or an explicit ISO date (`date`), both stored as text.
    Like a task's target finish this resolves to the exclusive end of the
    named day - an approval due "by day 5" is not late until day 6 starts.

    Returns None rather than raising when the template gives no required-by
    or gives one this cannot parse. Gate content is authored outside this
    codebase, and a malformed value in one of 32 gates must not take an
    entire project activation down with it.
    """
    if not required_by_type or required_by_value is None:
        return None
    raw = required_by_value.strip()
    if not raw:
        return None
    if required_by_type == "project_day":
        try:
            return target_finish_at(start_date, int(raw))
        except ValueError:
            return None
    if required_by_type == "date":
        try:
            explicit = date.fromisoformat(raw)
        except ValueError:
            return None
        return datetime.combine(explicit + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return None


def target_finish_at(start_date: date, planned_end_day: int | None) -> datetime | None:
    """The exclusive end of the planned end day - midnight UTC beginning the
    following day. See the module docstring for why this is not midnight of
    the day itself."""
    scheduled = scheduled_date(start_date, planned_end_day)
    if scheduled is None:
        return None
    return datetime.combine(scheduled + timedelta(days=1), time.min, tzinfo=timezone.utc)
