"""U14 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md,
KTD7): Telegram command parity with WhatsApp's inbound command set.

Resolves the open design question this unit was blocked on (see the
plan's Deferred / Open Questions): reusing `InboundMessageService`'s
actual command grammar and business-service calls via subclassing,
instead of duplicating them in a separate module. `_handle_employee`,
`_handle_vendor_contact`, and every `_handle_gate_*` method already take
an already-resolved identity plus a generic message-id/sender string -
they have no WhatsApp-specific behavior once identity matching is done.
Only identity matching (phone vs `telegram_chat_id`) is genuinely
channel-specific, so that is the only thing this module implements.

This single entry point supports all ten commands (vendor ACCEPT/DECLINE/
CLARIFY, employee STATUS, and all six GATE* commands) immediately,
because they were never re-implemented per channel - they are the same
inherited code paths WhatsApp already exercises. See
test_telegram_inbound_commands.py for one verification scenario per
command, in the plan's stated order.

Confirmations and errors route back over Telegram automatically: every
`_handle_*` method's success/failure path already goes through the
shared `OutboxService`/`MessageDispatchService` pipeline (U9/U10), which
resolves each recipient's actual `active_channel` at send time - no new
confirmation pipeline needed here.
"""

from __future__ import annotations

from sqlalchemy import select

from app.execution_models import InboundMessage
from app.models import EmployeeProfile, User
from app.services.inbound_message import EmployeeIdentity, InboundMessageService
from app.vendor_models import V2VendorContact


class TelegramInboundService(InboundMessageService):
    def __init__(self, db):
        super().__init__(db)
        self._inbound_channel = "telegram"
        self._inbound_channel_label = "Telegram"

    def process(self, update_id: int, chat_id: str, message_text: str) -> InboundMessage:
        """Mirrors `InboundMessageService.process`'s dedup-then-match-then-
        dispatch shape exactly, with `telegram_chat_id` matching in place
        of phone matching. `update_id` doubles as `provider_message_id` -
        `InboundMessage.provider_message_id`'s existing uniqueness
        constraint is what U2/U14's "reject a duplicate delivery" gap
        actually resolves to: the same dedup check WhatsApp already relies
        on, not a second mechanism."""
        provider_message_id = str(update_id)
        existing = self.db.scalar(
            select(InboundMessage).where(InboundMessage.provider_message_id == provider_message_id)
        )
        if existing is not None:
            return existing

        employee_matches = self._match_employees_by_chat_id(chat_id)
        vendor_matches = self._match_vendor_contacts_by_chat_id(chat_id)
        total_matches = len(employee_matches) + len(vendor_matches)

        if total_matches == 0:
            return self._save(
                provider_message_id, chat_id, message_text, None, None,
                "unmatched", "No identity matched this Telegram chat.",
            )
        if total_matches > 1:
            return self._save(
                provider_message_id, chat_id, message_text, None, None,
                "unmatched", "Telegram chat matched more than one identity; ambiguous.",
            )

        if employee_matches:
            # media_metadata is not passed (defaults to None) - Telegram
            # evidence/photo upload is a known gap, not yet built (see the
            # plan's Dependencies / Assumptions).
            return self._handle_employee(provider_message_id, chat_id, message_text, employee_matches[0])
        return self._handle_vendor_contact(provider_message_id, chat_id, message_text, vendor_matches[0])

    def _match_employees_by_chat_id(self, chat_id: str) -> list[EmployeeIdentity]:
        rows = self.db.execute(
            select(User, EmployeeProfile)
            .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
            .where(EmployeeProfile.telegram_chat_id == chat_id, User.active.is_(True))
        ).all()
        return [(row[0], row[1]) for row in rows]

    def _match_vendor_contacts_by_chat_id(self, chat_id: str) -> list[V2VendorContact]:
        return list(
            self.db.scalars(
                select(V2VendorContact).where(V2VendorContact.telegram_chat_id == chat_id)
            ).all()
        )
