"""Telegram-specific human-readable message rendering.

Separate from `message_templates.py` (WhatsApp's Meta-template
name/variable-order registry) by design (KTD8): Telegram has no
Meta-style approved-template system, so this module owns its own
plain-text rendering instead of reusing that registry's shape.

Covers only the event types needed for the Phase 2 manual test plan
(docs/2026-09-19-001-telegram-phase1-status-phase2-test-plan.md):
project.activated, project.member_added, task.readiness_check/
task.start_check, task.status_changed, task.vendor_assigned, and the gate
assignment/acknowledgement events. Every other event type keeps the
previous raw key:value dump via `_fallback`, unchanged - this module does
not attempt to cover every event type in the registry yet.

Architecture rule this module exists to satisfy: business event/data ->
shared backend -> Telegram renderer -> Telegram message. It only READS
existing project/task/vendor/user records to make a message readable; it
never mutates anything and holds no business rules of its own - a missing
or malformed id degrades to a placeholder string ("Unknown project", "?"),
it never raises.
"""

from __future__ import annotations

import uuid
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import ProjectExternalApproval, Task
from app.models import EmployeeProfile, User
from app.project_models import V2Project, V2ProjectExternalGate, V2ProjectMembership
from app.vendor_models import V2Vendor

_ROLE_LABELS = {
    "project_manager": "Project Manager",
    "site_supervisor": "Site Supervisor",
    "internal_employee": "Internal Employee",
}


def _uuid_or_none(value: object) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _project(db: Session, project_id: object) -> V2Project | None:
    resolved = _uuid_or_none(project_id)
    return db.get(V2Project, resolved) if resolved else None


def _project_name(db: Session, project_id: object, fallback: str = "Unknown project") -> str:
    project = _project(db, project_id)
    return project.name if project else fallback


def _task(db: Session, task_id: object) -> Task | None:
    resolved = _uuid_or_none(task_id)
    return db.get(Task, resolved) if resolved else None


def _task_label(db: Session, task_id: object) -> str:
    task = _task(db, task_id)
    return f"{task.original_code} - {task.title}" if task else "Unknown task"


def _task_code(db: Session, task_id: object) -> str:
    task = _task(db, task_id)
    return task.original_code if task else "?"


def _vendor_name(db: Session, vendor_id: object) -> str:
    resolved = _uuid_or_none(vendor_id)
    vendor = db.get(V2Vendor, resolved) if resolved else None
    return vendor.name if vendor else "Unknown vendor"


def _gate_name(db: Session, approval_id: object) -> str:
    resolved = _uuid_or_none(approval_id)
    approval = db.get(ProjectExternalApproval, resolved) if resolved else None
    if not approval:
        return "Unknown gate"
    gate = db.get(V2ProjectExternalGate, approval.project_gate_id)
    return gate.approval_name if gate else "Unknown gate"


def _short_ref(value: object) -> str:
    return str(value).replace("-", "")[:8] if value else "?"


def _recipient_role_label(db: Session, project_id: object, recipient_employee_id: uuid.UUID | None) -> str:
    resolved_project_id = _uuid_or_none(project_id)
    if not resolved_project_id or not recipient_employee_id:
        return "Team Member"
    project_role = db.execute(
        select(V2ProjectMembership.project_role)
        .where(
            V2ProjectMembership.project_id == resolved_project_id,
            V2ProjectMembership.employee_id == recipient_employee_id,
            V2ProjectMembership.ends_at.is_(None),
        )
        .limit(1)
    ).scalar_one_or_none()
    return _ROLE_LABELS.get(project_role, project_role) if project_role else "Team Member"


def _footer(action_required: str | None) -> str:
    return f"\n\nReply:\n{action_required}" if action_required else "\n\nNo action required."


