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

Self-link follow-up (2026-09-29): one Telegram chat <-> one identity, never
replaced silently. `handle_start` refuses a chat that is already linked to
someone else, and an identity already linked to a different chat, until an
Admin unlinks; it only works in a private chat. Tokens are stored as a
SHA-256 hash (the raw value exists only in the link handed to the person).
Linking and unlinking both clear the chat's open bot question
(`telegram_pending_input.clear_pending`), since that question belongs to
whoever the chat was linked to when it was asked. Queued/parked deliveries
need no change: `MessageDelivery` is keyed to the recipient identity and
`message_dispatch` resolves that identity's chat id fresh on every attempt,
so a relinked chat can never receive the previous person's messages.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.execution_models import TelegramConnectToken, TelegramInboundUpdate
from app.models import EmployeeProfile, User
from app.project_models import V2AuditEvent
from app.services.telegram_pending_input import clear_pending
from app.services.telegram_provider import TelegramProviderAdapter
from app.vendor_models import V2VendorContact

# A connect code is single-use and short-lived on purpose - it only ever
# needs to survive the gap between an Admin generating it and the person
# opening Telegram and sending it, not a general-purpose credential.
_CODE_TTL_MINUTES = 15

# 24 random bytes -> 32 URL-safe characters, inside Telegram's 64-character
# `start` parameter limit and its [A-Za-z0-9_-] alphabet.
_TOKEN_BYTES = 24

# 5 attempts per 5 minutes: generous enough that a person mistyping a
# token once or twice is never blocked, tight enough to bound how many
# guesses an attacker can try against a real, unused token before the
# intended recipient uses it.
_RATE_LIMIT_WINDOW = timedelta(minutes=5)
_RATE_LIMIT_MAX_ATTEMPTS = 5

_INVALID_TOKEN_REPLY = "That connect link isn't valid or has expired. Please ask for a new one."
_RATE_LIMITED_REPLY = "Too many attempts. Please wait a few minutes and try again."
_SUCCESS_REPLY = "You're connected! You'll now receive messages here on Telegram once an admin switches you over."
_PRIVATE_ONLY_REPLY = "Please open this link in a private chat with the bot, not in a group."
_CHAT_TAKEN_REPLY = "This Telegram account is already linked. Unlink it first."
_IDENTITY_TAKEN_REPLY = (
    "This SiteOps account is already linked to another Telegram account. Ask an admin to unlink it first."
)
_ALREADY_CONNECTED_REPLY = "You're already connected to this account."


