"""Acknowledge-button presses for onboarding and assignments (Telegram T2).

An Acknowledge button (`a1:<code>:<row id>`, see `telegram_message.py`)
records that the person received an assignment. It is a receipt only: it
grants nothing and never changes a task's lifecycle.

- `pm` a project membership - sets `acknowledged_at` on every active
  membership the person holds on that project (one tap for someone who is,
  say, both Supervisor and PM);
- `sa` a task support assignment - sets its `acknowledged_at`;
- `pv` a vendor's project mapping - sets its `acknowledged_at`;
- `va` a vendor task assignment - `VendorAcknowledgementService.
  record_acknowledgement(response="accepted")`, recorded on the vendor's
  behalf by the project's active PM, exactly what a typed `ACCEPT <ref>` does
  (`inbound_message.py`).

Guards: a private chat pressed by its own owner; `pm`/`sa` need the chat
linked to exactly one active SiteOps person who owns the row, `pv`/`va` the
vendor contact whose vendor owns it. An ended row, or one belonging to
someone else, is "no longer available". A second press is "Already
acknowledged". Vendor feedback is English with Hindi.

Each press is recorded as an `InboundMessage` keyed by the Telegram
`update_id`, the same audit trail task and gate buttons leave.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.execution_models import InboundMessage, Task, TaskSupportAssignment
from app.models import EmployeeProfile, User
from app.project_models import V2Project, V2ProjectMembership
from app.services.inbound_message import active_pm_user
from app.services.telegram_assignment_render import (
    ACK_MEMBERSHIP,
    ACK_PROJECT_VENDOR,
    ACK_SUPPORT_ASSIGNMENT,
    ACK_VENDOR_TASK,
)
from app.services.telegram_message import parse_ack_callback
from app.services.telegram_provider import TelegramProviderAdapter
from app.services.vendor_acknowledgement import RESOLVED_ASSIGNMENT_STATUSES, VendorAcknowledgementService
from app.vendor_models import ProjectVendor, TaskVendorAssignment, V2VendorContact

UNLINKED = "This Telegram account isn't linked to SiteOps. Ask your Admin for a new connect link."
STALE = "This button is no longer available."
PRIVATE_ONLY = "Use the bot in a private chat to acknowledge."

_DONE_TOAST = "Acknowledged"
_ALREADY_TOAST = "Already acknowledged"
_VENDOR_DONE_TOAST = "Acknowledged / स्वीकार किया गया"
_VENDOR_ALREADY_TOAST = "Already acknowledged / पहले ही स्वीकार किया जा चुका है"
_VENDOR_STALE = "This button is no longer available.\nयह बटन अब उपलब्ध नहीं है।"
_VENDOR_THANKS = "Thank you. Your acknowledgement has been recorded.\nधन्यवाद। आपकी पुष्टि दर्ज कर ली गई है।"

_INTERNAL_CODES = frozenset({ACK_MEMBERSHIP, ACK_SUPPORT_ASSIGNMENT})
_VENDOR_CODES = frozenset({ACK_PROJECT_VENDOR, ACK_VENDOR_TASK})


def _e(value: object) -> str:
    return html.escape(str(value), quote=False)


class TelegramAckCallbackService:
    def __init__(self, db: Session, provider: TelegramProviderAdapter | None = None):
        self.db = db
        self.provider = provider or TelegramProviderAdapter()

    def handle(
        self,
        *,
        update_id: int,
        chat_id: str,
        chat_type: str | None,
        from_id: str | None,
        message_id: int | None,
        callback_query_id: str | None,
        data: str | None,
    ) -> bool:
        """Handles one Acknowledge press. Returns True when an
        acknowledgement was newly recorded."""
        callback = parse_ack_callback(data)
        if callback is None or callback.code not in _INTERNAL_CODES | _VENDOR_CODES:
            self._refuse(chat_id, callback_query_id, STALE)
            return False
        if chat_type != "private" or from_id != chat_id:
            self._refuse(chat_id, callback_query_id, PRIVATE_ONLY)
            return False

        if callback.code in _INTERNAL_CODES:
            employee = self._linked_employee(chat_id)
            if employee is None:
                self._refuse(chat_id, callback_query_id, UNLINKED)
                return False
            handler = self._membership if callback.code == ACK_MEMBERSHIP else self._support_assignment
            outcome = handler(callback.row_id, employee)
            identity = ("employee", employee.id)
        else:
            contact = self.db.scalar(select(V2VendorContact).where(V2VendorContact.telegram_chat_id == chat_id))
            if contact is None:
                self._refuse(chat_id, callback_query_id, UNLINKED)
                return False
            handler = self._project_vendor if callback.code == ACK_PROJECT_VENDOR else self._vendor_task
            outcome = handler(callback.row_id, contact)
            identity = ("vendor_contact", contact.id)

        status, detail = outcome
        vendor = callback.code in _VENDOR_CODES
        self._record(update_id, chat_id, identity, status, detail if status == "rejected" else None, data)
        if status == "processed":
            self._answer(callback_query_id, _VENDOR_DONE_TOAST if vendor else _DONE_TOAST)
            if message_id is not None:
                self.provider.remove_buttons(chat_id, message_id)
            self._reply(chat_id, detail)
            return True
        if status == "already":
            self._answer(callback_query_id, _VENDOR_ALREADY_TOAST if vendor else _ALREADY_TOAST)
            if message_id is not None:
                self.provider.remove_buttons(chat_id, message_id)
            return False
        self._refuse(chat_id, callback_query_id, detail)
        return False

    # ---- internal people ------------------------------------------------------

    def _membership(self, membership_id, employee: EmployeeProfile) -> tuple[str, str]:
        membership = self.db.get(V2ProjectMembership, membership_id)
        if membership is None or membership.employee_id != employee.id or membership.ends_at is not None:
            return "rejected", STALE
        acknowledged = self.db.execute(
            update(V2ProjectMembership)
            .where(
                V2ProjectMembership.project_id == membership.project_id,
                V2ProjectMembership.employee_id == employee.id,
                V2ProjectMembership.ends_at.is_(None),
                V2ProjectMembership.acknowledged_at.is_(None),
            )
            .values(acknowledged_at=datetime.now(timezone.utc))
        ).rowcount
        self.db.commit()
        if not acknowledged:
            return "already", ""
        project = self.db.get(V2Project, membership.project_id)
        return "processed", (
            "<b>Assignment Acknowledged</b>\n\n"
            f"Project: {_e(project.name if project else 'Unknown project')}\n\n"
            "Thank you. Your acknowledgement has been recorded."
        )

    def _support_assignment(self, assignment_id, employee: EmployeeProfile) -> tuple[str, str]:
        assignment = self.db.get(TaskSupportAssignment, assignment_id)
        if (
            assignment is None or assignment.employee_id != employee.id
            or assignment.status != "active" or assignment.ends_at is not None
        ):
            return "rejected", STALE
        acknowledged = self.db.execute(
            update(TaskSupportAssignment)
            .where(TaskSupportAssignment.id == assignment.id, TaskSupportAssignment.acknowledged_at.is_(None))
            .values(acknowledged_at=datetime.now(timezone.utc))
        ).rowcount
        self.db.commit()
        if not acknowledged:
            return "already", ""
        task = self.db.get(Task, assignment.task_id)
        project = self.db.get(V2Project, assignment.project_id)
        return "processed", (
            "<b>Task Acknowledged</b>\n\n"
            f"Project: {_e(project.name if project else 'Unknown project')}\n"
            f"Task: {_e(f'{task.original_code} - {task.title}' if task else 'Unknown task')}\n\n"
            "Thank you. Your acknowledgement has been recorded."
        )

    # ---- vendor contacts --------------------------------------------------------

    def _project_vendor(self, mapping_id, contact: V2VendorContact) -> tuple[str, str]:
        mapping = self.db.get(ProjectVendor, mapping_id)
        if mapping is None or mapping.vendor_id != contact.vendor_id or mapping.ends_at is not None:
            return "rejected", _VENDOR_STALE
        acknowledged = self.db.execute(
            update(ProjectVendor)
            .where(ProjectVendor.id == mapping.id, ProjectVendor.acknowledged_at.is_(None))
            .values(acknowledged_at=datetime.now(timezone.utc))
        ).rowcount
        self.db.commit()
        if not acknowledged:
            return "already", ""
        project = self.db.get(V2Project, mapping.project_id)
        return "processed", (
            "<b>Acknowledged / स्वीकार किया गया</b>\n\n"
            f"Project / प्रोजेक्ट: {_e(project.name if project else 'Unknown project')}\n\n"
            f"{_e(_VENDOR_THANKS)}"
        )

    def _vendor_task(self, assignment_id, contact: V2VendorContact) -> tuple[str, str]:
        assignment = self.db.get(TaskVendorAssignment, assignment_id)
        if assignment is None or assignment.vendor_id != contact.vendor_id or assignment.ends_at is not None:
            return "rejected", _VENDOR_STALE
        if assignment.status in RESOLVED_ASSIGNMENT_STATUSES:
            return ("already", "") if assignment.status == "acknowledged" else ("rejected", _VENDOR_STALE)
        pm_actor = active_pm_user(self.db, assignment.project_id)
        if pm_actor is None:
            return "rejected", "No active PM on this project to record the acknowledgement."
        try:
            VendorAcknowledgementService(self.db).record_acknowledgement(
                assignment.project_id, assignment.task_id, assignment.id,
                response="accepted", actor=pm_actor, channel="telegram",
            )
        except HTTPException as exc:
            self.db.rollback()
            return "rejected", str(exc.detail)
        task = self.db.get(Task, assignment.task_id)
        project = self.db.get(V2Project, assignment.project_id)
        return "processed", (
            "<b>Acknowledged / स्वीकार किया गया</b>\n\n"
            f"Project / प्रोजेक्ट: {_e(project.name if project else 'Unknown project')}\n"
            f"Task / कार्य: {_e(f'{task.original_code} - {task.title}' if task else 'Unknown task')}\n\n"
            f"{_e(_VENDOR_THANKS)}"
        )

    # ---- identity, feedback and audit -----------------------------------------

    def _linked_employee(self, chat_id: str) -> EmployeeProfile | None:
        """The single active employee this chat is linked to. A chat that is
        also a vendor contact never acts as an internal person."""
        rows = self.db.scalars(
            select(EmployeeProfile)
            .join(User, User.id == EmployeeProfile.user_id)
            .where(EmployeeProfile.telegram_chat_id == chat_id, User.active.is_(True))
        ).all()
        vendor = self.db.scalar(select(V2VendorContact.id).where(V2VendorContact.telegram_chat_id == chat_id).limit(1))
        return rows[0] if len(rows) == 1 and vendor is None else None

    def _record(self, update_id: int, chat_id: str, identity, status: str, reason: str | None, data: str | None) -> None:
        provider_message_id = str(update_id)
        if self.db.scalar(select(InboundMessage.id).where(InboundMessage.provider_message_id == provider_message_id)):
            return
        self.db.add(InboundMessage(
            provider_message_id=provider_message_id, sender_phone=chat_id, raw_body=f"[button] Acknowledge {data}",
            matched_identity_type=identity[0], matched_identity_id=identity[1],
            processing_status="processed" if status in ("processed", "already") else "rejected",
            rejection_reason=reason,
        ))
        self.db.commit()

    def _refuse(self, chat_id: str, callback_query_id: str | None, reason: str) -> None:
        self._answer(callback_query_id, reason.split("\n")[0])
        self._reply(chat_id, _e(reason))

    def _answer(self, callback_query_id: str | None, text: str) -> None:
        if callback_query_id:
            self.provider.answer_callback_query(callback_query_id, text)

    def _reply(self, chat_id: str, html_text: str) -> None:
        self.provider.send_text(chat_id, html_text, parse_mode="HTML")
