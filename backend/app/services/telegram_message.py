"""Rendered Telegram message shape shared by the Telegram renderers and dispatch.

`actions` describes what the recipient can do next, as rows of
`TelegramAction`s. Each action carries the exact typed command that performs
it, so the business logic always stays behind the shared command handlers
(`inbound_message.py`) - the renderer only describes the choice. An action
with a `callback` is sent as an inline button; pressing it runs that same
command (see `telegram_callback.py`). An action without one is listed as a
typed command under the message instead.

`attachments` are stored evidence files dispatch sends right after the
message itself (Admin evidence review).
"""

from __future__ import annotations

import html
import re
import uuid
from dataclasses import dataclass, field

# Telegram limits callback_data to 64 bytes. Gate buttons carry the full gate
# id so the user never copies a reference: "g1:<code>:<32 hex>[:<arg>]".
GATE_CALLBACK_PREFIX = "g1"
_GATE_CALLBACK = re.compile(r"^g1:(?P<code>[a-z]{2})(?::(?P<hex>[0-9a-f]{32}))?(?::(?P<arg>[a-z_]{1,20}))?$")


@dataclass(frozen=True)
class TelegramAction:
    label: str
    command: str
    callback: str | None = None


@dataclass(frozen=True)
class GateCallback:
    code: str
    approval_hex: str | None
    arg: str | None

    @property
    def ref(self) -> str | None:
        """The 8-character reference the typed GATE* commands take."""
        return self.approval_hex[:8] if self.approval_hex else None


def gate_callback(code: str, approval_id: object = None, arg: str | None = None) -> str:
    parts = [GATE_CALLBACK_PREFIX, code]
    if approval_id:
        parts.append(uuid.UUID(str(approval_id)).hex)
    if arg:
        parts.append(arg)
    data = ":".join(parts)
    if len(data.encode()) > 64:
        raise ValueError(f"Telegram callback data too long: {data}")
    return data


def parse_gate_callback(data: str | None) -> GateCallback | None:
    match = _GATE_CALLBACK.match(data or "")
    if not match:
        return None
    return GateCallback(code=match["code"], approval_hex=match["hex"], arg=match["arg"])


# Task buttons (Telegram task plan KTD6): "t1:<code>:<32-hex task id>[:<arg>]".
# They carry the task's real id and call the task services directly - never a
# typed STATUS command, since task codes repeat across projects.
TASK_CALLBACK_PREFIX = "t1"
_TASK_CALLBACK = re.compile(r"^t1:(?P<code>[a-z]{2}):(?P<hex>[0-9a-f]{32})(?::(?P<arg>[a-z0-9_]{1,20}))?$")


@dataclass(frozen=True)
class TaskCallback:
    code: str
    task_id: uuid.UUID
    arg: str | None


def task_callback(code: str, task_id: object, arg: str | None = None) -> str:
    parts = [TASK_CALLBACK_PREFIX, code, uuid.UUID(str(task_id)).hex]
    if arg:
        parts.append(arg)
    data = ":".join(parts)
    if len(data.encode()) > 64:
        raise ValueError(f"Telegram callback data too long: {data}")
    return data


def parse_task_callback(data: str | None) -> TaskCallback | None:
    match = _TASK_CALLBACK.match(data or "")
    if not match:
        return None
    return TaskCallback(code=match["code"], task_id=uuid.UUID(hex=match["hex"]), arg=match["arg"])


def is_task_callback(data: str | None) -> bool:
    return (data or "").startswith(f"{TASK_CALLBACK_PREFIX}:")


def submission_token(progress_update_ids) -> str | None:
    """Telegram task plan KTD19: a short token naming one submission, carried
    by its review buttons so a button from an earlier submission is refused.
    Derived from the submission's progress-update ids (the highest id, first 8
    hex) - the same set the snapshot lists and, while the task is submitted,
    exactly its unreviewed updates - so it never depends on timestamp order."""
    ids = [uuid.UUID(str(value)) for value in progress_update_ids or () if value]
    return max(ids).hex[:8] if ids else None


@dataclass(frozen=True)
class TelegramAttachment:
    """A stored evidence file to send after the message text."""

    file_id: uuid.UUID  # FileObject id - never shown to the user
    caption: str | None = None


@dataclass(frozen=True)
class TelegramMessage:
    text: str
    parse_mode: str | None = None
    actions: tuple[tuple[TelegramAction, ...], ...] = field(default_factory=tuple)
    attachments: tuple[TelegramAttachment, ...] = field(default_factory=tuple)

    def _command_lines(self, actions: list[TelegramAction]) -> str:
        if self.parse_mode == "HTML":
            lines = [f"<code>{html.escape(a.command)}</code> - {html.escape(a.label)}" for a in actions]
            return "\n\n<b>Reply with:</b>\n" + "\n".join(lines)
        return "\n\nReply with:\n" + "\n".join(f"{a.command} - {a.label}" for a in actions)

    def text_with_typed_fallback(self) -> str:
        """Every action listed as a typed command (no buttons)."""
        commands = [action for row in self.actions for action in row]
        return self.text + self._command_lines(commands) if commands else self.text

    def text_for_buttons(self) -> str:
        """Message text when buttons are sent: only actions that have no
        button are listed as typed commands."""
        typed_only = [action for row in self.actions for action in row if not action.callback]
        return self.text + self._command_lines(typed_only) if typed_only else self.text

    def button_rows(self) -> list[list[dict]]:
        """Telegram `inline_keyboard` rows for every action with a callback."""
        rows = []
        for row in self.actions:
            buttons = [{"text": a.label, "callback_data": a.callback} for a in row if a.callback]
            if buttons:
                rows.append(buttons)
        return rows
