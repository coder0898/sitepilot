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

Vendors also get a plain-words day-before reminder (task.prestart_warning)
and a notice when they are removed from a task or a project.

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


# ---- vendor contacts (English, then Hindi) ------------------------------------
#
# A vendor gets only: their project assignment, their task assignment, one
# reminder the day before the task, and the notice if they are removed (see
# message_dispatch.py). Each message greets the contact by name, says in
# plain words what happened and what to do, and repeats it in Hindi.


def _contact(db: Session, vendor_contact_id: uuid.UUID) -> V2VendorContact | None:
    return db.get(V2VendorContact, vendor_contact_id)


def _day(value: date | None) -> str:
    return value.strftime("%a, %d %b %Y").replace(" 0", " ") if value else "to be confirmed"


def _duration(task: Task | None) -> str | None:
    if task is None or not task.planned_start_date or not task.planned_end_date:
        return None
    days = (task.planned_end_date - task.planned_start_date).days + 1
    return f"{days} day" if days == 1 else f"{days} days"


def _site_people(db: Session, project_id: object) -> dict[str, str]:
    """Names of the project's active Site Supervisor and PM - who a vendor
    should talk to on site."""
    resolved = _uuid_or_none(project_id)
    if not resolved:
        return {}
    rows = db.execute(
        select(V2ProjectMembership.project_role, User.name)
        .join(EmployeeProfile, EmployeeProfile.id == V2ProjectMembership.employee_id)
        .join(User, User.id == EmployeeProfile.user_id)
        .where(
            V2ProjectMembership.project_id == resolved,
            V2ProjectMembership.ends_at.is_(None),
            V2ProjectMembership.project_role.in_(("site_supervisor", "project_manager")),
        )
        .order_by(V2ProjectMembership.created_at)
    ).all()
    people: dict[str, str] = {}
    for role, name in rows:
        people.setdefault(role, name)
    return people


def _vendor_message(
    title: str, title_hi: str, english: list[str], hindi: list[str], actions=(),
) -> TelegramMessage:
    """Bold bilingual title, then the English block, then the Hindi block."""
    text = "\n".join([
        f"<b>{_e(title)}</b>",
        f"<b>{_e(title_hi)}</b>",
        "",
        "\n".join(english),
        "",
        "\n".join(hindi),
    ])
    return TelegramMessage(text=text, parse_mode="HTML", actions=tuple(actions))


def _greeting(contact: V2VendorContact | None, english: bool) -> str:
    name = _e(contact.name) if contact else ""
    if english:
        return f"Hello {name}," if name else "Hello,"
    return f"नमस्ते {name}," if name else "नमस्ते,"


def _details(pairs: list[tuple[str, str | None]]) -> list[str]:
    return [f"{_e(label)}: <b>{_e(value)}</b>" for label, value in pairs if value]


def _project_details(db: Session, project: V2Project | None, payload: dict, hindi: bool) -> list[str]:
    people = _site_people(db, project.id if project else None)
    name = project.name if project else payload.get("project_name") or "Unknown project"
    return _details([
        ("प्रोजेक्ट" if hindi else "Project", name),
        ("साइट" if hindi else "Site", project.site_address if project else None),
        ("शुरुआत" if hindi else "Starts", _day(project.start_date) if project else None),
        ("साइट सुपरवाइज़र" if hindi else "Site Supervisor", people.get("site_supervisor")),
        ("प्रोजेक्ट मैनेजर" if hindi else "Project Manager", people.get("project_manager")),
    ])


def _task_details(db: Session, project: V2Project | None, task: Task | None, hindi: bool) -> list[str]:
    people = _site_people(db, project.id if project else None)
    return _details([
        ("प्रोजेक्ट" if hindi else "Project", project.name if project else "Unknown project"),
        ("कार्य" if hindi else "Task", f"{task.original_code} - {task.title}" if task else "Unknown task"),
        ("साइट" if hindi else "Site", project.site_address if project else None),
        ("शुरुआत" if hindi else "Start", _day(task.planned_start_date) if task else None),
        ("अवधि" if hindi else "Duration", _duration(task)),
        ("साइट सुपरवाइज़र" if hindi else "Site Supervisor", people.get("site_supervisor")),
    ])


