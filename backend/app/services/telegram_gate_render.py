"""Readable Telegram templates for External Approval Gate events.

Replaces the raw key:value dump for every `project_external_approval.*` and
`gate_confirmation.*` event. Rendering is recipient-specific: the employee
responsible for the gate gets the actionable copy, everyone else (Admins) gets
an FYI copy with no actions. Who "the responsible employee" is comes from the
event payload where the event names them (so a message still reads correctly
if the gate changed hands before dispatch), falling back to the gate's current
assignee.

Read-only like `telegram_render.py`: it never mutates anything, holds no gate
business rules, and degrades to placeholders on missing/unknown ids rather
than raising. Every dynamic value is HTML-escaped (messages are sent with
`parse_mode="HTML"`), and no UUID, event name or payload key is ever shown -
the only identifier that appears is the 8-character gate reference inside the
typed-command fallback, which is the reference users already type today.
"""

from __future__ import annotations

import html
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import (
    FileObject,
    ProjectExternalApproval,
    ProjectExternalApprovalEvidence,
    ProjectExternalApprovalSubmission,
)
from app.models import EmployeeProfile, User
from app.project_models import V2Project, V2ProjectExternalGate
from app.services.project_gate_status_check import STATUS_CHECK_HEALTHS
from app.services.telegram_message import TelegramAction, TelegramMessage

# Users are in India; IST has no DST, so a fixed offset is exact.
_IST = timezone(timedelta(hours=5, minutes=30), "IST")

HEALTH_LABELS = {
    "on_track": "On Track",
    "waiting_external": "Waiting on External",
    "blocked": "Blocked",
    "need_help": "Need Help",
}
# Display order for health choices; only values the status-check service
# actually accepts are offered.
_HEALTH_ORDER = ("on_track", "waiting_external", "blocked", "need_help")

_FYI = "For your information. No action required."


def _e(value: object) -> str:
    return html.escape(str(value))


def _uuid_or_none(value: object) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _user_name(db: Session, user_id: object, fallback: str = "Unknown user") -> str:
    resolved = _uuid_or_none(user_id)
    user = db.get(User, resolved) if resolved else None
    return user.name if user else fallback


def _format_date(value: object) -> str:
    if not value:
        return "Not set"
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y").lstrip("0")
    if isinstance(value, date):
        return value.strftime("%d %b %Y").lstrip("0")
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d %b %Y").lstrip("0")
    except ValueError:
        return str(value)  # e.g. "No due date set"


def _format_timestamp(value: datetime | None) -> str:
    if value is None:
        return "Not recorded"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    local = value.astimezone(_IST)
    return f"{local.strftime('%d %b %Y').lstrip('0')}, {local.strftime('%I:%M %p').lstrip('0')} IST"


@dataclass(frozen=True)
class _Gate:
    approval: ProjectExternalApproval | None
    gate_name: str
    project_name: str
    due: str
    ref: str


def _gate(db: Session, payload: dict) -> _Gate:
    approval_id = _uuid_or_none(payload.get("approval_id"))
    approval = db.get(ProjectExternalApproval, approval_id) if approval_id else None

    gate_name = payload.get("gate_name")
    if not gate_name and approval is not None:
        gate = db.get(V2ProjectExternalGate, approval.project_gate_id)
        gate_name = gate.approval_name if gate else None

    project_name = payload.get("project_name")
    if not project_name:
        project_id = _uuid_or_none(payload.get("project_id")) or (approval.project_id if approval else None)
        project = db.get(V2Project, project_id) if project_id else None
        project_name = project.name if project else None

    due_raw = payload.get("due_date") or payload.get("due_at") or (approval.due_at if approval else None)
    ref = str(approval_id).replace("-", "")[:8] if approval_id else "?"
    return _Gate(
        approval=approval,
        gate_name=gate_name or "Unknown approval",
        project_name=project_name or "Unknown project",
        due=_format_date(due_raw),
        ref=ref,
    )


def _recipient_user_id(db: Session, recipient_employee_id: uuid.UUID | None) -> uuid.UUID | None:
    if recipient_employee_id is None:
        return None
    return db.scalar(select(EmployeeProfile.user_id).where(EmployeeProfile.id == recipient_employee_id))


def _is_user(recipient_user_id: uuid.UUID | None, user_id: object) -> bool:
    return recipient_user_id is not None and recipient_user_id == _uuid_or_none(user_id)


def _message(
    title: str,
    rows: list[tuple[str, object]],
    paragraphs: list[str] = (),
    actions: tuple[tuple[TelegramAction, ...], ...] = (),
) -> TelegramMessage:
    parts = [f"<b>{_e(title)}</b>"]
    if rows:
        parts.append("\n".join(f"{_e(label)}: {_e(value)}" for label, value in rows))
    parts.extend(_e(p) for p in paragraphs)
    return TelegramMessage(text="\n\n".join(parts), parse_mode="HTML", actions=actions)