def hash_token(raw_token: str) -> str:
    """What `TelegramConnectToken.token` stores. A random 192-bit token needs
    no salt or slow hash - the point is only that a database read never
    yields a usable link."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IssuedConnectCode:
    """A freshly generated code. `raw_token` is shown once and never stored."""

    raw_token: str
    expires_at: datetime


class TelegramConnectService:
    def __init__(self, db: Session):
        self.db = db

    def generate_code(
        self,
        *,
        employee_id: uuid.UUID | None = None,
        vendor_contact_id: uuid.UUID | None = None,
    ) -> IssuedConnectCode:
        """Issues a fresh one-time connect code for exactly one target -
        the missing generation half of the `/start <token>` flow this
        class only ever consumed (see module docstring).

        Refused while the target already has a linked chat: the link would
        be refused on use anyway, and an Admin must unlink first.

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
            target = self.db.get(EmployeeProfile, employee_id)
            match_filter = TelegramConnectToken.employee_id == employee_id
        else:
            target = self.db.get(V2VendorContact, vendor_contact_id)
            match_filter = TelegramConnectToken.vendor_contact_id == vendor_contact_id
        if target is None:
            raise HTTPException(404, "Person not found.")
        if target.telegram_chat_id:
            raise HTTPException(409, "This person is already linked to Telegram. Unlink it first.")

        now = datetime.now(timezone.utc)
        stale_tokens = self.db.scalars(
            select(TelegramConnectToken).where(match_filter, TelegramConnectToken.used_at.is_(None))
        ).all()
        for stale in stale_tokens:
            stale.used_at = now

        raw_token = secrets.token_urlsafe(_TOKEN_BYTES)
        token = TelegramConnectToken(
            token=hash_token(raw_token),
            employee_id=employee_id,
            vendor_contact_id=vendor_contact_id,
            expires_at=now + timedelta(minutes=_CODE_TTL_MINUTES),
        )
        self.db.add(token)
        self.db.commit()
        self.db.refresh(token)
        return IssuedConnectCode(raw_token=raw_token, expires_at=token.expires_at)

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

        clear_pending(self.db, profile.telegram_chat_id)
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

        clear_pending(self.db, contact.telegram_chat_id)
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

    def handle_start(self, *, chat_id: str, message_text: str, chat_type: str | None = None) -> None:
        """Processes a `/start <token>` message. Never raises - every
        outcome (rate-limited, invalid, refused, success) replies to the
        chat and returns normally, matching this codebase's "never surfaced
        as a provider-facing error" webhook discipline.

        A refusal that the person can fix (group chat, chat or account
        already linked) leaves the token unused, so the same link still
        works once the Admin has unlinked, until it expires."""
        adapter = TelegramProviderAdapter()

        if self._is_rate_limited(chat_id):
            adapter.send_text(chat_id, _RATE_LIMITED_REPLY)
            return

        if chat_type != "private":
            adapter.send_text(chat_id, _PRIVATE_ONLY_REPLY)
            return

        token = self._extract_token(message_text)
        if not token:
            adapter.send_text(chat_id, _INVALID_TOKEN_REPLY)
            return

        connect_token = self.db.scalar(
            select(TelegramConnectToken).where(TelegramConnectToken.token == hash_token(token))
        )
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

        if connect_token.employee_id is not None:
            target = self.db.get(EmployeeProfile, connect_token.employee_id)
            user = self.db.get(User, target.user_id) if target is not None else None
            if target is None or user is None or not user.active:
                adapter.send_text(chat_id, _INVALID_TOKEN_REPLY)
                return
            entity_type, actor_user_id = "employee", user.id
        else:
            target = self.db.get(V2VendorContact, connect_token.vendor_contact_id)
            if target is None:
                adapter.send_text(chat_id, _INVALID_TOKEN_REPLY)
                return
            entity_type, actor_user_id = "vendor_contact", None

        if target.telegram_chat_id == chat_id:
            connect_token.used_at = now
            self.db.commit()
            adapter.send_text(chat_id, _ALREADY_CONNECTED_REPLY)
            return
        if self._chat_linked_elsewhere(chat_id):
            adapter.send_text(chat_id, _CHAT_TAKEN_REPLY)
            return
        if target.telegram_chat_id:
            adapter.send_text(chat_id, _IDENTITY_TAKEN_REPLY)
            return

        connect_token.used_at = now
        target.telegram_chat_id = chat_id
        clear_pending(self.db, chat_id)
        self.db.add(V2AuditEvent(
            actor_user_id=actor_user_id,
            action="telegram_linked",
            entity_type=entity_type,
            entity_id=target.id,
            before_json={"telegram_connected": False},
            after_json={"telegram_connected": True},
            reason="Telegram linked from a one-time connect link.",
        ))
        try:
            self.db.commit()
        except IntegrityError:
            # A concurrent link claimed this chat first (unique chat id).
            self.db.rollback()
            adapter.send_text(chat_id, _CHAT_TAKEN_REPLY)
            return

        adapter.send_text(chat_id, _SUCCESS_REPLY)

    def _chat_linked_elsewhere(self, chat_id: str) -> bool:
        """Any employee or vendor contact already holds this chat."""
        employee = self.db.scalar(select(EmployeeProfile.id).where(EmployeeProfile.telegram_chat_id == chat_id))
        if employee is not None:
            return True
        return self.db.scalar(select(V2VendorContact.id).where(V2VendorContact.telegram_chat_id == chat_id)) is not None

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
