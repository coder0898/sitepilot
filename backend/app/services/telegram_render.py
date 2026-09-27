"""Telegram-specific human-readable message rendering.

Separate from `message_templates.py` (WhatsApp's Meta-template
name/variable-order registry) by design (KTD8): Telegram has no
Meta-style approved-template system, so this module owns its own
plain-text rendering instead of reusing that registry's shape.

Covers vendor soft-removal (task.vendor_unassigned, project.vendor_removed).
Project onboarding and assignment messages (project.activated,
project.member_added, project.vendor_mapped, task.vendor_assigned) are
rendered by `telegram_assignment_render.py`, bilingual for vendors. Every
internal task-execution event is rendered by `telegram_task_render.py` and
every external-approval gate event by `telegram_gate_render.py` (both HTML,
recipient-specific). Every other event type
keeps the previous raw key:value dump via `_fallback`, unchanged - this
module does not attempt to cover every event type in the registry yet.

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

from sqlalchemy.orm import Session

from app.execution_models import Task
from app.project_models import V2Project
from app.services.telegram_assignment_render import ASSIGNMENT_RENDERERS, VENDOR_RENDERERS
from app.services.telegram_gate_render import GATE_RENDERERS
from app.services.telegram_message import TelegramMessage
from app.services.telegram_task_render import TASK_RENDERERS
from app.vendor_models import V2Vendor

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


def _vendor_name(db: Session, vendor_id: object) -> str:
    resolved = _uuid_or_none(vendor_id)
    vendor = db.get(V2Vendor, resolved) if resolved else None
    return vendor.name if vendor else "Unknown vendor"


def _footer(action_required: str | None) -> str:
    return f"\n\nReply:\n{action_required}" if action_required else "\n\nNo action required."


def _render_project_vendor_removed(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> str:
    lines = [
        "*Removed From Project*",
        f"Project: {_project_name(db, payload.get('project_id'))}",
        f"Vendor: {_vendor_name(db, payload.get('vendor_id'))}",
    ]
    if payload.get("reason"):
        lines.append(f"Reason: {payload['reason']}")
    return "\n".join(lines) + _footer(None)


_RENDERERS: dict[str, Callable[[Session, dict, uuid.UUID | None], str | TelegramMessage]] = {
    # Onboarding and assignments with Acknowledge buttons (T2).
    **ASSIGNMENT_RENDERERS,
    "project.vendor_removed": _render_project_vendor_removed,
    # Internal task execution (status, review decisions, support, blockers,
    # delays, schedule, daily prompts, follow-ups) - readable HTML.
    **TASK_RENDERERS,
    # Every external-approval gate event and gate command confirmation.
    **GATE_RENDERERS,
}


def _fallback(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> str:
    lines = [f"{key}: {value}" for key, value in payload.items()]
    return "\n".join(lines) if lines else "(no content)"


def render_telegram(
    db: Session,
    event_type: str,
    payload: dict,
    recipient_employee_id: uuid.UUID | None = None,
    recipient_vendor_contact_id: uuid.UUID | None = None,
) -> TelegramMessage:
    """Renders one outbox event into a `TelegramMessage` for the event types
    listed in `_RENDERERS`; every other event type keeps the previous raw
    key:value fallback unchanged. Plain-text renderers are wrapped with no
    parse mode, so their output is sent exactly as before. A vendor contact
    gets the bilingual `VENDOR_RENDERERS` version where one exists."""
    vendor_renderer = VENDOR_RENDERERS.get(event_type) if recipient_vendor_contact_id is not None else None
    if vendor_renderer is not None:
        return vendor_renderer(db, payload, recipient_vendor_contact_id)
    renderer = _RENDERERS.get(event_type, _fallback)
    rendered = renderer(db, payload, recipient_employee_id)
    return rendered if isinstance(rendered, TelegramMessage) else TelegramMessage(text=rendered)


def render_telegram_message(
    db: Session,
    event_type: str,
    payload: dict,
    recipient_employee_id: uuid.UUID | None = None,
    recipient_vendor_contact_id: uuid.UUID | None = None,
) -> str:
    """The final message text, including the typed-command fallback for any
    actions the message offers."""
    return render_telegram(
        db, event_type, payload, recipient_employee_id, recipient_vendor_contact_id,
    ).text_with_typed_fallback()
