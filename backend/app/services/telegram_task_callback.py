"""Inline-button presses for internal task execution (Telegram task plan U5+).

A task button (`t1:<code>:<task id>`, see `telegram_message.py`) runs the
same shared service call the Web App makes - `TaskLifecycleService.transition`
for Mark Task Ready / Start Task - with source "telegram". Unlike gate
buttons it never becomes a typed command: task codes repeat across
projects, and the button already carries the task's real id (KTD6). No task
rule lives here; the service decides, and its refusal is shown in plain
words.

Guards before any action (KTD22):
- the press must come from a private chat with the bot, by the chat's own
  owner (a group chat, or someone else pressing, is refused);
- the chat must be linked to exactly one active SiteOps person;
- that person must be an Admin/Super Admin (whose existing authority needs
  no project membership) or an active member of the task's project.

Feedback, the same rules as gate buttons: the button spinner always gets a
short toast; on success the pressed message's buttons are removed; a second
press of a button that already succeeded on that message is answered
"Already done"; every refusal comes back as a readable message. Each press
is recorded as an `InboundMessage` keyed by the Telegram `update_id`
(audit trail and duplicate protection).
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import InboundMessage, Task, TelegramInboundUpdate
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2ProjectMembership
from app.services.task_lifecycle import TaskLifecycleService
from app.services.telegram_message import parse_task_callback
from app.services.telegram_provider import TelegramProviderAdapter
from app.vendor_models import V2VendorContact


@dataclass(frozen=True)
class _TaskButton:
    label: str
    what: str  # completes "Couldn't ..." in a refusal
    done_toast: str
    target_status: str


TASK_BUTTONS = {
    "rd": _TaskButton("Mark Task Ready", "mark this task ready", "Marked ready", "ready"),
    "st": _TaskButton("Start Task", "start this task", "Task started", "in_progress"),
}

UNLINKED = "This Telegram account isn't linked to SiteOps. Ask your Admin for a new connect link."
STALE = "This button is no longer available."
PRIVATE_ONLY = "Use the bot in a private chat to act on tasks."
NOT_A_MEMBER = "You are no longer a member of this task's project."


def _e(value: object) -> str:
    return html.escape(str(value), quote=False)


class TelegramTaskCallbackService:
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
        """Handles one task-button press. Returns True when an action ran
        successfully, so the caller can deliver its follow-up promptly."""
        callback = parse_task_callback(data)
        button = TASK_BUTTONS.get(callback.code) if callback else None
        if button is None:
            self._answer(callback_query_id, STALE)
            self._reply(chat_id, _e(STALE))
            return False

        if chat_type != "private" or from_id != chat_id:
            self._fail(chat_id, callback_query_id, button.what, PRIVATE_ONLY)
            return False

        if message_id is not None and self._already_done(update_id, chat_id, message_id, data):
            self._answer(callback_query_id, "Already done")
            self.provider.remove_buttons(chat_id, message_id)
            return False

        identity = self._linked_person(chat_id)
        if identity is None:
            self._record(update_id, chat_id, button, None, "unmatched", UNLINKED)
            self._fail(chat_id, callback_query_id, button.what, UNLINKED)
            return False
        user, employee = identity

        task = self.db.get(Task, callback.task_id)
        if task is None:
            self._record(update_id, chat_id, button, employee, "rejected", STALE)
            self._fail(chat_id, callback_query_id, button.what, STALE)
            return False
        if not self._may_act_on_project(user, employee, task):
            self._record(update_id, chat_id, button, employee, "rejected", NOT_A_MEMBER)
            self._fail(chat_id, callback_query_id, button.what, NOT_A_MEMBER)
            return False

        try:
            TaskLifecycleService(self.db).transition(
                task.project_id, task.id, button.target_status, user, source="telegram",
            )
        except HTTPException as exc:
            self.db.rollback()
            reason = str(exc.detail)
            self._record(update_id, chat_id, button, employee, "rejected", reason, task)
            self._fail(chat_id, callback_query_id, button.what, reason)
            return False

        self._record(update_id, chat_id, button, employee, "processed", None, task)
        self._answer(callback_query_id, button.done_toast)
        if message_id is not None:
            self.provider.remove_buttons(chat_id, message_id)
        return True

    # ---- guards ---------------------------------------------------------------------

    def _linked_person(self, chat_id: str) -> tuple[User, EmployeeProfile] | None:
        """The single active employee this chat is linked to. A chat that is
        also (or only) a vendor contact never acts on internal tasks."""
        rows = self.db.execute(
            select(User, EmployeeProfile)
            .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
            .where(EmployeeProfile.telegram_chat_id == chat_id, User.active.is_(True))
        ).all()
        vendor = self.db.scalar(select(V2VendorContact.id).where(V2VendorContact.telegram_chat_id == chat_id).limit(1))
        if len(rows) != 1 or vendor is not None:
            return None
        return rows[0][0], rows[0][1]

    def _may_act_on_project(self, user: User, employee: EmployeeProfile, task: Task) -> bool:
        """KTD22: Admin/Super Admin keep their existing authority, which needs
        no project membership; everyone else must still be on the project.
        Every other rule is the lifecycle service's."""
        if user.role in (UserRole.admin, UserRole.super_admin):
            return True
        return self.db.scalar(
            select(V2ProjectMembership.id).where(
                V2ProjectMembership.project_id == task.project_id,
                V2ProjectMembership.employee_id == employee.id,
                V2ProjectMembership.ends_at.is_(None),
            ).limit(1)
        ) is not None

    def _already_done(self, update_id: int, chat_id: str, message_id: int, data: str) -> bool:
        """Whether this same button on this same message already succeeded."""
        earlier_update_ids = [
            str(row.update_id)
            for row in self.db.scalars(
                select(TelegramInboundUpdate).where(
                    TelegramInboundUpdate.chat_id == chat_id,
                    TelegramInboundUpdate.callback_data == data,
                    TelegramInboundUpdate.update_id != update_id,
                )
            )
            if (((row.raw_payload or {}).get("callback_query") or {}).get("message") or {}).get("message_id") == message_id
        ]
        if not earlier_update_ids:
            return False
        return self.db.scalar(
            select(InboundMessage.id).where(
                InboundMessage.provider_message_id.in_(earlier_update_ids),
                InboundMessage.processing_status == "processed",
            ).limit(1)
        ) is not None

    # ---- feedback and audit ---------------------------------------------------------

    def _record(
        self, update_id: int, chat_id: str, button: _TaskButton, employee: EmployeeProfile | None,
        status: str, reason: str | None, task: Task | None = None,
    ) -> None:
        provider_message_id = str(update_id)
        if self.db.scalar(select(InboundMessage.id).where(InboundMessage.provider_message_id == provider_message_id)):
            return
        body = f"[button] {button.label}" + (f" {task.original_code}" if task is not None else "")
        self.db.add(InboundMessage(
            provider_message_id=provider_message_id, sender_phone=chat_id, raw_body=body,
            matched_identity_type="employee" if employee is not None else None,
            matched_identity_id=employee.id if employee is not None else None,
            processing_status=status, rejection_reason=reason,
        ))
        self.db.commit()

    def _fail(self, chat_id: str, callback_query_id: str | None, what: str, reason: str) -> None:
        self._answer(callback_query_id, f"Couldn't {what}")
        self._reply(chat_id, f"<b>Couldn't {_e(what)}</b>\n\n{_e(reason)}")

    def _answer(self, callback_query_id: str | None, text: str) -> None:
        if callback_query_id:
            self.provider.answer_callback_query(callback_query_id, text)

    def _reply(self, chat_id: str, html_text: str) -> None:
        self.provider.send_text(chat_id, html_text, parse_mode="HTML")
