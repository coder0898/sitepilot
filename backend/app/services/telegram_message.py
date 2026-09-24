"""Rendered Telegram message shape shared by the Telegram renderers and dispatch.

`actions` describes what the recipient can do next, as rows of
`TelegramAction`s. Each action carries the exact typed command that performs
it, so the business logic always stays behind the shared command handlers
(`inbound_message.py`) - the renderer only describes the choice. Until inline
buttons are wired (gate plan chunk 2), `text_with_typed_fallback()` lists the
actions as typed commands instead.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TelegramAction:
    label: str
    command: str


@dataclass(frozen=True)
class TelegramMessage:
    text: str
    parse_mode: str | None = None
    actions: tuple[tuple[TelegramAction, ...], ...] = field(default_factory=tuple)

    def text_with_typed_fallback(self) -> str:
        if not self.actions:
            return self.text
        commands = [action for row in self.actions for action in row]
        if self.parse_mode == "HTML":
            lines = [f"<code>{html.escape(a.command)}</code> - {html.escape(a.label)}" for a in commands]
            return f"{self.text}\n\n<b>Reply with:</b>\n" + "\n".join(lines)
        lines = [f"{a.command} - {a.label}" for a in commands]
        return f"{self.text}\n\nReply with:\n" + "\n".join(lines)