def _render_project_activated(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> str:
    project = _project(db, payload.get("project_id"))
    lines = [
        "*Project Activated*",
        f"Project: {project.name if project else payload.get('project_name', 'Unknown project')}",
        f"Your Role: {_recipient_role_label(db, payload.get('project_id'), recipient_employee_id)}",
    ]
    if project and project.start_date:
        lines.append(f"Start Date: {project.start_date.isoformat()}")
    lines.append("Status: Active")
    return "\n".join(lines) + _footer(None)


def _render_project_member_added(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> str:
    role = _ROLE_LABELS.get(payload.get("project_role"), payload.get("project_role") or "Team Member")
    lines = [
        "*Added to Project Team*",
        f"Project: {_project_name(db, payload.get('project_id'))}",
        f"Role: {role}",
    ]
    return "\n".join(lines) + _footer(None)


def _render_task_check(title: str) -> Callable[[Session, dict, uuid.UUID | None], str]:
    def _render(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> str:
        task_id = payload.get("task_id")
        lines = [
            f"*{title}*",
            f"Project: {_project_name(db, payload.get('project_id'))}",
            f"Task: {_task_label(db, task_id)}",
            f"Planned Start: {payload.get('planned_start_date') or 'Not set'}",
        ]
        return "\n".join(lines) + _footer(f"`STATUS {_task_code(db, task_id)} in_progress`")

    return _render


def _render_task_status_changed(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> str:
    lines = [
        "*Task Status Updated*",
        f"Project: {_project_name(db, payload.get('project_id'))}",
        f"Task: {_task_label(db, payload.get('task_id'))}",
        f"Status: {payload.get('before_status', '?')} -> {payload.get('target_status', '?')}",
    ]
    return "\n".join(lines) + _footer(None)


def _render_task_vendor_assigned(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> str:
    ref = _short_ref(payload.get("assignment_id"))
    lines = [
        "*Task Action Required*",
        f"Project: {_project_name(db, payload.get('project_id'))}",
        f"Task: {_task_label(db, payload.get('task_id'))}",
        f"Vendor: {_vendor_name(db, payload.get('vendor_id'))}",
    ]
    return "\n".join(lines) + _footer(f"`ACCEPT {ref}` or `DECLINE {ref}`")


def _render_gate_assigned(title: str) -> Callable[[Session, dict, uuid.UUID | None], str]:
    def _render(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> str:
        ref = _short_ref(payload.get("approval_id"))
        lines = [
            f"*{title}*",
            f"Project: {payload.get('project_name') or _project_name(db, payload.get('project_id'))}",
            f"Gate: {payload.get('gate_name') or _gate_name(db, payload.get('approval_id'))}",
            f"Due: {payload.get('due_date') or 'Not set'}",
        ]
        return "\n".join(lines) + _footer(f"`GATEACCEPT {ref}` or `GATEDECLINE {ref}`")

    return _render


def _render_gate_response(title: str) -> Callable[[Session, dict, uuid.UUID | None], str]:
    def _render(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> str:
        lines = [
            f"*{title}*",
            f"Project: {_project_name(db, payload.get('project_id'))}",
            f"Gate: {_gate_name(db, payload.get('approval_id'))}",
        ]
        if payload.get("note"):
            lines.append(f"Note: {payload['note']}")
        return "\n".join(lines) + _footer(None)

    return _render


_RENDERERS: dict[str, Callable[[Session, dict, uuid.UUID | None], str]] = {
    "project.activated": _render_project_activated,
    "project.member_added": _render_project_member_added,
    "task.readiness_check": _render_task_check("Task Readiness Check"),
    "task.start_check": _render_task_check("Task Start Check"),
    "task.status_changed": _render_task_status_changed,
    "task.vendor_assigned": _render_task_vendor_assigned,
    "project_external_approval.assigned": _render_gate_assigned("Gate Assignment"),
    "project_external_approval.reassigned": _render_gate_assigned("Gate Reassignment"),
    "project_external_approval.accepted": _render_gate_response("Gate Acknowledged"),
    "project_external_approval.declined": _render_gate_response("Gate Declined"),
}


def _fallback(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> str:
    lines = [f"{key}: {value}" for key, value in payload.items()]
    return "\n".join(lines) if lines else "(no content)"


def render_telegram_message(
    db: Session,
    event_type: str,
    payload: dict,
    recipient_employee_id: uuid.UUID | None = None,
) -> str:
    """Renders one outbox event into human-readable Telegram text for the
    event types listed in `_RENDERERS`; every other event type keeps the
    previous raw key:value fallback unchanged."""
    renderer = _RENDERERS.get(event_type, _fallback)
    return renderer(db, payload, recipient_employee_id)
