"""Readable Telegram messages for internal task-execution events.

Telegram task plan U4. Replaces the raw key:value dump (and the old plain
renderers with typed-command hints) for every internal task event in scope.
Buttons arrive in later units (U5+); until then each message says what
happened and, where the recipient has something to do, what that is.

Recipient-aware: the same event reads differently for the people doing the
work (active support assignees and whoever submitted the work) than for the
reviewers and the rest of the team.

Read-only like `telegram_gate_render.py`: never mutates anything, holds no
business rules, and degrades to placeholders rather than raising. Every
dynamic value is HTML-escaped (sent with `parse_mode="HTML"`), and no UUID,
event name or payload key is ever shown.

Vendor events (`task.vendor_*`) are deliberately not here - vendor messages
stay exactly as they are.
"""

from __future__ import annotations

import html
import uuid
from datetime import date
from typing import Callable
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.execution_models import Task, TaskBlocker, TaskDelayEvent, TaskSupportAssignment
from app.models import EmployeeProfile, User
from app.project_models import V2Project, V2ProjectMembership
from app.services.task_lifecycle import latest_submitter_user_id
from app.services.telegram_message import TelegramMessage

_FYI = "For your information. No action required."
_REWORK_STEP = "Add new progress and submit the task for review again."

_STATUS_LABELS = {
    "planned": "Planned",
    "ready": "Ready",
    "in_progress": "In Progress",
    "submitted": "Submitted for Review",
    "verified": "Verified",
    "approval_pending": "Awaiting Approval",
    "rejected": "Rejected",
    "completed": "Completed",
    "cancelled": "Cancelled",
}


def _e(value: object) -> str:
    return html.escape(str(value))


def _uuid_or_none(value: object) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _label(value: object) -> str:
    return str(value).replace("_", " ").strip().capitalize() if value else "Not given"


def _date(value: object) -> str:
    if not value:
        return "Not set"
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d %b %Y").lstrip("0")
    except ValueError:
        return str(value)


def _user_name(db: Session, user_id: object, fallback: str = "Unknown user") -> str:
    resolved = _uuid_or_none(user_id)
    user = db.get(User, resolved) if resolved else None
    return user.name if user else fallback


def _employee_name(db: Session, employee_id: object, fallback: str = "Unknown employee") -> str:
    resolved = _uuid_or_none(employee_id)
    employee = db.get(EmployeeProfile, resolved) if resolved else None
    user = db.get(User, employee.user_id) if employee else None
    return user.name if user else fallback


class _Ctx:
    """The task, its project and who the recipient is to this task."""

    def __init__(self, db: Session, payload: dict, recipient_employee_id: uuid.UUID | None):
        self.db = db
        self.payload = payload
        self.task: Task | None = None
        resolved_task = _uuid_or_none(payload.get("task_id"))
        if resolved_task:
            self.task = db.get(Task, resolved_task)
        resolved_project = _uuid_or_none(payload.get("project_id")) or (self.task.project_id if self.task else None)
        self.project: V2Project | None = db.get(V2Project, resolved_project) if resolved_project else None
        self.recipient_employee_id = recipient_employee_id
        self.recipient_user_id = None
        if recipient_employee_id is not None:
            employee = db.get(EmployeeProfile, recipient_employee_id)
            self.recipient_user_id = employee.user_id if employee else None

    # ---- who the recipient is ------------------------------------------

    def project_roles(self) -> set[str]:
        if self.recipient_employee_id is None or self.project is None:
            return set()
        return set(self.db.scalars(
            select(V2ProjectMembership.project_role).where(
                V2ProjectMembership.project_id == self.project.id,
                V2ProjectMembership.employee_id == self.recipient_employee_id,
                V2ProjectMembership.ends_at.is_(None),
            )
        ))

    def is_pm(self) -> bool:
        return "project_manager" in self.project_roles()

    def is_supervisor(self) -> bool:
        return "site_supervisor" in self.project_roles()

    def is_assignee(self) -> bool:
        if self.task is None or self.recipient_employee_id is None:
            return False
        return self.db.scalar(
            select(TaskSupportAssignment.id).where(
                TaskSupportAssignment.task_id == self.task.id,
                TaskSupportAssignment.employee_id == self.recipient_employee_id,
                TaskSupportAssignment.status == "active",
            ).limit(1)
        ) is not None

    def submitter_user_id(self) -> uuid.UUID | None:
        return latest_submitter_user_id(self.db, self.task.id) if self.task else None

    def is_submitter(self) -> bool:
        submitter = self.submitter_user_id()
        return submitter is not None and submitter == self.recipient_user_id

    def is_executor(self) -> bool:
        """The people doing the work: an active support assignee, or whoever
        submitted it (e.g. a Supervisor who executed it themselves)."""
        return self.is_assignee() or self.is_submitter()

    # ---- message parts ----------------------------------------------------

    def rows(self, *extra: tuple[str, object]) -> list[tuple[str, object]]:
        task_label = f"{self.task.original_code} - {self.task.title}" if self.task else "Unknown task"
        return [("Project", self.project.name if self.project else "Unknown project"), ("Task", task_label), *extra]

    def link(self) -> tuple[str, str] | None:
        if self.project is None or not settings.frontend_url:
            return None
        query = urlencode({"tab": "execution", "project": self.project.code})
        return "Open in Web App", f"{settings.frontend_url.rstrip('/')}/?{query}"