# ---- actions (each is the exact typed command that performs it) -------------


def _health_values(exclude: tuple[str, ...] = ()) -> list[str]:
    return [h for h in _HEALTH_ORDER if h in STATUS_CHECK_HEALTHS and h not in exclude]


def _health_actions(ref: str, exclude: tuple[str, ...] = ()) -> tuple[TelegramAction, ...]:
    return tuple(TelegramAction(HEALTH_LABELS[h], f"GATESTATUS {ref} {h}") for h in _health_values(exclude))


def _submit_evidence(ref: str, label: str = "Submit Evidence") -> TelegramAction:
    return TelegramAction(label, f"GATEOPEN {ref}")


def _progress_actions(ref: str, exclude: tuple[str, ...] = ()) -> tuple[tuple[TelegramAction, ...], ...]:
    return (_health_actions(ref, exclude), (_submit_evidence(ref),))


# ---- templates ----------------------------------------------------------------


def _assigned_to_employee(g: _Gate) -> TelegramMessage:
    return _message(
        "External Approval Assigned",
        [("Approval", g.gate_name), ("Project", g.project_name), ("Due", g.due)],
        [
            "You are responsible for coordinating this external approval.",
            "This may take time depending on the external authority.",
        ],
        actions=((TelegramAction("Acknowledge", f"GATEACCEPT {g.ref}"), TelegramAction("Decline", f"GATEDECLINE {g.ref}")),),
    )


def _responsibility_removed(g: _Gate) -> TelegramMessage:
    return _message(
        "External Approval Responsibility Removed",
        [("Approval", g.gate_name), ("Project", g.project_name)],
        ["You are no longer responsible for this approval.", "No action required."],
    )


