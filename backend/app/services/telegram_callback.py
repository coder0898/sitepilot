"""Inline-button presses and typed answers for External Approval Gate messages.

A button is a second way to send a typed GATE* command, nothing more: its
callback data (`g1:<code>:<gate id>[:<arg>]`, see `telegram_message.py`) is
translated into the exact command text a user could type, and that text runs
through `TelegramInboundService.process` - the same identity matching,
duplicate-delivery protection, assignee/Admin checks and shared gate services
(acknowledgement, status check, evidence session, decision) as a typed
command. No gate rule lives in this module.

Two buttons first ask a question (gate plan chunk 3), stored as a
`TelegramPendingInput` (`telegram_pending_input.py`):
- Reject asks the Admin for a reason; their next text message becomes
  `GATEDECIDE <ref> REJECT <reason>`. [Cancel] withdraws the question.
- A health button (On Track / Blocked / Need Help) asks for an optional
  note; the next text message becomes `GATESTATUS <ref> <health> <note>`,
  or [Skip note] sends `GATESTATUS <ref> <health>` with no note.
The pending question captures the next text message before it can be read
as a command or evidence text (`handle_text`).

Evidence session buttons (gate plan chunk 4): [Cancel Evidence Session] runs
GATECANCEL; [Add More Evidence] runs nothing - it only acknowledges, since
the next photo/PDF/note is added anyway.

Feedback, so nothing fails silently:
- the button's loading spinner is always answered with a short toast;
- on success the pressed message's buttons are removed, so the completed
  action can't be pressed again from that message; the follow-up message is
  the normal outbox notification for the action;
- a second press of the same button on the same message, after it already
  succeeded, is answered "Already done" without running the command again;
- any rejection (wrong person, gate no longer in that state, unlinked chat,
  stale/unknown button, expired or already-answered question) is sent back
  as a readable message.
"""

from __future__ import annotations

import html
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import InboundMessage, ProjectExternalApproval, TelegramInboundUpdate
from app.project_models import V2ProjectExternalGate
from app.services.telegram_gate_render import HEALTH_LABELS
from app.services.telegram_inbound import TelegramInboundService
from app.services.telegram_message import GateCallback, gate_callback, parse_gate_callback
from app.services.telegram_pending_input import (
    KIND_HEALTH_NOTE,
    KIND_REJECT_REASON,
    PENDING_INPUT_TTL,
    close_add_progress_mode,
    is_task_question,
    peek_pending,
    set_pending,
    take_pending,
)
from app.services.telegram_provider import TelegramProviderAdapter
from app.services.telegram_task_callback import TelegramTaskCallbackService


@dataclass(frozen=True)
class _ButtonAction:
    what: str  # completes "Couldn't ..." in a rejection message
    done_toast: str
    needs_gate: bool = True
    needs_arg: bool = False


_BUTTON_ACTIONS = {
    "ac": _ButtonAction("acknowledge this approval", "Acknowledged"),
    "dc": _ButtonAction("decline this approval", "Decline recorded"),
    "hs": _ButtonAction("update the status", "Add a note or skip", needs_arg=True),
    "sk": _ButtonAction("update the status", "Status updated"),
    "op": _ButtonAction("start an evidence submission", "Evidence submission started"),
    "cl": _ButtonAction("submit for review", "Submitted for review", needs_gate=False),
    "ap": _ButtonAction("approve this approval", "Approved"),
    "rj": _ButtonAction("reject this approval", "Reason needed"),
    "cn": _ButtonAction("cancel the rejection", "Cancelled"),
    "cx": _ButtonAction("cancel the evidence session", "Evidence session cancelled", needs_gate=False),
    # Nothing to run: the next photo/PDF/note is simply added.
    "ad": _ButtonAction("add more evidence", "Send your next photo, PDF or note", needs_gate=False),
}

