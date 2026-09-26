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
from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import InboundMessage, Task, TaskProgressUpdate, TelegramInboundUpdate
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.services.inbound_message import EMPLOYEE_COMMANDS, VENDOR_COMMANDS
from app.services.task_lifecycle import EarlyStartReasonRequired, TaskLifecycleService
from app.services.task_progress import ALLOWED_EVIDENCE_MIME_TYPES, MAX_EVIDENCE_SIZE_BYTES, TaskProgressService
from app.services.task_approval import TaskApprovalService
from app.services.task_verification import TaskVerificationService
from app.services.telegram_message import parse_task_callback, task_callback
from app.services.telegram_pending_input import (
    ADD_PROGRESS_TTL,
    KIND_TASK_ADD_PROGRESS,
    KIND_TASK_EARLY_START_REASON,
    KIND_TASK_APPROVAL_REJECT_REASON,
    KIND_TASK_VERIFY_REJECT_REASON,
    PENDING_INPUT_TTL,
    TakenInput,
    close_add_progress_mode,
    open_add_progress_mode,
    peek_pending,
    set_pending,
    take_pending,
)
from app.services.telegram_provider import TelegramProviderAdapter
from app.services.telegram_task_render import current_approval_token, current_submission_token
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
    "sb": _TaskButton("Submit for Review", "submit this task for review", "Submitted for review", "submitted"),
}

# The lifecycle's submission refusals, in plain words for Telegram (U8). Any
# other refusal is shown as the service wrote it.
_SUBMIT_EXPLANATIONS = {
    "Log a new progress update": "Add new progress before submitting. Tap Add Progress and send a note, photo or PDF.",
    "This task requires evidence": "This task needs a photo or PDF. Add one with Add Progress, then submit.",
}


def _explain(button: "_TaskButton", detail: str) -> str:
    if button.target_status == "submitted":
        for start, plain in _SUBMIT_EXPLANATIONS.items():
            if detail.startswith(start):
                return plain
    return detail

# [Cancel] under the early-start question (U6).
CANCEL_EARLY_START = "ce"
# [Add Progress] opens the Add Progress mode for a task; [Done] closes it (U7).
ADD_PROGRESS = "ap"
DONE_ADDING = "dn"
# Supervisor review of one submission (U9). Each carries that submission's
# token (KTD19): `t1:<code>:<task>:<token>`.
VERIFY = "vf"
REJECT_VERIFICATION = "vr"
CANCEL_REJECT_VERIFICATION = "vc"
# PM approval (U10): class_a work after verification, approval-gate tasks
# after submission. Same `t1:<code>:<task>:<token>` shape.
APPROVE = "pa"
REJECT_APPROVAL = "pr"
CANCEL_REJECT_APPROVAL = "pc"
OLDER_SUBMISSION = "This review is for an older submission - open the latest review message."

# A text starting with one of these closes Add Progress mode and runs as the
# command it is, never becoming a progress note (KTD8).
_COMMAND_KEYWORDS = frozenset(EMPLOYEE_COMMANDS | VENDOR_COMMANDS)

