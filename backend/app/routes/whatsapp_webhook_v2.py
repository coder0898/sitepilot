"""Phase 2 U6: inbound WhatsApp webhook receiver (R8/R9).

THE SIGNATURE-VERIFICATION GATE: the raw request body bytes (never the
Pydantic-parsed JSON - FastAPI/Pydantic auto-parsing would consume the body
before we can hash it) are read via `await request.body()` and HMAC-SHA256'd
with `settings.whatsapp_webhook_secret`, then compared - using
`hmac.compare_digest` (constant-time, never `==`, to avoid a timing-attack
surface) - against the hex digest in the `X-Hub-Signature-256` header
(format `sha256=<hex digest>`, matching Meta's actual webhook convention).
If the header is missing, malformed, `settings.whatsapp_webhook_secret` is
empty, or the digest doesn't match, this returns 401 IMMEDIATELY - before
the JSON body is parsed, before any database query, before any
`inbound_messages` row is written. Only a signature-verified request ever
reaches `InboundMessageService.process`.

THE VERIFICATION HANDSHAKE (GET): before Meta will deliver anything to this
URL, registering it in Meta for Developers > WhatsApp > Configuration
requires answering one GET request with `?hub.mode=subscribe&hub.verify_
token=<token>&hub.challenge=<n>` by echoing `hub.challenge` back verbatim -
proving whoever owns the URL also knows the token entered in Meta's
dashboard. `settings.whatsapp_webhook_verify_token` is that token (distinct
from `whatsapp_webhook_secret`, which signs the POST deliveries themselves,
not this one-time handshake).

Expected JSON payload shape - Meta's real WhatsApp Cloud API webhook body
(https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/):

    {
      "object": "whatsapp_business_account",
      "entry": [{
        "id": "<waba_id>",
        "changes": [{
          "field": "messages",
          "value": {
            "messaging_product": "whatsapp",
            "metadata": {"phone_number_id": "..."},
            "messages": [{
              "from": "919000000001",
              "id": "wamid.HBgLMTIzNDU2Nzg5MAA=",
              "timestamp": "1700000000",
              "type": "text",
              "text": {"body": "ACCEPT 1a2b3c4d"}
            }]
          }
        }]
      }]
    }

`messages[].from` arrives as bare digits with no leading `+` (Meta's
convention) - every phone number this codebase stores is E.164 with a
leading `+` (enforced at write time, e.g. `app.routes.users`'s "+919876543210"
validation), so it is prefixed with `+` before being handed to
`InboundMessageService`, which matches by raw string equality against those
stored values (see that module's docstring for why no further normalization
is applied). A `changes[].value` with `statuses` instead of `messages` is a
delivery/read receipt, not an inbound message - skipped, not an error. A
non-`"text"` message type (image, location, etc.) is still passed through
with an empty `message_text`, which `InboundMessageService` already rejects
as "Unrecognized command" - not a crash. Meta may batch multiple entries/
changes/messages in one delivery; every message found is processed.

On success (200) each message's outcome is recorded internally on its own
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

from fastapi import APIRouter, Depends, HTTPException, Request, Response
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


def _extract_messages(payload: dict) -> list[dict]:
    """Pulls every `messages[]` entry out of Meta's nested envelope,
    tolerating any level being absent/malformed (a `statuses`-only change,
    an empty `entry` list, etc.) rather than raising - a webhook body this
    route doesn't recognize the shape of is simply "no messages found",
    never a 4xx (see module docstring's "never surfaced as 4xx/5xx" rule)."""
    messages: list[dict] = []
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            for message in value.get("messages") or []:
                if isinstance(message, dict):
                    messages.append(message)
    return messages


@router.get("/inbound")
async def verify_whatsapp_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if (
        mode == "subscribe"
        and settings.whatsapp_webhook_verify_token
        and token == settings.whatsapp_webhook_verify_token
        and challenge is not None
    ):
        # Meta expects the raw challenge string back, not JSON.
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(403, "Webhook verification failed.")


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

    for message in _extract_messages(payload):
        provider_message_id = message.get("id")
        sender_phone = message.get("from")
        if not provider_message_id or not sender_phone:
            continue  # Malformed individual message - skip it, not the whole batch.

        message_text = ""
        if message.get("type") == "text":
            message_text = (message.get("text") or {}).get("body") or ""

        InboundMessageService(db).process(
            str(provider_message_id), f"+{sender_phone}", str(message_text),
        )

    return {"status": "received"}