def _message(ctx: _Ctx, title: str, rows: list[tuple[str, object]], paragraph: str | None = None) -> TelegramMessage:
    parts = [f"<b>{_e(title)}</b>"]
    if rows:
        parts.append("\n".join(f"{_e(label)}: {_e(value)}" for label, value in rows))
    if paragraph:
        parts.append(_e(paragraph))
    link = ctx.link()
    if link:
        parts.append(f'<a href="{_e(link[1])}">{_e(link[0])}</a>')
    return TelegramMessage(text="\n\n".join(parts), parse_mode="HTML")


def _is_approval_gate(ctx: _Ctx) -> bool:
    return ctx.task is not None and ctx.task.task_kind == "approval_gate"


def _is_class_a_work(ctx: _Ctx) -> bool:
    return ctx.task is not None and ctx.task.task_class == "class_a" and not _is_approval_gate(ctx)


# ---- status changes ----------------------------------------------------------


def _render_status_changed(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    target = payload.get("target_status")
    actor = _user_name(db, payload.get("actor_user_id"), fallback="") if payload.get("actor_user_id") else ""

    if target == "ready":
        rows = ctx.rows(*([("Marked ready by", actor)] if actor else []))
        step = "This task is ready to start." if ctx.is_executor() else _FYI
        return _message(ctx, "Task Ready", rows, step)

    if target == "in_progress":
        extra = [("Started by", actor)] if actor else []
        if ctx.task is not None and ctx.task.early_start_reason and payload.get("before_status") in ("planned", "ready"):
            extra.append(("Early start reason", ctx.task.early_start_reason))
        step = "Log your progress as you work." if ctx.is_executor() else _FYI
        return _message(ctx, "Task Started", ctx.rows(*extra), step)

    if target == "submitted":
        rows = ctx.rows(("Submitted by", actor or "Unknown user"))
        if _is_approval_gate(ctx):
            # Approval-gate tasks skip Supervisor verification entirely (KTD23):
            # nobody but the PM/Admin has anything to do, and the Supervisor is
            # never asked to "review" or "verify" it.
            if ctx.is_submitter():
                step = "Sent to the PM for approval. You will be told the outcome."
            elif ctx.is_pm():
                step = "Review and approve or reject it in the Web App."
            else:
                step = _FYI
            return _message(ctx, "Submitted - Awaiting PM Approval", rows, step)
        if ctx.is_submitter():
            return _message(ctx, "Submitted for Review", rows, "Your work was sent for review. You will be told the outcome.")
        if ctx.is_supervisor() or ctx.is_pm():
            return _message(ctx, "Task Submitted for Review", rows, "Review it in the Web App.")
        return _message(ctx, "Task Submitted for Review", rows, _FYI)

    if target == "completed":
        if ctx.task is not None and ctx.task.task_kind == "milestone":
            return _message(ctx, "Milestone Completed", ctx.rows(), "All of its predecessor tasks are complete.")
        return _message(ctx, "Task Completed", ctx.rows(), _FYI)

    if target == "cancelled":
        rows = ctx.rows(*([("Cancelled by", actor)] if actor else []), ("Reason", payload.get("reason") or "Not given"))
        return _message(ctx, "Task Cancelled", rows, _FYI)

    before = _STATUS_LABELS.get(payload.get("before_status"), _label(payload.get("before_status")))
    after = _STATUS_LABELS.get(target, _label(target))
    return _message(ctx, "Task Status Updated", ctx.rows(("Status", f"{before} -> {after}")), _FYI)


# ---- review decisions -----------------------------------------------------------


def _render_rework(ctx: _Ctx, reviewer_label: str, reviewer: str, reason: object) -> TelegramMessage:
    rows = ctx.rows((reviewer_label, reviewer), ("Reason", reason or "Not given"))
    step = _REWORK_STEP if ctx.is_executor() else "Sent back for rework. " + _FYI
    return _message(ctx, "Rework Required", rows, step)


def _render_verification_recorded(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    reviewer = _user_name(db, payload.get("verified_by"))
    if payload.get("decision") == "rejected":
        return _render_rework(ctx, "Rejected by", reviewer, payload.get("remarks"))
    rows = ctx.rows(("Verified by", reviewer))
    if _is_class_a_work(ctx):
        if ctx.is_pm():
            step = "Review and approve or reject it in the Web App."
        elif ctx.is_executor():
            step = "Your work passed verification and is now waiting for PM approval."
        else:
            step = _FYI
        return _message(ctx, "Verified - Awaiting PM Approval", rows, step)
    step = "Your work was verified. Nothing more to do on this task." if ctx.is_executor() else _FYI
    return _message(ctx, "Task Completed", rows, step)


def _render_approval_recorded(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    reviewer = _user_name(db, payload.get("decided_by"))
    if payload.get("decision") == "rejected":
        return _render_rework(ctx, "Rejected by", reviewer, payload.get("remarks"))
    step = "Your work was approved. Nothing more to do on this task." if ctx.is_executor() else _FYI
    return _message(ctx, "Task Approved and Completed", ctx.rows(("Approved by", reviewer)), step)


# ---- support assignment ------------------------------------------------------


def _render_support_assigned(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    responsibility = [("Responsibility", payload["responsibility"])] if payload.get("responsibility") else []
    planned = [("Planned start", _date(ctx.task.planned_start_date))] if ctx.task is not None else []
    if recipient_employee_id is not None and str(recipient_employee_id) == str(payload.get("employee_id")):
        return _message(
            ctx, "Task Assigned to You", ctx.rows(*responsibility, *planned),
            "You are responsible for doing this task and logging its progress.",
        )
    rows = ctx.rows(("Employee", _employee_name(db, payload.get("employee_id"))), *responsibility)
    return _message(ctx, "Employee Assigned to Task", rows, _FYI)


def _render_support_ended(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    replacement = payload.get("replacement_employee_id")
    replaced = [("Replaced by", _employee_name(db, replacement))] if replacement else []
    reason = [("Reason", _label(payload.get("reason_code")))] if payload.get("reason_code") else []
    if recipient_employee_id is not None and str(recipient_employee_id) == str(payload.get("previous_employee_id")):
        return _message(ctx, "No Longer Assigned to You", ctx.rows(*replaced, *reason), "You are no longer responsible for this task.")
    if replacement and recipient_employee_id is not None and str(recipient_employee_id) == str(replacement):
        return _message(
            ctx, "Task Assigned to You", ctx.rows(("Previously", _employee_name(db, payload.get("previous_employee_id")))),
            "You are responsible for doing this task and logging its progress.",
        )
    rows = ctx.rows(("Employee", _employee_name(db, payload.get("previous_employee_id"))), *replaced, *reason)
    return _message(ctx, "Task Assignment Ended", rows, _FYI)


# ---- blockers, delays, schedule ---------------------------------------------


def _render_blocker_created(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    rows = ctx.rows(("Type", payload.get("type") or "Not given"), ("Description", payload.get("description") or "Not given"))
    return _message(ctx, "Blocker Reported", rows, _FYI)


def _render_blocker_resolved(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    blocker_id = _uuid_or_none(payload.get("blocker_id"))
    blocker = db.get(TaskBlocker, blocker_id) if blocker_id else None
    extra = [("Blocker", f"{blocker.type}: {blocker.description}")] if blocker else []
    return _message(ctx, "Blocker Resolved", ctx.rows(*extra, ("Resolved by", _user_name(db, payload.get("resolved_by")))), _FYI)


def _render_delay_recorded(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    delay_id = _uuid_or_none(payload.get("delay_id"))
    delay = db.get(TaskDelayEvent, delay_id) if delay_id else None
    days = payload.get("impact_days")
    rows = ctx.rows(
        ("Responsibility", _label(payload.get("responsibility_type"))),
        ("Impact", f"{days} day{'s' if days != 1 else ''}" if days is not None else "Not given"),
        *([("Reason", delay.reason)] if delay else []),
    )
    return _message(ctx, "Delay Recorded", rows, _FYI)


def _render_rescheduled(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    rows = ctx.rows(
        ("Start", f"{_date(payload.get('before_planned_start_date'))} -> {_date(payload.get('planned_start_date'))}"),
        ("Finish", f"{_date(payload.get('before_planned_end_date'))} -> {_date(payload.get('planned_end_date'))}"),
        ("Reason", payload.get("reason") or "Not given"),
    )
    return _message(ctx, "Task Rescheduled", rows, _FYI)


# ---- daily prompts and follow-ups ----------------------------------------------


def _render_daily_check(title: str, executor_step: str) -> Callable[[Session, dict, uuid.UUID | None], TelegramMessage]:
    def _render(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
        ctx = _Ctx(db, payload, recipient_employee_id)
        status = _STATUS_LABELS.get(payload.get("lifecycle_status"), _label(payload.get("lifecycle_status")))
        rows = ctx.rows(("Status", status), ("Planned start", _date(payload.get("planned_start_date"))))
        return _message(ctx, title, rows, executor_step if ctx.is_executor() else _FYI)

    return _render


def _render_no_update(title: str) -> Callable[[Session, dict, uuid.UUID | None], TelegramMessage]:
    def _render(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
        ctx = _Ctx(db, payload, recipient_employee_id)
        hours = payload.get("update_sla_hours")
        status = _STATUS_LABELS.get(payload.get("lifecycle_status"), _label(payload.get("lifecycle_status")))
        rows = ctx.rows(("Status", status), *([("Expected update every", f"{hours} hours")] if hours else []))
        step = "Please log a progress update." if ctx.is_executor() else "No progress update has been logged in time. " + _FYI
        return _message(ctx, title, rows, step)

    return _render


TASK_RENDERERS: dict[str, Callable[[Session, dict, uuid.UUID | None], TelegramMessage]] = {
    "task.status_changed": _render_status_changed,
    "task.verification_recorded": _render_verification_recorded,
    "task.approval_recorded": _render_approval_recorded,
    "task.support_assigned": _render_support_assigned,
    "task.support_ended": _render_support_ended,
    "task.blocker_created": _render_blocker_created,
    "task.blocker_resolved": _render_blocker_resolved,
    "task.delay_recorded": _render_delay_recorded,
    "task.rescheduled": _render_rescheduled,
    "task.readiness_check": _render_daily_check("Readiness Check", "Is the site ready for this task? Mark it ready when it is."),
    "task.start_check": _render_daily_check("Start Check", "This task is due to start. Start it when work begins."),
    "task.midday_check": _render_daily_check("Midday Check", "Please log today's progress so far."),
    "task.eod_check": _render_daily_check("End-of-Day Check", "Please log what was completed today."),
    "task.eod_followup_required": _render_no_update("Progress Update Overdue"),
    "task.escalated_to_admin": _render_no_update("Escalated: Progress Update Overdue"),
}
