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

Photos and documents (`process_media`) take the same shared evidence-session
path WhatsApp attachments do; only downloading the file is Telegram-specific
(`_download_media`).

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

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select

from app.execution_models import GateEvidenceSessionAttachment, InboundMessage
from app.models import EmployeeProfile, User
from app.services.inbound_message import EmployeeIdentity, InboundMessageService
from app.services.project_gate_submission import MAX_EVIDENCE_SIZE_BYTES
from app.services.telegram_provider import TelegramProviderAdapter
from app.vendor_models import V2VendorContact


@dataclass(frozen=True)
class TelegramEvidenceOutcome:
    """What one message sent into an evidence session did."""

    inbound: InboundMessage
    approval_id: uuid.UUID | None  # the session's gate, when the item was added
    media: dict | None
    text: str


class TelegramInboundService(InboundMessageService):
    def __init__(self, db):
        super().__init__(db)
        self._inbound_channel = "telegram"
        self._inbound_channel_label = "Telegram"
        # Set when a message was handled as evidence (`_handle_gate_session_fallback`).
        self.evidence: TelegramEvidenceOutcome | None = None

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
            return self._handle_employee(provider_message_id, chat_id, message_text, employee_matches[0])
        return self._handle_vendor_contact(provider_message_id, chat_id, message_text, vendor_matches[0])

    def process_media(self, update_id: int, chat_id: str, media_metadata: dict) -> InboundMessage:
        """A photo or document. It is always evidence, never a command (a
        caption is only its description), so it goes straight to the shared
        evidence-session path - the same one WhatsApp attachments take -
        with the same duplicate-delivery check and identity matching as
        `process`. `media_metadata`: `id` (Telegram file_id), `kind`
        ("photo"/"document"), `mime_type`, `filename`, `file_size`, `caption`."""
        provider_message_id = str(update_id)
        existing = self.db.scalar(
            select(InboundMessage).where(InboundMessage.provider_message_id == provider_message_id)
        )
        if existing is not None:
            return existing

        caption = media_metadata.get("caption") or ""
        employee_matches = self._match_employees_by_chat_id(chat_id)
        if len(employee_matches) != 1 or self._match_vendor_contacts_by_chat_id(chat_id):
            return self._save(
                provider_message_id, chat_id, caption, None, None,
                "unmatched", "No single employee matched this Telegram chat.",
            )
        user, employee = employee_matches[0]
        if not media_metadata.get("filename"):
            media_metadata = {**media_metadata, "filename": self._photo_filename(user.id)}
        return self._handle_gate_session_fallback(provider_message_id, chat_id, caption, user, employee, media_metadata)

    def _photo_filename(self, user_id) -> str:
        """Telegram photos arrive without a name; number them within the
        open session (photo-1.jpg, photo-2.jpg...) so the Web App and the
        caption labels read clearly."""
        session = self._open_session_for_employee(user_id)
        count = 0
        if session is not None:
            count = self.db.scalar(
                select(func.count()).select_from(GateEvidenceSessionAttachment)
                .where(GateEvidenceSessionAttachment.session_id == session.id)
            ) or 0
        return f"photo-{count + 1}.jpg"

    # ---- evidence hooks ---------------------------------------------------------

    def _handle_gate_session_fallback(self, provider_message_id, sender, message_text, user, employee, media_metadata):
        """Records what an evidence message did (`self.evidence`), so the
        Telegram layer can confirm it or explain a rejection."""
        outcome = super()._handle_gate_session_fallback(
            provider_message_id, sender, message_text, user, employee, media_metadata,
        )
        session = self._open_session_for_employee(user.id) if outcome.processing_status == "processed" else None
        self.evidence = TelegramEvidenceOutcome(
            inbound=outcome,
            approval_id=session.approval_id if session is not None else None,
            media=media_metadata,
            text=message_text,
        )
        return outcome

    def _download_media(self, media_metadata: dict):
        return TelegramProviderAdapter().download_file(media_metadata.get("id"), max_bytes=MAX_EVIDENCE_SIZE_BYTES)

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
