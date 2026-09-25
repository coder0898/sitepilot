"""Replies to evidence an employee sends on Telegram (gate plan chunk 4).

A photo, a document or a text note sent while an evidence session is open is
added by the shared evidence-session path (`TelegramInboundService`, the same
path WhatsApp attachments take). This module only tells the employee what
happened, so evidence is never silently dropped:

- added: "Evidence Added" with what was received, plus [Add More Evidence]
  [Submit for Review] [Cancel Evidence Session];
- a photo/document with no open session: "No evidence submission is
  currently open" - the file is not attached to any other gate;
- unsupported type, too large, or not downloadable: "Couldn't add this
  evidence" with the reason.

A text message with no open session keeps today's behaviour (no reply) - it
may be a mistyped command, not evidence.
"""

from __future__ import annotations

import html

from sqlalchemy.orm import Session

from app.execution_models import ProjectExternalApproval
from app.project_models import V2ProjectExternalGate
from app.services.inbound_message import (
    DOWNLOAD_FAILED_REASON_PREFIX,
    NO_OPEN_SESSION_REASON,
    OVERSIZED_ATTACHMENT_REASON,
    SESSION_NOT_ASSIGNED_REASON,
    UNSUPPORTED_ATTACHMENT_REASON,
)
from app.services.telegram_gate_render import render_evidence_added
from app.services.telegram_inbound import TelegramEvidenceOutcome, TelegramInboundService
from app.services.telegram_provider import TelegramProviderAdapter

_UNLINKED = "This Telegram account isn't linked to SiteOps. Ask your Admin for a new connect link."
_NO_SESSION = "<b>No evidence submission is currently open</b>\n\nOpen the approval and tap Submit Evidence first."
_TYPE_OR_SIZE = (
    "This file type or size isn't supported. Please send a supported photo (JPG, PNG, WebP) "
    "or PDF of up to 10 MB, or use the Web App."
)
_DOWNLOAD_FAILED = "The file couldn't be downloaded from Telegram. Please send it again."
_NOT_ASSIGNED = (
    "This approval is no longer assigned to you, so nothing was added. "
    "Tap Cancel Evidence Session to close this submission."
)


def _e(value: object) -> str:
    return html.escape(str(value), quote=False)


class TelegramEvidenceService:
    def __init__(self, db: Session, provider: TelegramProviderAdapter | None = None):
        self.db = db
        self.provider = provider or TelegramProviderAdapter()

    def handle_media(self, *, update_id: int, chat_id: str, media: dict) -> None:
        """A photo or document message: added to the sender's open evidence
        session, and the sender is told the outcome."""
        inbound = TelegramInboundService(self.db)
        outcome = inbound.process_media(update_id, chat_id, media)
        if outcome.processing_status == "unmatched":
            self._reply(chat_id, f"<b>Couldn't add this evidence</b>\n\n{_e(_UNLINKED)}")
            return
        if inbound.evidence is not None:
            self._reply_to(chat_id, inbound.evidence)

    def handle_text(self, *, update_id: int, chat_id: str, text: str) -> None:
        """A text message: processed exactly as before (a typed command, or
        a note for the open evidence session). Only a note that went into a
        session gets a reply."""
        inbound = TelegramInboundService(self.db)
        inbound.process(update_id, chat_id, text)
        evidence = inbound.evidence
        if evidence is None:
            return
        if evidence.inbound.rejection_reason == NO_OPEN_SESSION_REASON:
            return  # plain text with no session: unchanged, no reply
        self._reply_to(chat_id, evidence)

    # ---- replies ------------------------------------------------------------

    def _reply_to(self, chat_id: str, evidence: TelegramEvidenceOutcome) -> None:
        if evidence.inbound.processing_status == "processed" and evidence.approval_id is not None:
            message = render_evidence_added(self._gate_name(evidence.approval_id), self._received(evidence))
            self.provider.send_with_buttons(chat_id, message.text_for_buttons(), message.button_rows(), parse_mode="HTML")
            return
        reason = evidence.inbound.rejection_reason or ""
        if reason == NO_OPEN_SESSION_REASON:
            self._reply(chat_id, _NO_SESSION)
            return
        if reason in (UNSUPPORTED_ATTACHMENT_REASON, OVERSIZED_ATTACHMENT_REASON):
            explanation = _TYPE_OR_SIZE
        elif reason.startswith(DOWNLOAD_FAILED_REASON_PREFIX):
            explanation = _DOWNLOAD_FAILED
        elif reason == SESSION_NOT_ASSIGNED_REASON:
            explanation = _NOT_ASSIGNED
        else:
            explanation = reason or "Unknown reason."
        self._reply(chat_id, f"<b>Couldn't add this evidence</b>\n\n{_e(explanation)}")

    @staticmethod
    def _received(evidence: TelegramEvidenceOutcome) -> str:
        media = evidence.media
        if media is None:
            return "Text note"
        label = "Photo" if media.get("kind") == "photo" else media.get("filename") or "Document"
        return f"{label} (with caption)" if (media.get("caption") or "").strip() else label

    def _gate_name(self, approval_id) -> str:
        approval = self.db.get(ProjectExternalApproval, approval_id)
        gate = self.db.get(V2ProjectExternalGate, approval.project_gate_id) if approval is not None else None
        return gate.approval_name if gate is not None else "this approval"

    def _reply(self, chat_id: str, html_text: str) -> None:
        self.provider.send_text(chat_id, html_text, parse_mode="HTML")
