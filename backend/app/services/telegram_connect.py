"""U13 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md,
KTD3): lets a person link a Telegram chat to their existing identity by
opening the bot's `/start <token>` link. Consuming a valid token only sets
`telegram_chat_id` - it never touches `active_channel` (KTD3). Only the
Admin/Super-Admin toggle (U15) changes which channel is actually live for
a person.

Rate-limiting and duplicate-delivery protection reuse `TelegramInboundUpdate`
(U2) - every inbound message is already stored there, so this counts
recent `/start` attempts from that count rather than adding a new table.

Local-testing follow-up (2026-09-18): `generate_code` below is the
token-ISSUING half this module was missing entirely - `TelegramConnectToken`
(U3) only ever had schema plus this file's *consuming* half (`handle_start`).
Nothing generated a real token before this, so nobody could actually
complete the connect flow through the product; a prior local test session
worked around it with a one-off DB script. Exposed via
`app/routes/telegram_connect_codes.py`.

Local-testing follow-up (2026-09-21): `unlink_employee` frees an employee's
`telegram_chat_id` so a different employee can connect the same physical
Telegram account - `telegram_chat_id` is unique at the DB level, so two
employees can never hold the same chat id at once, and local testing has
only one real Telegram account to test with. Admin-only, mirrors
`ChannelToggleService`'s audit pattern (`app.services.channel_toggle`).
Deliberately narrow: it only clears `telegram_chat_id` on `EmployeeProfile`
- it never touches `active_channel`, role, membership, or any other
employee data, and never offboards/deletes anyone.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.execution_models import TelegramConnectToken, TelegramInboundUpdate
from app.models import EmployeeProfile, User
from app.project_models import V2AuditEvent
from app.services.telegram_provider import TelegramProviderAdapter
from app.vendor_models import V2VendorContact

# A connect code is single-use and short-lived on purpose - it only ever
# needs to survive the gap between an Admin generating it and the person
# opening Telegram and sending it, not a general-purpose credential.
_CODE_TTL_MINUTES = 15

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

    def generate_code(
        self,
        *,
        employee_id: uuid.UUID | None = None,
        vendor_contact_id: uuid.UUID | None = None,
    ) -> TelegramConnectToken:
        """Issues a fresh one-time connect code for exactly one target -
        the missing generation half of the `/start <token>` flow this
        class only ever consumed (see module docstring).

        Any previous unused (not necessarily expired) code for the SAME
        target is invalidated first (`used_at` set, without ever setting
        `telegram_chat_id` from it), so at most one code is ever live per
        person - showing an Admin two "currently valid" codes for the same
        person is confusing, and leaving the old one alive would let
        either one work, silently doubling the guessable surface for no
        reason.
        """
        if (employee_id is None) == (vendor_contact_id is None):
            raise ValueError("Exactly one of employee_id or vendor_contact_id must be set.")

        if employee_id is not None:
            target_exists = self.db.get(EmployeeProfile, employee_id) is not None
            match_filter = TelegramConnectToken.employee_id == employee_id
        else:
            target_exists = self.db.get(V2VendorContact, vendor_contact_id) is not None
            match_filter = TelegramConnectToken.vendor_contact_id == vendor_contact_id
        if not target_exists:
            raise HTTPException(404, "Person not found.")

        now = datetime.now(timezone.utc)
        stale_tokens = self.db.scalars(
            select(TelegramConnectToken).where(match_filter, TelegramConnectToken.used_at.is_(None))
        ).all()
        for stale in stale_tokens:
            stale.used_at = now

        token = TelegramConnectToken(
            token=secrets.token_urlsafe(8),
            employee_id=employee_id,
            vendor_contact_id=vendor_contact_id,
            expires_at=now + timedelta(minutes=_CODE_TTL_MINUTES),
        )
        self.db.add(token)
        self.db.commit()
        self.db.refresh(token)
        return token

    def unlink_employee(self, *, employee_id: uuid.UUID, actor: User) -> EmployeeProfile:
        """Clears `telegram_chat_id` on one employee, freeing that chat id
        for a different employee to connect (unique constraint). Idempotent:
        unlinking an already-unconnected employee is a no-op success with
        no audit row, same convention `ChannelToggleService._toggle_one`
        uses for a no-op switch."""
        profile = self.db.get(EmployeeProfile, employee_id)
        if profile is None:
            raise HTTPException(404, "Employee not found.")

        if not profile.telegram_chat_id:
            return profile

        profile.telegram_chat_id = None
        self.db.add(V2AuditEvent(
            actor_user_id=actor.id,
            action="telegram_unlinked",
            entity_type="employee",
            entity_id=profile.id,
            before_json={"telegram_connected": True},
            after_json={"telegram_connected": False},
            reason=f"Telegram unlinked by {actor.name}.",
        ))
        self.db.commit()
        self.db.refresh(profile)
        return profile

    def unlink_vendor_contact(self, *, vendor_contact_id: uuid.UUID, actor: User) -> V2VendorContact:
        """Sibling of `unlink_employee`, same idempotent/audit shape, for a
        `V2VendorContact` instead of an `EmployeeProfile`."""
        contact = self.db.get(V2VendorContact, vendor_contact_id)
        if contact is None:
            raise HTTPException(404, "Vendor contact not found.")

        if not contact.telegram_chat_id:
            return contact

        contact.telegram_chat_id = None
        self.db.add(V2AuditEvent(
            actor_user_id=actor.id,
            action="telegram_unlinked",
            entity_type="vendor_contact",
            entity_id=contact.id,
            before_json={"telegram_connected": True},
            after_json={"telegram_connected": False},
            reason=f"Telegram unlinked by {actor.name}.",
        ))
        self.db.commit()
        self.db.refresh(contact)
        return contact

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