def _vendor_project_assignment(db: Session, payload: dict, contact: V2VendorContact | None) -> TelegramMessage:
    project = _get(db, V2Project, payload.get("project_id"))
    vendor = db.get(V2Vendor, contact.vendor_id) if contact else None
    company = _e(vendor.name) if vendor else "Your company"
    mapping = None
    if contact is not None and project is not None:
        mapping = db.scalar(
            select(ProjectVendor).where(
                ProjectVendor.project_id == project.id,
                ProjectVendor.vendor_id == contact.vendor_id,
                ProjectVendor.ends_at.is_(None),
            ).limit(1)
        )
    pending = mapping is not None and mapping.acknowledged_at is None
    english = [
        f"{_greeting(contact, True)} <b>{company}</b> has been assigned to a new project.",
        "",
        *_project_details(db, project, payload, hindi=False),
        "",
        "Please tap <b>Acknowledge</b> to confirm you have received this assignment."
        if pending else "You have already confirmed this assignment. Thank you.",
    ]
    hindi = [
        f"{_greeting(contact, False)} <b>{company}</b> को एक नए प्रोजेक्ट पर नियुक्त किया गया है।",
        "",
        *_project_details(db, project, payload, hindi=True),
        "",
        "यह असाइनमेंट मिलने की पुष्टि के लिए कृपया <b>स्वीकार करें</b> दबाएँ।"
        if pending else "आप इस असाइनमेंट की पुष्टि पहले ही कर चुके हैं। धन्यवाद।",
    ]
    actions = ((TelegramAction(VENDOR_ACK_LABEL, "", ack_callback(ACK_PROJECT_VENDOR, mapping.id)),),) if pending else ()
    return _vendor_message("New Project Assignment", "नया प्रोजेक्ट असाइनमेंट", english, hindi, actions)


def _vendor_project_activated(db: Session, payload: dict, vendor_contact_id: uuid.UUID) -> TelegramMessage:
    return _vendor_project_assignment(db, payload, _contact(db, vendor_contact_id))


def _vendor_project_vendor_mapped(db: Session, payload: dict, vendor_contact_id: uuid.UUID) -> TelegramMessage:
    # Dispatch sends this only to the vendor just mapped.
    return _vendor_project_assignment(db, payload, _contact(db, vendor_contact_id))


def _vendor_task_assigned(db: Session, payload: dict, vendor_contact_id: uuid.UUID) -> TelegramMessage:
    contact = _contact(db, vendor_contact_id)
    project = _get(db, V2Project, payload.get("project_id"))
    task = _get(db, Task, payload.get("task_id"))
    assignment = _get(db, TaskVendorAssignment, payload.get("assignment_id"))
    pending = assignment is not None and assignment.ends_at is None and assignment.status == "pending_ack"
    ref = assignment.id.hex[:8] if assignment is not None else ""
    english = [
        f"{_greeting(contact, True)} you have a new task.",
        "",
        *_task_details(db, project, task, hindi=False),
        "",
        "Please tap <b>Acknowledge</b> to confirm you can take up this task. "
        f"If you cannot, reply <code>DECLINE {ref}</code>."
        if pending else "No action is needed on this message.",
    ]
    hindi = [
        f"{_greeting(contact, False)} आपको एक नया कार्य सौंपा गया है।",
        "",
        *_task_details(db, project, task, hindi=True),
        "",
        "यह कार्य लेने की पुष्टि के लिए कृपया <b>स्वीकार करें</b> दबाएँ। "
        f"अगर आप यह नहीं कर सकते, तो <code>DECLINE {ref}</code> लिखकर भेजें।"
        if pending else "इस संदेश पर कोई कार्रवाई आवश्यक नहीं है।",
    ]
    actions = ()
    if pending:
        # The Decline line is already in the text; only Acknowledge is a button.
        actions = ((TelegramAction(VENDOR_ACK_LABEL, f"ACCEPT {ref}", ack_callback(ACK_VENDOR_TASK, assignment.id)),),)
    return _vendor_message("New Task for You", "आपके लिए नया कार्य", english, hindi, actions)


def _vendor_task_starts_tomorrow(db: Session, payload: dict, vendor_contact_id: uuid.UUID) -> TelegramMessage:
    """The vendor's one reminder: the day before their task starts."""
    contact = _contact(db, vendor_contact_id)
    project = _get(db, V2Project, payload.get("project_id"))
    task = _get(db, Task, payload.get("task_id"))
    when = _day(task.planned_start_date) if task else "tomorrow"
    english = [
        f"{_greeting(contact, True)} a reminder that your work starts <b>tomorrow, {_e(when)}</b>.",
        "",
        *_task_details(db, project, task, hindi=False),
        "",
        "Please make sure your team, materials and tools reach the site on time. "
        "If anything will stop you from starting, tell the Site Supervisor today.",
    ]
    hindi = [
        f"{_greeting(contact, False)} याद दिला दें कि आपका काम <b>कल, {_e(when)}</b> से शुरू होगा।",
        "",
        *_task_details(db, project, task, hindi=True),
        "",
        "कृपया सुनिश्चित करें कि आपकी टीम, सामग्री और औज़ार समय पर साइट पर पहुँचें। "
        "अगर किसी वजह से काम शुरू नहीं हो सकता, तो आज ही साइट सुपरवाइज़र को बताएँ।",
    ]
    return _vendor_message("Reminder: Work Starts Tomorrow", "याद दिलाना: काम कल से शुरू", english, hindi)


