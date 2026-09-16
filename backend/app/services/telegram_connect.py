"""U13 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md,
KTD3): lets a person link a Telegram chat to their existing identity by
opening the bot's `/start <token>` link. Consuming a valid token only sets
`telegram_chat_id` - it never touches `active_channel` (KTD3). Only the
Admin/Super-Admin toggle (U15) changes which channel is actually live for
a person.

Rate-limiting and duplicate-delivery protection reuse `TelegramInboundUpdate`
(U2) - every inbound message is already stored there, so this counts
recent `/start` attempts from that count rather than adding a new table.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.execution_models import TelegramConnectToken, TelegramInboundUpdate
from app.models import EmployeeProfile
from app.services.telegram_provider import TelegramProviderAdapter
from app.vendor_models import V2VendorContact

# 5 attempts per 5 minutes: generous enough that a person mistyping a
# token once or twice is never blocked, tight enough to bound how many
# guesses an attacker can try against a real, unused token before the
# intended recipient uses it.
_RATE_LIMIT_WINDOW = timedelta(minutes=5)
_RATE_LIMIT_MAX_ATTEMPTS = 5

_INVALID_TOKEN_REPLY = "That connect link isn't valid or has expired. Please ask for a new one."
_RATE_LIMITED_REPLY = "Too many attempts. Please wait a few minutes and try again."
_SUCCESS_REPLY = "You're connected! You'll now receive messages here on Telegram once an admin switches you over."


class TelegramConnectService:
    def __init__(self, db: Session):
        self.db = db

    def handle_start(self, *, chat_id: str, message_text: str) -> None:
        """Processes a `/start <token>` message. Never raises - every
        outcome (rate-limited, invalid, success) replies to the chat and
        returns normally, matching this codebase's "never surfaced as a
        provider-facing error" webhook discipline."""
        adapter = TelegramProviderAdapter()

        if self._is_rate_limited(chat_id):
            adapter.send_text(chat_id, _RATE_LIMITED_REPLY)
            return

        token = self._extract_token(message_text)
        if not token:
            adapter.send_text(chat_id, _INVALID_TOKEN_REPLY)
            return

        connect_token = self.db.scalar(select(TelegramConnectToken).where(TelegramConnectToken.token == token))
        now = datetime.now(timezone.utc)
        # SQLite (test harness only - Postgres preserves tz-awareness on a
        # real `timestamptz` column) reads DateTime values back naive.
        # Normalize before comparing so this works in both environments.
        expires_at = connect_token.expires_at if connect_token is not None else None
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if connect_token is None or connect_token.used_at is not None or expires_at < now:
            # Never log the raw token value itself - only that an
            # invalid/expired/used attempt occurred.
            adapter.send_text(chat_id, _INVALID_TOKEN_REPLY)
            return

        connect_token.used_at = now
        if connect_token.employee_id is not None:
            profile = self.db.get(EmployeeProfile, connect_token.employee_id)
            profile.telegram_chat_id = chat_id
        else:
            contact = self.db.get(V2VendorContact, connect_token.vendor_contact_id)
            contact.telegram_chat_id = chat_id
        self.db.commit()

        adapter.send_text(chat_id, _SUCCESS_REPLY)

    @staticmethod
    def _extract_token(message_text: str) -> str | None:
        parts = (message_text or "").split(maxsplit=1)
        if len(parts) < 2 or parts[0] != "/start":
            return None
        token = parts[1].strip()
        return token or None

    def _is_rate_limited(self, chat_id: str) -> bool:
        window_start = datetime.now(timezone.utc) - _RATE_LIMIT_WINDOW
        count = self.db.scalar(
            select(func.count()).select_from(TelegramInboundUpdate).where(
                TelegramInboundUpdate.chat_id == chat_id,
                TelegramInboundUpdate.message_text.like("/start%"),
                TelegramInboundUpdate.created_at >= window_start,
            )
        ) or 0
        return count > _RATE_LIMIT_MAX_ATTEMPTS
