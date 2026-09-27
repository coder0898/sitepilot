"""Readable Telegram messages for project-level events that used to arrive
as a raw key:value dump: project role changes and the weekly summary.

Read-only like the other renderers: never mutates, holds no business rule,
degrades to placeholders rather than raising, HTML-escapes every value and
never shows a UUID or payload key.
"""

from __future__ import annotations

import html
import uuid
from datetime import datetime
from typing import Callable
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from app.config import settings
from app.models import EmployeeProfile, User
from app.project_models import V2Project, V2ProjectMembership
from app.report_models import ReportSnapshot
from app.services.telegram_message import TelegramMessage

_ROLE_LABELS = {"project_manager": "Project Manager", "site_supervisor": "Site Supervisor"}


def _e(value: object) -> str:
    return html.escape(str(value), quote=False)


def _uuid_or_none(value: object) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _get(db: Session, model, value: object):
    resolved = _uuid_or_none(value)
    return db.get(model, resolved) if resolved else None


def _employee_name(db: Session, employee_id: object) -> str | None:
    employee = _get(db, EmployeeProfile, employee_id)
    user = db.get(User, employee.user_id) if employee else None
    return user.name if user else None


def _label(value: object) -> str:
    return str(value or "").replace("_", " ").strip().capitalize() or "Not given"


def _message(project: V2Project | None, title: str, rows: list[tuple[str, object]], paragraph: str) -> TelegramMessage:
    all_rows = [("Project", project.name if project else "Unknown project"), *rows]
    parts = [
        f"<b>{_e(title)}</b>",
        "\n".join(f"{_e(label)}: {_e(value)}" for label, value in all_rows if value not in (None, "")),
        _e(paragraph),
    ]
    if project is not None and settings.frontend_url:
        url = f"{settings.frontend_url.rstrip('/')}/?{urlencode({'tab': 'execution', 'project': project.code})}"
        parts.append(f'<a href="{_e(url)}">Open in Web App</a>')
    return TelegramMessage(text="\n\n".join(parts), parse_mode="HTML")


# ---- project role changes ------------------------------------------------------


def _change_line(db: Session, payload: dict) -> str:
    if payload.get("change_type") == "vacate":
        return "Leave the role empty"
    name = _employee_name(db, payload.get("replacement_employee_id"))
    return f"Replace with {name}" if name else "Replace the current holder"


def _render_role_change_requested(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    project = _get(db, V2Project, payload.get("project_id"))
    role = _ROLE_LABELS.get(payload.get("role_type"), _label(payload.get("role_type")))
    return _message(
        project, "Role Change Requested",
        [("Role", role), ("Change", _change_line(db, payload)), ("Reason", _label(payload.get("reason_code")))],
        "An Admin will review this request in the Web App. For your information.",
    )


def _render_role_change_approved(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    project = _get(db, V2Project, payload.get("project_id"))
    role = _ROLE_LABELS.get(payload.get("role_type"), _label(payload.get("role_type")))
    membership = _get(db, V2ProjectMembership, payload.get("membership_id"))
    holder = _employee_name(db, membership.employee_id) if membership else None
    now_held = "Nobody - the role is now empty" if payload.get("change_type") == "vacate" else holder or "Updated"
    return _message(
        project, "Role Change Approved",
        [("Role", role), ("Now held by", now_held)],
        "The project team has been updated.",
    )


def _render_role_change_rejected(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    project = _get(db, V2Project, payload.get("project_id"))
    role = _ROLE_LABELS.get(payload.get("role_type"), _label(payload.get("role_type")))
    return _message(
        project, "Role Change Rejected",
        [("Role", role), ("Reason", payload.get("reason") or "Not given")],
        "The project team stays as it is.",
    )


# ---- weekly summary ----------------------------------------------------------------


def _day(value: object) -> str | None:
    try:
        return datetime.fromisoformat(str(value)).strftime("%d %b %Y").lstrip("0")
    except (TypeError, ValueError):
        return None


def _render_weekly_summary(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    project = _get(db, V2Project, payload.get("project_id"))
    snapshot = _get(db, ReportSnapshot, payload.get("report_snapshot_id"))
    data = (snapshot.payload_json or {}) if snapshot else {}
    summary = data.get("summary") or {}

    def count(key: str) -> int:
        value = summary.get(key)
        return len(value) if isinstance(value, list) else int(value or 0)

    week = None
    if snapshot is not None:
        start, end = _day(snapshot.period_start.isoformat()), _day(snapshot.period_end.isoformat())
        week = f"{start} - {end}" if start and end else None
    total = count("total_count")
    rows = [
        ("Week", week),
        ("Tasks", f"{count('completed_count')} completed, {count('active_count')} in progress, "
                  f"{count('planned_count')} not started (of {total})" if summary else "Not available"),
        ("Overdue", count("overdue_tasks")),
        ("Blocked", count("blocked_tasks")),
        ("Delayed", count("delayed_tasks")),
        ("Waiting for verification", count("pending_verifications")),
        ("Waiting for PM approval", count("pending_approvals")),
        ("Approval gates at risk", count("approval_gates_at_risk")),
    ]
    attention = count("overdue_tasks") + count("blocked_tasks") + count("approval_gates_at_risk")
    step = (
        "Some items need attention - open the full report in the Web App."
        if attention else "No overdue or blocked work this week. The full report is in the Web App."
    )
    return _message(project, "Weekly Project Summary", rows, step)


PROJECT_RENDERERS: dict[str, Callable[[Session, dict, uuid.UUID | None], TelegramMessage]] = {
    "project.role_change_requested": _render_role_change_requested,
    "project.role_change_approved": _render_role_change_approved,
    "project.role_change_rejected": _render_role_change_rejected,
    "report.weekly_summary_generated": _render_weekly_summary,
}