_PROGRESS_TYPE_OR_SIZE = (
    "This file type or size isn't supported. Please send a photo (JPG, PNG, WebP) or a PDF "
    "of up to 10 MB, or use the Web App."
)
_PROGRESS_DOWNLOAD_FAILED = "The file couldn't be downloaded from Telegram. Please send it again."
_ADD_PROGRESS_MINUTES = int(ADD_PROGRESS_TTL.total_seconds() // 60)

UNLINKED = "This Telegram account isn't linked to SiteOps. Ask your Admin for a new connect link."
STALE = "This button is no longer available."
PRIVATE_ONLY = "Use the bot in a private chat to act on tasks."
NOT_A_MEMBER = "You are no longer a member of this task's project."
NOT_PENDING = "This question has expired or was already answered."
_MINUTES = int(PENDING_INPUT_TTL.total_seconds() // 60)


def _e(value: object) -> str:
    return html.escape(str(value), quote=False)


def _format_date(value: date) -> str:
    return value.strftime("%d %b %Y").lstrip("0")


def _shorten(text: str, limit: int = 60) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= limit else one_line[: limit - 1] + "…"


# Audit label for Add Progress presses and items (not a lifecycle transition).
_ADD_PROGRESS_BUTTON = _TaskButton("Add Progress", "add progress", "Send your progress", "in_progress")
# Labels for the review decisions (U9); the decision itself is the service's.
_VERIFY_BUTTON = _TaskButton("Verify", "verify this task", "Verified", "verified")
_REJECT_BUTTON = _TaskButton("Reject", "reject this task", "Rejected", "rejected")
_APPROVE_BUTTON = _TaskButton("Approve", "approve this task", "Approved", "completed")
_REJECT_APPROVAL_BUTTON = _TaskButton("PM Reject", "reject this task", "Rejected", "rejected")


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
        if callback is not None and callback.code == CANCEL_EARLY_START:
            return self._cancel_early_start(chat_id, chat_type, from_id, message_id, callback_query_id, callback.task_id)
        if callback is not None and callback.code == ADD_PROGRESS:
            return self._open_add_progress(update_id, chat_id, chat_type, from_id, callback_query_id, callback.task_id)
        if callback is not None and callback.code == DONE_ADDING:
            return self._done_adding(chat_id, chat_type, from_id, message_id, callback_query_id, callback.task_id)
        if callback is not None and callback.code in (VERIFY, REJECT_VERIFICATION, CANCEL_REJECT_VERIFICATION):
            return self._review_button(update_id, chat_id, chat_type, from_id, message_id, callback_query_id, callback, data)
        if callback is not None and callback.code in (APPROVE, REJECT_APPROVAL, CANCEL_REJECT_APPROVAL):
            return self._approval_button(update_id, chat_id, chat_type, from_id, message_id, callback_query_id, callback, data)
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
        except EarlyStartReasonRequired as exc:
            # The lifecycle's own early-start rule (KTD9): nothing changed; ask
            # for the reason and start the task only once it is given.
            self.db.rollback()
            self._record(update_id, chat_id, button, employee, "rejected", "Asked for an early-start reason.", task)
            self._ask_early_start_reason(chat_id, callback_query_id, task, exc.planned_start_date)
            return False
        except HTTPException as exc:
            self.db.rollback()
            reason = str(exc.detail)
            self._record(update_id, chat_id, button, employee, "rejected", reason, task)
            self._fail(chat_id, callback_query_id, button.what, _explain(button, reason))
            return False

        if button.target_status == "submitted" and close_add_progress_mode(self.db, chat_id):
            self.db.commit()  # submitting ends Add Progress for this chat (KTD8)
        self._record(update_id, chat_id, button, employee, "processed", None, task)
        self._answer(callback_query_id, button.done_toast)
        if message_id is not None:
            self.provider.remove_buttons(chat_id, message_id)
        return True

    # ---- early-start reason (U6) --------------------------------------------------------

    def _ask_early_start_reason(self, chat_id: str, callback_query_id: str | None, task: Task, planned_start: date) -> None:
        pending = set_pending(self.db, chat_id=chat_id, kind=KIND_TASK_EARLY_START_REASON, task_id=task.id)
        self._answer(callback_query_id, "Reason needed")
        pending.prompt_message_id = self._ask(
            chat_id,
            f"<b>Start Early: {_e(task.original_code)} - {_e(task.title)}</b>\n\n"
            f"This task is planned to start on {_e(_format_date(planned_start))}.\n\n"
            "Please provide the reason for starting this task early.\n"
            f"Send it as your next message within {_MINUTES} minutes.",
            [[{"text": "Cancel", "callback_data": task_callback(CANCEL_EARLY_START, task.id)}]],
        )
        self.db.commit()

    def _cancel_early_start(
        self, chat_id: str, chat_type: str | None, from_id: str | None, message_id: int | None,
        callback_query_id: str | None, task_id,
    ) -> bool:
        what = "cancel the early start"
        if chat_type != "private" or from_id != chat_id:
            self._fail(chat_id, callback_query_id, what, PRIVATE_ONLY)
            return False
        pending = peek_pending(self.db, chat_id)
        if message_id is not None:
            self.provider.remove_buttons(chat_id, message_id)
        if pending is None or pending.kind != KIND_TASK_EARLY_START_REASON or pending.task_id != task_id:
            self._fail(chat_id, callback_query_id, what, NOT_PENDING)
            return False
        take_pending(self.db, chat_id)
        self.db.commit()
        self._answer(callback_query_id, "Cancelled")
        self._reply(chat_id, "<b>Early start cancelled</b>\n\nThe task was not started.")
        return False

    def handle_answer(
        self, *, update_id: int, chat_id: str, chat_type: str | None, text: str, taken: TakenInput,
    ) -> bool:
        """The next text message after a task question (the question has
        already been taken off the chat). Returns True when an action ran."""
        pending = taken.pending
        if pending.prompt_message_id is not None:
            self.provider.remove_buttons(chat_id, pending.prompt_message_id)
        if chat_type is not None and chat_type != "private":
            self._reply(chat_id, _e(PRIVATE_ONLY))
            return False
        again = {
            KIND_TASK_EARLY_START_REASON: "Tap Start Task again",
            KIND_TASK_VERIFY_REJECT_REASON: "Tap Reject on the review message again",
            KIND_TASK_APPROVAL_REJECT_REASON: "Tap Reject on the approval message again",
        }.get(pending.kind, "Start again from the task message")
        if taken.expired:
            self._reply(
                chat_id,
                f"<b>This question has expired</b>\n\nYour message was not used. {again} to start over.",
            )
            return False
        answer = " ".join(text.split())
        if pending.kind == KIND_TASK_VERIFY_REJECT_REASON:
            return self._decide_verification(
                update_id, chat_id, None, None, pending.task_id, pending.review_token, "rejected", answer,
            )
        if pending.kind == KIND_TASK_APPROVAL_REJECT_REASON:
            return self._decide_approval(
                update_id, chat_id, None, None, pending.task_id, pending.review_token, "rejected", answer,
            )
        return self._start_early(update_id, chat_id, pending.task_id, answer)

    def _start_early(self, update_id: int, chat_id: str, task_id, reason: str) -> bool:
        button = TASK_BUTTONS["st"]
        identity = self._linked_person(chat_id)
        if identity is None:
            self._record(update_id, chat_id, button, None, "unmatched", UNLINKED)
            self._reply(chat_id, f"<b>Couldn't {_e(button.what)}</b>\n\n{_e(UNLINKED)}")
            return False
        user, employee = identity
        task = self.db.get(Task, task_id)
        if task is None or not self._may_act_on_project(user, employee, task):
            reason_text = STALE if task is None else NOT_A_MEMBER
            self._record(update_id, chat_id, button, employee, "rejected", reason_text, task)
            self._reply(chat_id, f"<b>Couldn't {_e(button.what)}</b>\n\n{_e(reason_text)}")
            return False
        body = f"[reply] Early-start reason for {task.original_code}: {reason}"
        try:
            TaskLifecycleService(self.db).transition(
                task.project_id, task.id, "in_progress", user, reason=reason, source="telegram",
            )
        except HTTPException as exc:
            self.db.rollback()
            self._record(update_id, chat_id, button, employee, "rejected", str(exc.detail), task, body=body)
            self._reply(chat_id, f"<b>Couldn't {_e(button.what)}</b>\n\n{_e(exc.detail)}")
            return False
        self._record(update_id, chat_id, button, employee, "processed", None, task, body=body)
        return True

    # ---- Add Progress (U7) ----------------------------------------------------------------

    def _open_add_progress(
        self, update_id: int, chat_id: str, chat_type: str | None, from_id: str | None,
        callback_query_id: str | None, task_id,
    ) -> bool:
        what = "add progress"
        if chat_type != "private" or from_id != chat_id:
            self._fail(chat_id, callback_query_id, what, PRIVATE_ONLY)
            return False
        checked = self._person_and_task(chat_id, task_id)
        if isinstance(checked, str):
            self._fail(chat_id, callback_query_id, what, checked)
            return False
        user, employee, task = checked
        refusal = self._progress_refusal(user, task)
        if refusal:
            self._fail(chat_id, callback_query_id, what, refusal)
            return False

        set_pending(self.db, chat_id=chat_id, kind=KIND_TASK_ADD_PROGRESS, task_id=task.id, ttl=ADD_PROGRESS_TTL)
        self.db.commit()
        self._record(update_id, chat_id, _ADD_PROGRESS_BUTTON, employee, "processed", None, task)
        self._answer(callback_query_id, "Send your progress")
        self._ask(
            chat_id,
            f"<b>Add Progress: {_e(task.original_code)} - {_e(task.title)}</b>\n\n"
            "Send a note, a photo or a PDF. Each message is saved as one progress update; "
            "a caption is saved as the note of its photo or PDF.\n\n"
            f"This closes after {_ADD_PROGRESS_MINUTES} minutes without a message, or when you tap Done.",
            self._progress_buttons(task),
        )
        return False

    def _done_adding(
        self, chat_id: str, chat_type: str | None, from_id: str | None, message_id: int | None,
        callback_query_id: str | None, task_id,
    ) -> bool:
        if chat_type != "private" or from_id != chat_id:
            self._fail(chat_id, callback_query_id, "close Add Progress", PRIVATE_ONLY)
            return False
        pending = open_add_progress_mode(self.db, chat_id)
        if message_id is not None:
            self.provider.remove_buttons(chat_id, message_id)
        if pending is None or pending.task_id != task_id:
            self.db.commit()
            self._answer(callback_query_id, "Already closed")
            return False
        close_add_progress_mode(self.db, chat_id)
        self.db.commit()
        self._answer(callback_query_id, "Done")
        self._reply(chat_id, "<b>Add Progress closed</b>\n\nYour progress updates are saved.")
        return False

    def handle_progress_text(
        self, *, update_id: int, chat_id: str, chat_type: str | None, text: str,
    ) -> tuple[bool, bool]:
        """A text message while Add Progress mode may be open. Returns
        (handled, acted): not handled means it is not a progress note (no open
        mode, or a command) and goes on to normal processing."""
        pending = open_add_progress_mode(self.db, chat_id)
        if pending is None:
            self.db.commit()  # an expired mode was dropped
            return False, False
        if chat_type is not None and chat_type != "private":
            return False, False
        keyword = text.split()[0].upper() if text.split() else ""
        if keyword in _COMMAND_KEYWORDS:
            close_add_progress_mode(self.db, chat_id)
            self.db.commit()
            return False, False
        acted = self._store_progress(update_id, chat_id, pending, note=text, received=f'Note: "{_shorten(text)}"')
        return True, acted

    def handle_progress_media(self, *, update_id: int, chat_id: str, chat_type: str | None, media: dict) -> tuple[bool, bool]:
        """A photo or document while Add Progress mode may be open. Returns
        (handled, acted); not handled goes on to the gate evidence path."""
        pending = open_add_progress_mode(self.db, chat_id)
        if pending is None:
            self.db.commit()
            return False, False
        if chat_type is not None and chat_type != "private":
            return False, False
        mime_type = media.get("mime_type")
        declared = media.get("file_size")
        if mime_type not in ALLOWED_EVIDENCE_MIME_TYPES or (isinstance(declared, int) and declared > MAX_EVIDENCE_SIZE_BYTES):
            # Refused before any download.
            self._reply(chat_id, f"<b>Couldn't add this progress</b>\n\n{_e(_PROGRESS_TYPE_OR_SIZE)}")
            return True, False
        download = self.provider.download_file(media.get("id"), max_bytes=MAX_EVIDENCE_SIZE_BYTES)
        if not download.ok:
            reason = _PROGRESS_TYPE_OR_SIZE if download.failure_code == "too_large" else _PROGRESS_DOWNLOAD_FAILED
            self._reply(chat_id, f"<b>Couldn't add this progress</b>\n\n{_e(reason)}")
            return True, False
        is_photo = media.get("kind") == "photo"
        filename = media.get("filename") or ("photo.jpg" if is_photo else "document")
        caption = (media.get("caption") or "").strip() or None
        label = "Photo" if is_photo else filename
        acted = self._store_progress(
            update_id, chat_id, pending, note=caption,
            received=f"{label} (with caption)" if caption else label,
            evidence=(download.bytes, filename, mime_type),
        )
        return True, acted

    def _store_progress(
        self, update_id: int, chat_id: str, pending, *, note: str | None, received: str,
        evidence: tuple[bytes, str, str] | None = None,
    ) -> bool:
        """One Telegram item = one normal progress update (KTD5), through the
        same service the Web App uses."""
        what = "add this progress"
        if self.db.scalar(select(InboundMessage.id).where(InboundMessage.provider_message_id == str(update_id))):
            return False  # this Telegram update was already handled - never store it twice
        checked = self._person_and_task(chat_id, pending.task_id)
        if isinstance(checked, str):
            close_add_progress_mode(self.db, chat_id)
            self.db.commit()
            self._reply(chat_id, f"<b>Couldn't {what}</b>\n\n{_e(checked)}")
            return False
        user, employee, task = checked
        body = f"[progress] {task.original_code}: {received}"
        try:
            TaskProgressService(self.db).submit_progress(
                task.project_id, task.id, user, note=note,
                evidence_bytes=evidence[0] if evidence else None,
                evidence_filename=evidence[1] if evidence else None,
                evidence_content_type=evidence[2] if evidence else None,
                source="telegram",
            )
        except HTTPException as exc:
            self.db.rollback()
            # e.g. the task was submitted or reassigned meanwhile: nothing more
            # can be added, so the mode closes.
            close_add_progress_mode(self.db, chat_id)
            self.db.commit()
            self._record(update_id, chat_id, _ADD_PROGRESS_BUTTON, employee, "rejected", str(exc.detail), task, body=body)
            self._reply(chat_id, f"<b>Couldn't {what}</b>\n\n{_e(exc.detail)}")
            return False

        mode = open_add_progress_mode(self.db, chat_id)
        if mode is not None:
            mode.expires_at = datetime.now(timezone.utc) + ADD_PROGRESS_TTL  # slides from the last item
        self.db.commit()
        self._record(update_id, chat_id, _ADD_PROGRESS_BUTTON, employee, "processed", None, task, body=body)
        self._ask(
            chat_id,
            f"<b>Progress Added</b>\n\nTask: {_e(task.original_code)} - {_e(task.title)}\n"
            f"Received: {_e(received)}\n\nSend more, tap Submit for Review when the work is complete, or tap Done.",
            self._progress_buttons(task),
        )
        return True

    def _progress_buttons(self, task: Task) -> list[list[dict]]:
        """[Submit for Review] [Done] under the Add Progress prompt and each
        Progress Added reply (U8)."""
        return [[
            {"text": "Submit for Review", "callback_data": task_callback("sb", task.id)},
            {"text": "Done", "callback_data": task_callback(DONE_ADDING, task.id)},
        ]]

    def _progress_refusal(self, user: User, task: Task) -> str | None:
        """Why this person can't log progress on this task right now, in the
        progress service's own words - checked when the mode opens so the
        refusal comes before anything is sent. Each item is still checked
        again by `submit_progress` itself."""
        if task.lifecycle_status != "in_progress":
            return f"Progress can only be logged while the task is in progress (it is currently {task.lifecycle_status})."
        service = TaskProgressService(self.db)
        try:
            service._require_progress_actor(self.db.get(V2Project, task.project_id), task, user)
        except HTTPException as exc:
            return str(exc.detail)
        return None

    # ---- Supervisor review (U9) ----------------------------------------------------------

    def current_submission_token(self, task: Task) -> str | None:
        """The same token the review message carried (shared with the
        renderer, so the two can never disagree)."""
        return current_submission_token(self.db, task)

    def _review_refusal(self, task: Task, token: str | None) -> str | None:
        """KTD19: the button (or the reason question it opened) must belong
        to the submission currently waiting; the verification service still
        enforces every other rule."""
        if task.lifecycle_status != "submitted":
            return f"This task is no longer awaiting verification (current status: {task.lifecycle_status})."
        if not token or token != self.current_submission_token(task):
            return OLDER_SUBMISSION
        return None

    def _review_button(
        self, update_id: int, chat_id: str, chat_type: str | None, from_id: str | None, message_id: int | None,
        callback_query_id: str | None, callback, data: str | None,
    ) -> bool:
        code, token = callback.code, callback.arg
        what = {
            VERIFY: "verify this task", REJECT_VERIFICATION: "reject this task",
            CANCEL_REJECT_VERIFICATION: "cancel the rejection",
        }[code]
        if chat_type != "private" or from_id != chat_id:
            self._fail(chat_id, callback_query_id, what, PRIVATE_ONLY)
            return False

        if code == CANCEL_REJECT_VERIFICATION:
            pending = peek_pending(self.db, chat_id)
            if message_id is not None:
                self.provider.remove_buttons(chat_id, message_id)
            if (
                pending is None or pending.kind != KIND_TASK_VERIFY_REJECT_REASON
                or pending.task_id != callback.task_id or pending.review_token != token
            ):
                self._fail(chat_id, callback_query_id, what, NOT_PENDING)
                return False
            take_pending(self.db, chat_id)
            self.db.commit()
            self._answer(callback_query_id, "Cancelled")
            self._reply(chat_id, "<b>Rejection cancelled</b>\n\nThe task is still awaiting verification.")
            return False

        if code == VERIFY and message_id is not None and self._already_done(update_id, chat_id, message_id, data):
            self._answer(callback_query_id, "Already done")
            self.provider.remove_buttons(chat_id, message_id)
            return False

        checked = self._person_and_task(chat_id, callback.task_id)
        if isinstance(checked, str):
            self._fail(chat_id, callback_query_id, what, checked)
            return False
        _, _, task = checked
        refusal = self._review_refusal(task, token)
        if refusal:
            self._fail(chat_id, callback_query_id, what, refusal)
            if message_id is not None:
                self.provider.remove_buttons(chat_id, message_id)
            return False

        if code == REJECT_VERIFICATION:
            pending = set_pending(
                self.db, chat_id=chat_id, kind=KIND_TASK_VERIFY_REJECT_REASON, task_id=task.id, review_token=token,
            )
            self._answer(callback_query_id, "Reason needed")
            pending.prompt_message_id = self._ask(
                chat_id,
                f"<b>Reject {_e(task.original_code)} - {_e(task.title)}</b>\n\n"
                "Please enter the reason for rejecting this work. It is sent to the person who did it.\n"
                f"Send it as your next message within {_MINUTES} minutes.",
                [[{"text": "Cancel", "callback_data": task_callback(CANCEL_REJECT_VERIFICATION, task.id, token)}]],
            )
            self.db.commit()
            return False

        return self._decide_verification(update_id, chat_id, message_id, callback_query_id, task.id, token, "verified", None)

    def _decide_verification(
        self, update_id: int, chat_id: str, message_id: int | None, callback_query_id: str | None,
        task_id, token: str | None, decision: str, remarks: str | None,
    ) -> bool:
        """Records the decision through TaskVerificationService.verify - the
        same call as the Web App, source "telegram"."""
        button = _VERIFY_BUTTON if decision == "verified" else _REJECT_BUTTON
        checked = self._person_and_task(chat_id, task_id)
        if isinstance(checked, str):
            self._fail(chat_id, callback_query_id, button.what, checked)
            return False
        user, employee, task = checked
        body = f"[{'button' if decision == 'verified' else 'reply'}] {button.label} {task.original_code}" + (
            f": {remarks}" if remarks else ""
        )
        refusal = self._review_refusal(task, token)
        if refusal:
            self._record(update_id, chat_id, button, employee, "rejected", refusal, task, body=body)
            self._fail(chat_id, callback_query_id, button.what, refusal)
            return False
        try:
            TaskVerificationService(self.db).verify(
                task.project_id, task.id, decision, user, remarks=remarks, source="telegram",
            )
        except HTTPException as exc:
            self.db.rollback()
            self._record(update_id, chat_id, button, employee, "rejected", str(exc.detail), task, body=body)
            self._fail(chat_id, callback_query_id, button.what, str(exc.detail))
            return False
        self._record(update_id, chat_id, button, employee, "processed", None, task, body=body)
        self._answer(callback_query_id, button.done_toast)
        if message_id is not None:
            self.provider.remove_buttons(chat_id, message_id)
        return True

    # ---- PM approval (U10) -----------------------------------------------------------------

    def current_approval_token(self, task: Task) -> str | None:
        """What is currently awaiting PM approval (shared with the renderer)."""
        return current_approval_token(self.db, task)

    def _approval_refusal(self, task: Task, token: str | None) -> str | None:
        current = self.current_approval_token(task)
        if current is None:
            return f"This task is no longer awaiting approval (current status: {task.lifecycle_status})."
        if token != current:
            return OLDER_SUBMISSION
        return None

    def _approval_button(
        self, update_id: int, chat_id: str, chat_type: str | None, from_id: str | None, message_id: int | None,
        callback_query_id: str | None, callback, data: str | None,
    ) -> bool:
        code, token = callback.code, callback.arg
        what = {APPROVE: "approve this task", REJECT_APPROVAL: "reject this task", CANCEL_REJECT_APPROVAL: "cancel the rejection"}[code]
        if chat_type != "private" or from_id != chat_id:
            self._fail(chat_id, callback_query_id, what, PRIVATE_ONLY)
            return False

        if code == CANCEL_REJECT_APPROVAL:
            pending = peek_pending(self.db, chat_id)
            if message_id is not None:
                self.provider.remove_buttons(chat_id, message_id)
            if (
                pending is None or pending.kind != KIND_TASK_APPROVAL_REJECT_REASON
                or pending.task_id != callback.task_id or pending.review_token != token
            ):
                self._fail(chat_id, callback_query_id, what, NOT_PENDING)
                return False
            take_pending(self.db, chat_id)
            self.db.commit()
            self._answer(callback_query_id, "Cancelled")
            self._reply(chat_id, "<b>Rejection cancelled</b>\n\nThe task is still awaiting approval.")
            return False

        if code == APPROVE and message_id is not None and self._already_done(update_id, chat_id, message_id, data):
            self._answer(callback_query_id, "Already done")
            self.provider.remove_buttons(chat_id, message_id)
            return False

        checked = self._person_and_task(chat_id, callback.task_id)
        if isinstance(checked, str):
            self._fail(chat_id, callback_query_id, what, checked)
            return False
        _, _, task = checked
        refusal = self._approval_refusal(task, token)
        if refusal:
            self._fail(chat_id, callback_query_id, what, refusal)
            if message_id is not None:
                self.provider.remove_buttons(chat_id, message_id)
            return False

        if code == REJECT_APPROVAL:
            pending = set_pending(
                self.db, chat_id=chat_id, kind=KIND_TASK_APPROVAL_REJECT_REASON, task_id=task.id, review_token=token,
            )
            self._answer(callback_query_id, "Reason needed")
            pending.prompt_message_id = self._ask(
                chat_id,
                f"<b>Reject {_e(task.original_code)} - {_e(task.title)}</b>\n\n"
                "Please enter the reason for rejecting this work. It is sent to the person who did it.\n"
                f"Send it as your next message within {_MINUTES} minutes.",
                [[{"text": "Cancel", "callback_data": task_callback(CANCEL_REJECT_APPROVAL, task.id, token)}]],
            )
            self.db.commit()
            return False

        return self._decide_approval(update_id, chat_id, message_id, callback_query_id, task.id, token, "approved", None)

    def _decide_approval(
        self, update_id: int, chat_id: str, message_id: int | None, callback_query_id: str | None,
        task_id, token: str | None, decision: str, remarks: str | None,
    ) -> bool:
        """Records the decision through TaskApprovalService.approve - the same
        call as the Web App, source "telegram". The approval service still
        refuses the fallback verifier (and every other rule)."""
        button = _APPROVE_BUTTON if decision == "approved" else _REJECT_APPROVAL_BUTTON
        checked = self._person_and_task(chat_id, task_id)
        if isinstance(checked, str):
            self._fail(chat_id, callback_query_id, button.what, checked)
            return False
        user, employee, task = checked
        body = f"[{'button' if decision == 'approved' else 'reply'}] {button.label} {task.original_code}" + (
            f": {remarks}" if remarks else ""
        )
        refusal = self._approval_refusal(task, token)
        if refusal:
            self._record(update_id, chat_id, button, employee, "rejected", refusal, task, body=body)
            self._fail(chat_id, callback_query_id, button.what, refusal)
            return False
        try:
            TaskApprovalService(self.db).approve(
                task.project_id, task.id, decision, user, remarks=remarks, source="telegram",
            )
        except HTTPException as exc:
            self.db.rollback()
            self._record(update_id, chat_id, button, employee, "rejected", str(exc.detail), task, body=body)
            self._fail(chat_id, callback_query_id, button.what, str(exc.detail))
            return False
        self._record(update_id, chat_id, button, employee, "processed", None, task, body=body)
        self._answer(callback_query_id, button.done_toast)
        if message_id is not None:
            self.provider.remove_buttons(chat_id, message_id)
        return True

    def _person_and_task(self, chat_id: str, task_id):
        """(user, employee, task) after the KTD22 guards, or the refusal text."""
        identity = self._linked_person(chat_id)
        if identity is None:
            return UNLINKED
        user, employee = identity
        task = self.db.get(Task, task_id) if task_id else None
        if task is None:
            return STALE
        if not self._may_act_on_project(user, employee, task):
            return NOT_A_MEMBER
        return user, employee, task

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
        status: str, reason: str | None, task: Task | None = None, body: str | None = None,
    ) -> None:
        provider_message_id = str(update_id)
        if self.db.scalar(select(InboundMessage.id).where(InboundMessage.provider_message_id == provider_message_id)):
            return
        body = body or f"[button] {button.label}" + (f" {task.original_code}" if task is not None else "")
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

    def _ask(self, chat_id: str, html_text: str, buttons: list[list[dict]]) -> int | None:
        result = self.provider.send_with_buttons(chat_id, html_text, buttons, parse_mode="HTML")
        return int(result.provider_message_id) if result.ok and result.provider_message_id else None