def _vendor_task_unassigned(db: Session, payload: dict, vendor_contact_id: uuid.UUID) -> TelegramMessage:
    contact = _contact(db, vendor_contact_id)
    project = _get(db, V2Project, payload.get("project_id"))
    task = _get(db, Task, payload.get("task_id"))
    reason = payload.get("reason")
    task_label = f"{task.original_code} - {task.title}" if task else "Unknown task"
    english = [
        f"{_greeting(contact, True)} the task below is no longer assigned to you.",
        "",
        *_details([("Project", project.name if project else "Unknown project"), ("Task", task_label), ("Reason", reason)]),
        "",
        "You do not need to do any work on this task. Contact the Project Manager if you have questions.",
    ]
    hindi = [
        f"{_greeting(contact, False)} नीचे दिया गया कार्य अब आपको सौंपा नहीं गया है।",
        "",
        *_details([("प्रोजेक्ट", project.name if project else "Unknown project"), ("कार्य", task_label), ("कारण", reason)]),
        "",
        "आपको इस कार्य पर कोई काम नहीं करना है। कोई सवाल हो तो प्रोजेक्ट मैनेजर से संपर्क करें।",
    ]
    return _vendor_message("Task Withdrawn", "कार्य वापस लिया गया", english, hindi)


def _vendor_project_removed(db: Session, payload: dict, vendor_contact_id: uuid.UUID) -> TelegramMessage:
    contact = _contact(db, vendor_contact_id)
    project = _get(db, V2Project, payload.get("project_id"))
    reason = payload.get("reason")
    name = project.name if project else "Unknown project"
    english = [
        f"{_greeting(contact, True)} your company is no longer part of this project.",
        "",
        *_details([("Project", name), ("Reason", reason)]),
        "",
        "Any tasks you had on this project have been withdrawn. Contact the Project Manager if you have questions.",
    ]
    hindi = [
        f"{_greeting(contact, False)} आपकी कंपनी अब इस प्रोजेक्ट का हिस्सा नहीं है।",
        "",
        *_details([("प्रोजेक्ट", name), ("कारण", reason)]),
        "",
        "इस प्रोजेक्ट पर आपके सभी कार्य वापस ले लिए गए हैं। कोई सवाल हो तो प्रोजेक्ट मैनेजर से संपर्क करें।",
    ]
    return _vendor_message("Removed from Project", "प्रोजेक्ट से हटाया गया", english, hindi)


# Staff copy when a vendor is taken off a task (the vendor gets its own).
def _render_task_vendor_unassigned(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    project = _get(db, V2Project, payload.get("project_id"))
    task = _get(db, Task, payload.get("task_id"))
    vendor = _get(db, V2Vendor, payload.get("vendor_id"))
    rows = _project_rows(project, payload)[:1] + [
        ("Task", f"{task.original_code} - {task.title}" if task else "Unknown task"),
        ("Vendor", vendor.name if vendor else "Unknown vendor"),
        *([("Reason", payload["reason"])] if payload.get("reason") else []),
    ]
    return _message("Vendor Removed from Task", rows, _FYI)


ASSIGNMENT_RENDERERS: dict[str, Callable[[Session, dict, uuid.UUID | None], TelegramMessage]] = {
    "project.activated": _render_project_activated,
    "project.member_added": _render_project_member_added,
    "project.vendor_mapped": _render_project_vendor_mapped,
    "task.vendor_assigned": _render_task_vendor_assigned,
    "task.vendor_unassigned": _render_task_vendor_unassigned,
}

# Used instead of the renderers above when the recipient is a vendor contact.
VENDOR_RENDERERS: dict[str, Callable[[Session, dict, uuid.UUID], TelegramMessage]] = {
    "project.activated": _vendor_project_activated,
    "project.vendor_mapped": _vendor_project_vendor_mapped,
    "task.vendor_assigned": _vendor_task_assigned,
    "task.prestart_warning": _vendor_task_starts_tomorrow,
    "task.vendor_unassigned": _vendor_task_unassigned,
    "project.vendor_removed": _vendor_project_removed,
}
