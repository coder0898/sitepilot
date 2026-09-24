"""Inline-button presses for External Approval Gate messages.

A button is a second way to send a typed GATE* command, nothing more: its
callback data (`g1:<code>:<gate id>[:<arg>]`, see `telegram_message.py`) is
translated into the exact command text a user could type, and that text runs
through `TelegramInboundService.process` - the same identity matching,
duplicate-delivery protection, assignee/Admin checks and shared gate services
(acknowledgement, status check, evidence session, decision) as a typed
command. No gate rule lives in this module.

The one exception is Reject: a rejection needs a typed reason, and the
reason prompt is a later chunk of the gate plan. Until then the Reject button
changes nothing - it replies with the ready-to-send `GATEDECIDE ... REJECT`
command (or says the gate is no longer awaiting a decision).

What this module adds on top is button feedback, so a press never fails
silently:
- the button's loading spinner is always answered with a short toast;
- on success the pressed message's buttons are removed, so the completed
  action can't be pressed again from that message; the follow-up message is
  the normal outbox notification for the action;
- a second press of the same button on the same message, after it already
  succeeded, is answered "Already done" without running the command again;
- any rejection (wrong person, gate no longer in that state, unlinked chat,
  stale/unknown button) is sent back as a readable message.
"""

from __future__ import annotations

import html
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import InboundMessage, ProjectExternalApproval, TelegramInboundUpdate
from app.project_models import V2ProjectExternalGate
from app.services.telegram_inbound import TelegramInboundService
from app.services.telegram_message import GateCallback, parse_gate_callback
from app.services.telegram_provider import TelegramProviderAdapter


@dataclass(frozen=True)
class _ButtonAction:
    what: str  # completes "Couldn't ..." in a rejection message
    done_toast: str
    needs_gate: bool = True
    needs_arg: bool = False


_BUTTON_ACTIONS = {
    "ac": _ButtonAction("acknowledge this approval", "Acknowledged"),
    "dc": _ButtonAction("decline this approval", "Decline recorded"),
    "hs": _ButtonAction("update the status", "Status updated", needs_arg=True),
    "op": _ButtonAction("start an evidence submission", "Evidence submission started"),
    "cl": _ButtonAction("submit for review", "Submitted for review", needs_gate=False),
    "ap": _ButtonAction("approve this approval", "Approved"),
    "rj": _ButtonAction("reject this approval", "Reason needed"),
}

_UNLINKED = "This Telegram account isn't linked to SiteOps. Ask your Admin for a new connect link."
_STALE = "This button is no longer available."


def _e(value: object) -> str:
    return html.escape(str(value), quote=False)


def _command_for(callback: GateCallback) -> str | None:
    """The exact typed command this button stands for, or None if the
    callback is incomplete for its action."""
    action = _BUTTON_ACTIONS.get(callback.code)
    if action is None or (action.needs_gate and not callback.ref) or (action.needs_arg and not callback.arg):
        return None
    ref = callback.ref
    return {
        "ac": f"GATEACCEPT {ref}",
        "dc": f"GATEDECLINE {ref}",
        "hs": f"GATESTATUS {ref} {callback.arg}",
        "op": f"GATEOPEN {ref}",
        "cl": "GATECLOSE",
        "ap": f"GATEDECIDE {ref} APPROVE",
        "rj": f"GATEDECIDE {ref} REJECT",
    }[callback.code]


class TelegramCallbackService:
    def __init__(self, db: Session, provider: TelegramProviderAdapter | None = None):
        self.db = db
        self.provider = provider or TelegramProviderAdapter()

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

        action = _BUTTON_ACTIONS[callback.code]
        if callback.code == "rj":
            self._reject_instructions(chat_id, callback_query_id, callback, command)
            return False

        if message_id is not None and self._already_done(update_id, chat_id, message_id, data):
            self._answer(callback_query_id, "Already done")
            self.provider.remove_buttons(chat_id, message_id)
            return False

        outcome = TelegramInboundService(self.db).process(update_id, chat_id, command)

        if outcome.processing_status == "processed":
            self._answer(callback_query_id, action.done_toast)
            if message_id is not None:
                self.provider.remove_buttons(chat_id, message_id)
            return True

        reason = _UNLINKED if outcome.processing_status == "unmatched" else (outcome.rejection_reason or "Unknown reason.")
        self._answer(callback_query_id, f"Couldn't {action.what}")
        self._reply(chat_id, f"<b>Couldn't {_e(action.what)}</b>\n\n{_e(reason)}")
        return False

    def _reject_instructions(
        self, chat_id: str, callback_query_id: str | None, callback: GateCallback, command: str,
    ) -> None:
        """Read-only: tells the Admin how to send the rejection with a
        reason. The decision itself (and every permission/state rule) is
        still enforced by GATEDECIDE when they send it."""
        if not TelegramInboundService(self.db)._match_employees_by_chat_id(chat_id):
            self._answer(callback_query_id, "Couldn't reject this approval")
            self._reply(chat_id, f"<b>Couldn't reject this approval</b>\n\n{_e(_UNLINKED)}")
            return
        approval = self.db.get(ProjectExternalApproval, uuid.UUID(callback.approval_hex))
        if approval is None:
            self._answer(callback_query_id, _STALE)
            self._reply(chat_id, _e(_STALE))
            return
        gate = self.db.get(V2ProjectExternalGate, approval.project_gate_id)
        gate_name = gate.approval_name if gate else "this approval"
        if approval.status != "submitted":
            self._answer(callback_query_id, "Not awaiting a decision")
            self._reply(
                chat_id,
                f"<b>Couldn't reject this approval</b>\n\n{_e(gate_name)} is no longer awaiting a decision "
                f"(current status: {_e(approval.status)}).",
            )
            return
        self._answer(callback_query_id, "Reason needed")
        self._reply(
            chat_id,
            f"<b>Reject {_e(gate_name)}</b>\n\nA reason is required. Send this command with your reason:\n\n"
            f"<code>{_e(command)} your reason</code>",
        )

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

    def _answer(self, callback_query_id: str | None, text: str) -> None:
        if callback_query_id:
            self.provider.answer_callback_query(callback_query_id, text)

    def _reply(self, chat_id: str, html_text: str) -> None:
        self.provider.send_text(chat_id, html_text, parse_mode="HTML")
