"""Readable Telegram messages for project onboarding and assignments (T2).

Internal people read English; vendor contacts read English with Hindi under
each line. Every message that hands someone a new responsibility offers an
Acknowledge button (`a1:<code>:<row id>`, handled by
`telegram_ack_callback.py`) while it is still unacknowledged:

- project.activated / project.member_added -> the member's project
  membership ([Acknowledge Assignment]);
- project.activated / project.vendor_mapped -> the vendor's project mapping
  ([Acknowledge / स्वीकार करें]);
- task.vendor_assigned -> the vendor task assignment, the same
  acknowledgement the typed `ACCEPT <ref>` records.

`task.support_assigned` (internal task assignment) lives with the other task
messages in `telegram_task_render.py`.

Read-only like the other renderers: never mutates, holds no business rule,
degrades to placeholders rather than raising, HTML-escapes every value and
never shows a UUID.
"""

from __future__ import annotations

import html
import uuid
from datetime import date
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import Task
from app.models import EmployeeProfile, User
from app.project_models import V2Project, V2ProjectMembership
from app.services.telegram_message import TelegramAction, TelegramMessage, ack_callback
from app.vendor_models import ProjectVendor, TaskVendorAssignment, V2Vendor, V2VendorContact

ACK_MEMBERSHIP = "pm"
ACK_PROJECT_VENDOR = "pv"
ACK_SUPPORT_ASSIGNMENT = "sa"
ACK_VENDOR_TASK = "va"

ACK_LABEL = "Acknowledge"
ACK_ASSIGNMENT_LABEL = "Acknowledge Assignment"
VENDOR_ACK_LABEL = "Acknowledge / स्वीकार करें"

_ROLE_LABELS = {
    "project_manager": "Project Manager",
    "site_supervisor": "Site Supervisor",
    "internal_employee": "Internal Employee",
}
_FYI = "For your information. No action required."
_VENDOR_FYI = "For your information. No action required.\nकेवल आपकी जानकारी के लिए। कोई कार्रवाई आवश्यक नहीं है।"


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


def _date(value: date | None) -> str:
    return value.strftime("%d %b %Y").lstrip("0") if value else "Not set"


def _message(title: str, rows: list[tuple[str, object]], paragraph: str, actions=()) -> TelegramMessage:
    parts = [f"<b>{_e(title)}</b>"]
    if rows:
        parts.append("\n".join(f"{_e(label)}: {_e(value)}" for label, value in rows))
    parts.append(_e(paragraph))
    return TelegramMessage(text="\n\n".join(parts), parse_mode="HTML", actions=tuple(actions))


def _project_rows(project: V2Project | None, payload: dict, *, hindi: bool = False) -> list[tuple[str, object]]:
    name = project.name if project else payload.get("project_name") or "Unknown project"
    rows = [("Project / प्रोजेक्ट" if hindi else "Project", name)]
    if project is not None and project.site_address:
        rows.append(("Site / साइट" if hindi else "Site", project.site_address))
    if project is not None and project.start_date:
        rows.append(("Start date / शुरू होने की तारीख" if hindi else "Start date", _date(project.start_date)))
    return rows


# ---- internal people -------------------------------------------------------


def _memberships(db: Session, project_id: object, employee_id: object) -> list[V2ProjectMembership]:
    resolved_project, resolved_employee = _uuid_or_none(project_id), _uuid_or_none(employee_id)
    if not resolved_project or not resolved_employee:
        return []
    return list(db.scalars(
        select(V2ProjectMembership).where(
            V2ProjectMembership.project_id == resolved_project,
            V2ProjectMembership.employee_id == resolved_employee,
            V2ProjectMembership.ends_at.is_(None),
        ).order_by(V2ProjectMembership.created_at)
    ))


def _welcome(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None, title: str) -> TelegramMessage:
    project = _get(db, V2Project, payload.get("project_id"))
    memberships = _memberships(db, payload.get("project_id"), recipient_employee_id)
    roles = ", ".join(_ROLE_LABELS.get(m.project_role, m.project_role) for m in memberships) or "Team Member"
    rows = _project_rows(project, payload) + [("Your role", roles), ("Status", "Active")]
    pending = next((m for m in memberships if m.acknowledged_at is None), None)
    if pending is None:
        return _message(title, rows, "You are on this project team." if memberships else _FYI)
    return _message(
        title, rows, "You have been assigned to this project. Please acknowledge that you received this assignment.",
        ((TelegramAction(ACK_ASSIGNMENT_LABEL, "", ack_callback(ACK_MEMBERSHIP, pending.id)),),),
    )