_UNLINKED = "This Telegram account isn't linked to SiteOps. Ask your Admin for a new connect link."
_STALE = "This button is no longer available."
_NOT_PENDING = "This question has expired or was already answered."
_MINUTES = int(PENDING_INPUT_TTL.total_seconds() // 60)


def _e(value: object) -> str:
    return html.escape(str(value), quote=False)


def _command_for(callback: GateCallback) -> str | None:
    """The exact typed command this button stands for (for the question
    buttons, the command the question will complete), or None if the
    callback is incomplete for its action."""
    action = _BUTTON_ACTIONS.get(callback.code)
    if action is None or (action.needs_gate and not callback.ref) or (action.needs_arg and not callback.arg):
        return None
    ref = callback.ref
    return {
        "ac": f"GATEACCEPT {ref}",
        "dc": f"GATEDECLINE {ref}",
        "hs": f"GATESTATUS {ref} {callback.arg}",
        "sk": f"GATESTATUS {ref}",
        "op": f"GATEOPEN {ref}",
        "cl": "GATECLOSE",
        "ap": f"GATEDECIDE {ref} APPROVE",
        "rj": f"GATEDECIDE {ref} REJECT",
        "cn": f"GATEDECIDE {ref} REJECT",
        "cx": "GATECANCEL",
        "ad": "",
    }[callback.code]


class TelegramCallbackService:
    def __init__(self, db: Session, provider: TelegramProviderAdapter | None = None):
        self.db = db
        self.provider = provider or TelegramProviderAdapter()

    # ---- button presses ---------------------------------------------------------

    def handle(
        self,
        *,
        update_id: int,
        chat_id: str,
        message_id: int | None,
        callback_query_id: str | None,
        data: str | None,
    ) -> bool:
        """Handles one button press. Returns True when an action ran
        successfully, so the caller can deliver its follow-up promptly."""
        callback = parse_gate_callback(data)
        command = _command_for(callback) if callback else None
        if command is None:
            self._answer(callback_query_id, _STALE)
            self._reply(chat_id, _e(_STALE))
            return False

        if callback.code == "ad":
            self._answer(callback_query_id, _BUTTON_ACTIONS["ad"].done_toast)
            return False
        if callback.code == "rj":
            self._ask_reject_reason(chat_id, callback_query_id, callback)
            return False
        if callback.code == "hs":
            self._ask_health_note(chat_id, callback_query_id, callback)
            return False
        if callback.code in ("sk", "cn"):
            return self._answer_question_button(update_id, chat_id, message_id, callback_query_id, callback)

        if message_id is not None and self._already_done(update_id, chat_id, message_id, data):
            self._answer(callback_query_id, "Already done")
            self.provider.remove_buttons(chat_id, message_id)
            return False

        if callback.code == "op" and close_add_progress_mode(self.db, chat_id):
            # Opening a gate evidence session closes Add Progress mode, so the
            # next photo goes to the gate, not to the task (KTD8).
            self.db.commit()

        return self._run(update_id, chat_id, command, _BUTTON_ACTIONS[callback.code], callback_query_id, message_id)

    # ---- typed answers ----------------------------------------------------------

    def handle_text(
        self, *, update_id: int, chat_id: str, text: str, chat_type: str | None = None,
    ) -> tuple[bool, bool]:
        """Offers a text message to this chat's pending question first.
        Returns (handled, acted): `handled` False means there was no question
        and the message should be processed as a normal command/evidence
        text; `acted` True means an action ran successfully."""
        # An open Add Progress mode (Telegram task plan U7) takes the message
        # as a progress note without being consumed - unless it is a command.
        handled, acted = TelegramTaskCallbackService(self.db, self.provider).handle_progress_text(
            update_id=update_id, chat_id=chat_id, chat_type=chat_type, text=text,
        )
        if handled:
            return True, acted

        taken = take_pending(self.db, chat_id)
        if taken is None:
            return False, False
        self.db.commit()
        pending = taken.pending
        if is_task_question(pending):
            # A question about an internal task (Telegram task plan U6+).
            acted = TelegramTaskCallbackService(self.db, self.provider).handle_answer(
                update_id=update_id, chat_id=chat_id, chat_type=chat_type, text=text, taken=taken,
            )
            return True, acted
        if pending.prompt_message_id is not None:
            self.provider.remove_buttons(chat_id, pending.prompt_message_id)

        if taken.expired:
            again = "Tap Reject again" if pending.kind == KIND_REJECT_REASON else "Tap the status again"
            self._reply(
                chat_id,
                f"<b>This question has expired</b>\n\nYour message was not used. {again} to start over.",
            )
            return True, False

        ref = pending.approval_id.hex[:8]
        answer = " ".join(text.split())  # one line: the command grammar is whitespace-separated
        if pending.kind == KIND_REJECT_REASON:
            command = f"GATEDECIDE {ref} REJECT {answer}"
            action = _BUTTON_ACTIONS["rj"]
        else:
            command = f"GATESTATUS {ref} {pending.health} {answer}"
            action = _BUTTON_ACTIONS["hs"]
        return True, self._run(update_id, chat_id, command, action, callback_query_id=None, message_id=None)

    # ---- questions ----------------------------------------------------------------

    def _gate_for_question(self, chat_id: str, callback_query_id: str | None, callback: GateCallback, what: str):
        """Read-only lookups needed to phrase a question: the chat must be
        linked and the gate must exist. Every permission/state rule is still
        enforced by the GATE* command the answer completes."""
        if not TelegramInboundService(self.db)._match_employees_by_chat_id(chat_id):
            self._fail(chat_id, callback_query_id, what, _UNLINKED)
            return None, None
        approval = self.db.get(ProjectExternalApproval, uuid.UUID(callback.approval_hex))
        if approval is None:
            self._answer(callback_query_id, _STALE)
            self._reply(chat_id, _e(_STALE))
            return None, None
        gate = self.db.get(V2ProjectExternalGate, approval.project_gate_id)
        return approval, (gate.approval_name if gate else "this approval")

    def _ask_reject_reason(self, chat_id: str, callback_query_id: str | None, callback: GateCallback) -> None:
        approval, gate_name = self._gate_for_question(chat_id, callback_query_id, callback, "reject this approval")
        if approval is None:
            return
        if approval.status != "submitted":
            self._fail(
                chat_id, callback_query_id, "reject this approval",
                f"{gate_name} is no longer awaiting a decision (current status: {approval.status}).",
            )
            return
        pending = set_pending(self.db, chat_id=chat_id, kind=KIND_REJECT_REASON, approval_id=approval.id)
        self._answer(callback_query_id, "Reason needed")
        pending.prompt_message_id = self._ask(
            chat_id,
            f"<b>Reject {_e(gate_name)}</b>\n\nPlease enter the rejection reason for {_e(gate_name)}.\n"
            f"Send it as your next message within {_MINUTES} minutes.",
            [[{"text": "Cancel", "callback_data": gate_callback("cn", approval.id)}]],
        )
        self.db.commit()

    def _ask_health_note(self, chat_id: str, callback_query_id: str | None, callback: GateCallback) -> None:
        approval, gate_name = self._gate_for_question(chat_id, callback_query_id, callback, "update the status")
        if approval is None:
            return
        health_label = HEALTH_LABELS.get(callback.arg, callback.arg)
        pending = set_pending(
            self.db, chat_id=chat_id, kind=KIND_HEALTH_NOTE, approval_id=approval.id, health=callback.arg,
        )
        self._answer(callback_query_id, "Add a note or skip")
        pending.prompt_message_id = self._ask(
            chat_id,
            f"<b>Status: {_e(health_label)}</b>\n\nApproval: {_e(gate_name)}\n\n"
            f"Add a short note? Send it as your next message within {_MINUTES} minutes, or tap Skip note.\n\n"
            "Example: Application submitted to Fire Department. Awaiting inspection date.",
            [[{"text": "Skip note", "callback_data": gate_callback("sk", approval.id)}]],
        )
        self.db.commit()

    def _answer_question_button(
        self, update_id: int, chat_id: str, message_id: int | None, callback_query_id: str | None, callback: GateCallback,
    ) -> bool:
        """[Skip note] or [Cancel] on a question message."""
        expected_kind = KIND_HEALTH_NOTE if callback.code == "sk" else KIND_REJECT_REASON
        action = _BUTTON_ACTIONS[callback.code]
        pending = peek_pending(self.db, chat_id)
        if (
            pending is None or pending.kind != expected_kind or pending.approval_id is None
            or pending.approval_id.hex != callback.approval_hex
        ):
            self._fail(chat_id, callback_query_id, action.what, _NOT_PENDING)
            if message_id is not None:
                self.provider.remove_buttons(chat_id, message_id)
            return False

        taken = take_pending(self.db, chat_id)
        self.db.commit()
        if message_id is not None:
            self.provider.remove_buttons(chat_id, message_id)
        if taken is None or taken.expired:
            self._fail(chat_id, callback_query_id, action.what, "This question has expired. Start again from the approval message.")
            return False

        if callback.code == "cn":
            self._answer(callback_query_id, "Cancelled")
            self._reply(chat_id, "<b>Rejection cancelled</b>\n\nThe approval is still awaiting your decision.")
            return False
        command = f"GATESTATUS {callback.ref} {taken.pending.health}"
        return self._run(update_id, chat_id, command, action, callback_query_id, message_id=None)

    # ---- shared -----------------------------------------------------------------------

    def _run(
        self, update_id: int, chat_id: str, command: str, action: _ButtonAction,
        callback_query_id: str | None, message_id: int | None,
    ) -> bool:
        outcome = TelegramInboundService(self.db).process(update_id, chat_id, command)
        if outcome.processing_status == "processed":
            self._answer(callback_query_id, action.done_toast)
            if message_id is not None:
                self.provider.remove_buttons(chat_id, message_id)
            return True
        reason = _UNLINKED if outcome.processing_status == "unmatched" else (outcome.rejection_reason or "Unknown reason.")
        self._fail(chat_id, callback_query_id, action.what, reason)
        return False

    def _already_done(self, update_id: int, chat_id: str, message_id: int, data: str) -> bool:
        """Whether this same button on this same message already ran
        successfully (an earlier update, same chat/message/callback data)."""
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