def _render_assigned(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    g = _gate(db, payload)
    me = _recipient_user_id(db, recipient_employee_id)
    if _is_user(me, payload.get("assigned_to_user_id")):
        return _assigned_to_employee(g)
    return _message(
        "External Approval Assigned",
        [
            ("Approval", g.gate_name), ("Project", g.project_name), ("Due", g.due),
            ("Assigned to", _user_name(db, payload.get("assigned_to_user_id"))),
        ],
        [_FYI],
    )


def _render_reassigned(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    g = _gate(db, payload)
    me = _recipient_user_id(db, recipient_employee_id)
    if _is_user(me, payload.get("assigned_to_user_id")):
        return _assigned_to_employee(g)
    if _is_user(me, payload.get("previous_assignee_id")):
        return _responsibility_removed(g)
    return _message(
        "External Approval Reassigned",
        [
            ("Approval", g.gate_name), ("Project", g.project_name),
            ("From", _user_name(db, payload.get("previous_assignee_id"), "Not recorded")),
            ("To", _user_name(db, payload.get("assigned_to_user_id"))),
        ],
        [_FYI],
    )


def _render_unassigned(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    g = _gate(db, payload)
    me = _recipient_user_id(db, recipient_employee_id)
    if _is_user(me, payload.get("previous_assignee_id")):
        return _responsibility_removed(g)
    return _message(
        "External Approval Unassigned",
        [
            ("Approval", g.gate_name), ("Project", g.project_name),
            ("Previously assigned to", _user_name(db, payload.get("previous_assignee_id"), "Not recorded")),
        ],
        ["Assign it again from the Web App when ready."],
    )


def _current_assignee(g: _Gate, payload: dict) -> object:
    return payload.get("assigned_to_user_id") or (g.approval.assigned_to_user_id if g.approval else None)


def _render_accepted(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    g = _gate(db, payload)
    assignee = _current_assignee(g, payload)
    if _is_user(_recipient_user_id(db, recipient_employee_id), assignee):
        return _message(
            "Approval Acknowledged",
            [("Approval", g.gate_name), ("Project", g.project_name)],
            [
                "Responsibility has been acknowledged.",
                "Use the options below whenever you need to update progress or submit evidence.",
            ],
            actions=_progress_actions(g.ref),
        )
    return _message(
        "External Approval Acknowledged",
        [("Approval", g.gate_name), ("Project", g.project_name), ("Acknowledged by", _user_name(db, assignee))],
        ["Responsibility has been acknowledged. The approval has not been submitted yet.", _FYI],
    )


def _render_declined(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    g = _gate(db, payload)
    assignee = _current_assignee(g, payload)
    if _is_user(_recipient_user_id(db, recipient_employee_id), assignee):
        return _message(
            "Approval Assignment Declined",
            [("Approval", g.gate_name), ("Project", g.project_name)],
            [
                "Your decline has been recorded.",
                "The Admin can reassign this approval from the Web App.",
                "No further Telegram action required.",
            ],
        )
    rows = [("Approval", g.gate_name), ("Project", g.project_name), ("Declined by", _user_name(db, assignee))]
    if payload.get("note"):
        rows.append(("Note", payload["note"]))
    return _message("External Approval Declined", rows, ["Reassign this approval from the Web App."])


def _render_status_checked(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    g = _gate(db, payload)
    health = payload.get("health")
    health_label = HEALTH_LABELS.get(health, health or "Unknown")
    note = payload.get("note") or "No note"
    assignee = _current_assignee(g, payload)
    if _is_user(_recipient_user_id(db, recipient_employee_id), assignee):
        return _message(
            "Status Updated",
            [("Approval", g.gate_name), ("Status", health_label), ("Note", note)],
            ["This is only a progress update.", "The approval has not been submitted for Admin decision."],
            actions=_progress_actions(g.ref),
        )
    return _message(
        "External Approval Status Update",
        [
            ("Approval", g.gate_name), ("Project", g.project_name),
            ("From", _user_name(db, assignee)), ("Status", health_label), ("Note", note),
        ],
        ["Progress update only - not yet submitted for decision.", _FYI],
    )


def _submission_items(db: Session, submission_id: object) -> tuple[int, str]:
    """(submitted item count, human summary) - files plus the note, if any."""
    resolved = _uuid_or_none(submission_id)
    submission = db.get(ProjectExternalApprovalSubmission, resolved) if resolved else None
    if submission is None:
        return 0, "Not available"
    mime_types = list(
        db.scalars(
            select(FileObject.mime_type)
            .join(ProjectExternalApprovalEvidence, ProjectExternalApprovalEvidence.file_id == FileObject.id)
            .where(ProjectExternalApprovalEvidence.submission_id == submission.id)
        )
    )
    photos = sum(1 for m in mime_types if (m or "").startswith("image/"))
    pdfs = sum(1 for m in mime_types if m == "application/pdf")
    others = len(mime_types) - photos - pdfs
    has_note = bool((submission.note or "").strip())
    parts = []
    if photos:
        parts.append(f"{photos} photo{'s' if photos != 1 else ''}")
    if pdfs:
        parts.append(f"{pdfs} PDF{'s' if pdfs != 1 else ''}")
    if others:
        parts.append(f"{others} file{'s' if others != 1 else ''}")
    if has_note:
        parts.append("note")
    return len(mime_types) + (1 if has_note else 0), (", ".join(parts) if parts else "None")


def _render_submitted(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    g = _gate(db, payload)
    count, summary = _submission_items(db, payload.get("submission_id"))
    submitter = payload.get("submitted_by") or _current_assignee(g, payload)
    if _is_user(_recipient_user_id(db, recipient_employee_id), submitter):
        return _message(
            "Submitted for Review",
            [("Approval", g.gate_name), ("Project", g.project_name)],
            [
                "Your evidence has been submitted to Admin for review.",
                f"Submitted items: {count}",
                "No further action is required unless the Admin rejects it or asks for correction.",
            ],
        )
    submission_id = _uuid_or_none(payload.get("submission_id"))
    submission = db.get(ProjectExternalApprovalSubmission, submission_id) if submission_id else None
    return _message(
        "External Approval Ready for Review",
        [
            ("Approval", g.gate_name), ("Project", g.project_name),
            ("Submitted by", _user_name(db, submitter)),
            ("Submitted", _format_timestamp(submission.submitted_at if submission else None)),
            ("Evidence", summary),
        ],
        ["Review the evidence in the Web App (External Approvals) and decide."],
        actions=((
            TelegramAction("Approve", f"GATEDECIDE {g.ref} APPROVE"),
            TelegramAction("Reject", f"GATEDECIDE {g.ref} REJECT <reason>"),
        ),),
    )


def _render_decided(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    g = _gate(db, payload)
    approved = payload.get("decision") == "approved"
    decider = _user_name(db, payload.get("decided_by"))
    assignee = _current_assignee(g, payload)
    reason = payload.get("reason") or "No reason given"
    if _is_user(_recipient_user_id(db, recipient_employee_id), assignee):
        if approved:
            return _message(
                "External Approval Approved",
                [("Approval", g.gate_name), ("Project", g.project_name), ("Approved by", decider)],
                ["The approval is complete.", "Status: Approved", "No action required."],
            )
        return _message(
            "External Approval Rejected",
            [("Approval", g.gate_name), ("Project", g.project_name), ("Rejected by", decider), ("Reason", reason)],
            ["Please correct the issue and submit the updated evidence again."],
            actions=((_submit_evidence(g.ref, "Submit Evidence Again"),), _health_actions(g.ref)),
        )
    if approved:
        return _message(
            "External Approval Approved",
            [("Approval", g.gate_name), ("Project", g.project_name), ("Approved by", decider)],
            [_FYI],
        )
    return _message(
        "External Approval Rejected",
        [
            ("Approval", g.gate_name), ("Project", g.project_name),
            ("Rejected by", decider), ("Reason", reason),
        ],
        [f"Returned to {_user_name(db, assignee)} for correction and resubmission.", _FYI],
    )


def _render_due_reminder(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    g = _gate(db, payload)
    assignee = _current_assignee(g, payload)
    if _is_user(_recipient_user_id(db, recipient_employee_id), assignee):
        return _message(
            "Reminder - External Approval Due Tomorrow",
            [("Approval", g.gate_name), ("Project", g.project_name), ("Due", g.due)],
            ["Please update the status if anything has changed."],
            actions=_progress_actions(g.ref),
        )
    return _message(
        "External Approval Due Tomorrow",
        [("Approval", g.gate_name), ("Project", g.project_name), ("Due", g.due), ("Assigned to", _user_name(db, assignee))],
        ["A reminder has been sent to the assigned employee.", _FYI],
    )


def _render_overdue(title_employee: str, title_admin: str, admin_note: str):
    def _render(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
        g = _gate(db, payload)
        assignee = _current_assignee(g, payload)
        if _is_user(_recipient_user_id(db, recipient_employee_id), assignee):
            return _message(
                title_employee,
                [("Approval", g.gate_name), ("Project", g.project_name), ("Due", g.due)],
                ["This approval has not yet been submitted.", "Please update the current position."],
                actions=_progress_actions(g.ref, exclude=("on_track",)),
            )
        return _message(
            title_admin,
            [("Approval", g.gate_name), ("Project", g.project_name), ("Due", g.due), ("Assigned to", _user_name(db, assignee))],
            ["This approval has not yet been submitted.", admin_note],
        )

    return _render


# ---- gate command confirmations (sent back to whoever sent the command) -----


def _render_session_opened(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    g = _gate(db, payload)
    return _message(
        "Submit Evidence",
        [("Approval", g.gate_name), ("Project", g.project_name)],
        [
            "Send any supporting evidence for this approval.",
            "You may send:\n- Photo\n- PDF/document\n- Text note",
            "You can send more than one item.",
            "When finished, submit everything for review.",
        ],
        actions=((TelegramAction("Submit for Review", "GATECLOSE"),),),
    )


def _render_confirmation_simple(title: str, body: str):
    def _render(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
        g = _gate(db, payload)
        rows = [("Approval", g.gate_name), ("Project", g.project_name)]
        if payload.get("health"):
            rows.append(("Status", HEALTH_LABELS.get(payload["health"], payload["health"])))
        if payload.get("decision"):
            rows.append(("Decision", "Approved" if payload["decision"] == "approved" else "Rejected"))
        return _message(title, rows, [body])

    return _render


GATE_RENDERERS: dict[str, Callable[[Session, dict, uuid.UUID | None], TelegramMessage]] = {
    "project_external_approval.assigned": _render_assigned,
    "project_external_approval.reassigned": _render_reassigned,
    "project_external_approval.unassigned": _render_unassigned,
    "project_external_approval.accepted": _render_accepted,
    "project_external_approval.declined": _render_declined,
    "project_external_approval.status_checked": _render_status_checked,
    "project_external_approval.submitted": _render_submitted,
    "project_external_approval.decided": _render_decided,
    "project_external_approval.due_reminder": _render_due_reminder,
    "project_external_approval.followup_required": _render_overdue(
        "External Approval Overdue", "External Approval Overdue",
        "The assigned employee has been asked for an update.",
    ),
    "project_external_approval.escalated_to_admin": _render_overdue(
        "External Approval Still Overdue", "Escalation - External Approval Overdue",
        "Still not submitted after the follow-up. Consider contacting the employee or reassigning from the Web App.",
    ),
    "gate_confirmation.session_opened": _render_session_opened,
    # The confirmations below duplicate a main event the sender already
    # receives, so dispatch does not send them over Telegram (see
    # message_dispatch._TELEGRAM_REDUNDANT_GATE_CONFIRMATIONS). They still get
    # a readable template so nothing can ever reach Telegram as a raw dump.
    "gate_confirmation.accepted": _render_confirmation_simple("Approval Acknowledged", "Responsibility has been acknowledged."),
    "gate_confirmation.declined": _render_confirmation_simple("Approval Assignment Declined", "Your decline has been recorded."),
    "gate_confirmation.status_recorded": _render_confirmation_simple("Status Updated", "This is only a progress update."),
    "gate_confirmation.session_closed": _render_confirmation_simple("Submitted for Review", "Your evidence has been submitted to Admin for review."),
    "gate_confirmation.decided": _render_confirmation_simple("Decision Recorded", "Your decision has been recorded."),
}
