"""Phase 2 U6: inbound WhatsApp webhook receiver (R8/R9).

THE SIGNATURE-VERIFICATION GATE: the raw request body bytes (never the
Pydantic-parsed JSON - FastAPI/Pydantic auto-parsing would consume the body
before we can hash it) are read via `await request.body()` and HMAC-SHA256'd
with `settings.whatsapp_webhook_secret`, then compared - using
`hmac.compare_digest` (constant-time, never `==`, to avoid a timing-attack
surface) - against the hex digest in the `X-Hub-Signature-256` header
(format `sha256=<hex digest>`, mirroring Meta's actual webhook convention;
no real Meta integration is wired in here). If the header is missing,
malformed, `settings.whatsapp_webhook_secret` is empty, or the digest
doesn't match, this returns 401 IMMEDIATELY - before the JSON body is
parsed, before any database query, before any `inbound_messages` row is
written. Only a signature-verified request ever reaches
`InboundMessageService.process`.

Expected JSON payload shape (a deliberately simplified, invented minimal
shape loosely mirroring a real Meta WhatsApp webhook body - no real Meta
schema is wired in yet):

    {
      "provider_message_id": "wamid.HBgLMTIzNDU2Nzg5MAA=",
      "sender_phone": "+919000000001",
      "message_text": "ACCEPT 1a2b3c4d"
    }

On success (200) the outcome is recorded internally on the
`inbound_messages` row (`processing_status`); it is never surfaced back to
the provider as a 4xx/5xx for a business-level failure (unmatched phone
number, ambiguous match, invalid command, a rejected task transition,
etc.) - providers retry non-2xx responses, and an unmatched/invalid inbound
message should never trigger infinite provider retries.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.services.inbound_message import InboundMessageService

router = APIRouter(prefix="/api/v2/whatsapp", tags=["v2-whatsapp-webhook"])


def _verify_signature(raw_body: bytes, signature_header: str | None) -> None:
    if not settings.whatsapp_webhook_secret:
        raise HTTPException(401, "Invalid webhook signature.")
    if not signature_header or not signature_header.startswith("sha256="):
        raise HTTPException(401, "Invalid webhook signature.")

    provided_digest = signature_header[len("sha256="):]
    expected_digest = hmac.new(
        settings.whatsapp_webhook_secret.encode("utf-8"), raw_body, hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(provided_digest, expected_digest):
        raise HTTPException(401, "Invalid webhook signature.")


@router.post("/inbound")
async def receive_inbound_whatsapp_message(request: Request, db: Session = Depends(get_db)):
    # Read raw bytes BEFORE any JSON parsing - required for the signature
    # computation to match what the provider actually signed.
    raw_body = await request.body()
    _verify_signature(raw_body, request.headers.get("X-Hub-Signature-256"))

    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(422, "Malformed JSON payload.") from exc

    if not isinstance(payload, dict):
        raise HTTPException(422, "Malformed JSON payload.")

    provider_message_id = payload.get("provider_message_id")
    sender_phone = payload.get("sender_phone")
    message_text = payload.get("message_text") or ""

    if not provider_message_id or not sender_phone:
        raise HTTPException(422, "provider_message_id and sender_phone are required.")

    InboundMessageService(db).process(str(provider_message_id), str(sender_phone), str(message_text))
    return {"status": "received"}