def _render_project_activated(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    project = _get(db, V2Project, payload.get("project_id"))
    name = project.name if project else payload.get("project_name") or "Unknown project"
    return _welcome(db, payload, recipient_employee_id, f"Welcome to {name}")


def _render_project_member_added(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    if recipient_employee_id is not None and str(recipient_employee_id) == str(payload.get("employee_id")):
        return _welcome(db, payload, recipient_employee_id, "Added to Project Team")
    project = _get(db, V2Project, payload.get("project_id"))
    employee = _get(db, EmployeeProfile, payload.get("employee_id"))
    user = db.get(User, employee.user_id) if employee else None
    role = _ROLE_LABELS.get(payload.get("project_role"), payload.get("project_role") or "Team Member")
    rows = _project_rows(project, payload)[:1] + [("Member", user.name if user else "Unknown member"), ("Role", role)]
    return _message("New Team Member", rows, _FYI)


def _render_project_vendor_mapped(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    project = _get(db, V2Project, payload.get("project_id"))
    vendor = _get(db, V2Vendor, payload.get("vendor_id"))
    rows = _project_rows(project, payload)[:1] + [("Vendor", vendor.name if vendor else "Unknown vendor")]
    return _message("Vendor Added to Project", rows, _FYI)


def _render_task_vendor_assigned(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    project = _get(db, V2Project, payload.get("project_id"))
    task = _get(db, Task, payload.get("task_id"))
    vendor = _get(db, V2Vendor, payload.get("vendor_id"))
    rows = _project_rows(project, payload)[:1] + [
        ("Task", f"{task.original_code} - {task.title}" if task else "Unknown task"),
        ("Vendor", vendor.name if vendor else "Unknown vendor"),
    ]
    return _message("Vendor Assigned to Task", rows, "The vendor has been asked to acknowledge. " + _FYI)


# ---- vendor contacts (English + Hindi) ------------------------------------


def _contact(db: Session, vendor_contact_id: uuid.UUID) -> V2VendorContact | None:
    return db.get(V2VendorContact, vendor_contact_id)


def _vendor_project_assignment(db: Session, payload: dict, contact: V2VendorContact | None) -> TelegramMessage:
    project = _get(db, V2Project, payload.get("project_id"))
    vendor = db.get(V2Vendor, contact.vendor_id) if contact else None
    rows = _project_rows(project, payload, hindi=True) + [("Vendor / वेंडर", vendor.name if vendor else "Unknown vendor")]
    mapping = None
    if contact is not None and project is not None:
        mapping = db.scalar(
            select(ProjectVendor).where(
                ProjectVendor.project_id == project.id,
                ProjectVendor.vendor_id == contact.vendor_id,
                ProjectVendor.ends_at.is_(None),
            ).limit(1)
        )
    title = "Project Assignment / प्रोजेक्ट असाइनमेंट"
    if mapping is None or mapping.acknowledged_at is not None:
        return _message(title, rows, "You are assigned to this project.\nआप इस प्रोजेक्ट पर नियुक्त हैं।")
    return _message(
        title, rows,
        "Your company has been assigned to this project. Please acknowledge that you received this assignment.\n"
        "आपकी कंपनी को इस प्रोजेक्ट पर नियुक्त किया गया है। कृपया पुष्टि करें कि आपको यह असाइनमेंट मिल गया है।",
        ((TelegramAction(VENDOR_ACK_LABEL, "", ack_callback(ACK_PROJECT_VENDOR, mapping.id)),),),
    )


def _vendor_project_activated(db: Session, payload: dict, vendor_contact_id: uuid.UUID) -> TelegramMessage:
    return _vendor_project_assignment(db, payload, _contact(db, vendor_contact_id))


def _vendor_project_vendor_mapped(db: Session, payload: dict, vendor_contact_id: uuid.UUID) -> TelegramMessage:
    contact = _contact(db, vendor_contact_id)
    if contact is not None and str(contact.vendor_id) == str(payload.get("vendor_id")):
        return _vendor_project_assignment(db, payload, contact)
    project = _get(db, V2Project, payload.get("project_id"))
    vendor = _get(db, V2Vendor, payload.get("vendor_id"))
    rows = _project_rows(project, payload, hindi=True)[:1] + [("Vendor / वेंडर", vendor.name if vendor else "Unknown vendor")]
    return _message("Vendor Added to Project / प्रोजेक्ट में नया वेंडर जोड़ा गया", rows, _VENDOR_FYI)


def _vendor_task_assigned(db: Session, payload: dict, vendor_contact_id: uuid.UUID) -> TelegramMessage:
    project = _get(db, V2Project, payload.get("project_id"))
    task = _get(db, Task, payload.get("task_id"))
    assignment = _get(db, TaskVendorAssignment, payload.get("assignment_id"))
    rows = _project_rows(project, payload, hindi=True)[:1] + [
        ("Task / कार्य", f"{task.original_code} - {task.title}" if task else "Unknown task"),
        ("Start date / शुरू होने की तारीख", _date(task.planned_start_date) if task else "Not set"),
    ]
    title = "New Task Assigned / नया कार्य सौंपा गया"
    if assignment is None or assignment.ends_at is not None or assignment.status != "pending_ack":
        return _message(title, rows, _VENDOR_FYI)
    ref = assignment.id.hex[:8]
    return _message(
        title, rows,
        "Please acknowledge that you received this task.\nकृपया पुष्टि करें कि आपको यह कार्य मिल गया है।",
        (
            (TelegramAction(VENDOR_ACK_LABEL, f"ACCEPT {ref}", ack_callback(ACK_VENDOR_TASK, assignment.id)),),
            (TelegramAction("Decline / मना करें", f"DECLINE {ref}"),),
        ),
    )


ASSIGNMENT_RENDERERS: dict[str, Callable[[Session, dict, uuid.UUID | None], TelegramMessage]] = {
    "project.activated": _render_project_activated,
    "project.member_added": _render_project_member_added,
    "project.vendor_mapped": _render_project_vendor_mapped,
    "task.vendor_assigned": _render_task_vendor_assigned,
}

# Used instead of the renderers above when the recipient is a vendor contact.
VENDOR_RENDERERS: dict[str, Callable[[Session, dict, uuid.UUID], TelegramMessage]] = {
    "project.activated": _vendor_project_activated,
    "project.vendor_mapped": _vendor_project_vendor_mapped,
    "task.vendor_assigned": _vendor_task_assigned,
}
