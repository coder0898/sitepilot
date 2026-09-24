"""U2 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md):
inbound Telegram webhook receiver - raw receive only.

THE SECRET-TOKEN GATE: unlike WhatsApp's HMAC-signed payloads
(`whatsapp_webhook_v2.py`), Telegram's Bot API sends a plain secret value
verbatim in the `X-Telegram-Bot-Api-Secret-Token` header on every webhook
delivery, once configured via `setWebhook`'s `secret_token` parameter -
there is nothing to sign or hash, only a direct comparison. It is still
done with `hmac.compare_digest` (constant-time, never `==`) to avoid a
timing-attack surface on the secret value itself. If the header is missing,
`settings.telegram_webhook_secret` is empty, or the value doesn't match,
this returns 401 IMMEDIATELY - before the JSON body is parsed, before any
database query, before any `telegram_inbound_updates` row is written.

This unit verifies and stores the raw update, then recognizes a
`/start <token>` message and hands it to `TelegramConnectService` (U13),
any other non-empty text to `TelegramInboundService` (U14) for full
command parity - unless the bot is waiting for a typed answer from that
chat (a rejection reason or health note), which takes the text first - or
an inline-button press to `TelegramCallbackService` (which runs the same
typed command the button stands for). Telegram's own `update_id` is stored alongside the raw
update, and a duplicate delivery short-circuits BEFORE either handler
runs (the `IntegrityError` branch below returns early) - Telegram's Bot
API redelivers on a slow/failed response, the same at-least-once behavior
WhatsApp's `InboundMessage.provider_message_id` uniqueness already
guards against (and which `TelegramInboundService.process` also uses
directly, since `update_id` doubles as that same `provider_message_id`).

Expected JSON payload shape - Telegram's real Bot API update
(https://core.telegram.org/bots/api#update), the two shapes this unit
extracts:

    {"update_id": 123456789, "message": {"chat": {"id": 987654321}, "text": "/start abc123"}}
    {"update_id": 123456790, "callback_query": {"message": {"chat": {"id": 987654321}}, "data": "accept"}}

A duplicate `update_id` (same webhook delivery retried by Telegram) is
silently accepted as a no-op, not rejected as an error - matching this
route's "never surfaced as 4xx/5xx for a business-level outcome" discipline,
the same one `whatsapp_webhook_v2.py` follows.
"""

from __future__ import annotations

import hmac
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.execution_models import TelegramInboundUpdate
from app.services.outbox_scheduler import run_dispatch_pass
from app.services.telegram_callback import TelegramCallbackService
from app.services.telegram_connect import TelegramConnectService
from app.services.telegram_inbound import TelegramInboundService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/telegram", tags=["v2-telegram-webhook"])


def _verify_secret_token(header_value: str | None) -> None:
    if not settings.telegram_webhook_secret:
        raise HTTPException(401, "Invalid webhook secret.")
    if not header_value:
        raise HTTPException(401, "Invalid webhook secret.")
    if not hmac.compare_digest(header_value, settings.telegram_webhook_secret):
        raise HTTPException(401, "Invalid webhook secret.")


@router.post("/inbound")
async def receive_inbound_telegram_update(
    request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db),
):
    _verify_secret_token(request.headers.get("X-Telegram-Bot-Api-Secret-Token"))

    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(422, "Malformed JSON payload.") from exc

    if not isinstance(payload, dict):
        raise HTTPException(422, "Malformed JSON payload.")

    update_id = payload.get("update_id")
    message = payload.get("message")
    callback_query = payload.get("callback_query")

    chat_id: str | None = None
    message_text: str | None = None
    callback_data: str | None = None
    callback_query_id: str | None = None
    callback_message_id: int | None = None

    if isinstance(message, dict):
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id")) if chat.get("id") is not None else None
        message_text = message.get("text")
    elif isinstance(callback_query, dict):
        inner_message = callback_query.get("message") or {}
        chat = inner_message.get("chat") or {}
        chat_id = str(chat.get("id")) if chat.get("id") is not None else None
        callback_data = callback_query.get("data")
        callback_query_id = callback_query.get("id")
        callback_message_id = inner_message.get("message_id")

    if update_id is None or chat_id is None:
        # Malformed or unrecognized update shape - nothing to store, not an
        # error (a location pin, a poll answer, etc. arrive this way too).
        return {"status": "received"}

    row = TelegramInboundUpdate(
        update_id=int(update_id),
        chat_id=chat_id,
        message_text=message_text,
        callback_data=callback_data,
        raw_payload=payload,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # Duplicate update_id - Telegram redelivered the same update. No-op,
        # not an error (see module docstring). Returning here, before any
        # /start processing below, is what U13's duplicate-delivery
        # protection actually is - a retried update never reaches
        # TelegramConnectService a second time.
        db.rollback()
        return {"status": "received"}

    if message_text and message_text.startswith("/start"):
        # U13: connect-flow.
        TelegramConnectService(db).handle_start(chat_id=chat_id, message_text=message_text)
    elif message_text:
        # A question the bot asked (rejection reason / health note) takes
        # the next text message first; otherwise it is a normal message.
        handled, acted = TelegramCallbackService(db).handle_text(
            update_id=int(update_id), chat_id=chat_id, text=message_text,
        )
        if acted:
            background_tasks.add_task(_dispatch_now)
        if not handled:
            # U14: full command parity (vendor ACCEPT/DECLINE/CLARIFY, employee
            # STATUS, all six GATE* commands) - reuses InboundMessageService's
            # shared dispatch, not a separate implementation per command.
            TelegramInboundService(db).process(int(update_id), chat_id, message_text)
    elif callback_data is not None:
        # Inline-button press: runs the same GATE* command a user could type.
        acted = TelegramCallbackService(db).handle(
            update_id=int(update_id), chat_id=chat_id, message_id=callback_message_id,
            callback_query_id=callback_query_id, data=callback_data,
        )
        if acted:
            # Deliver the action's follow-up message now rather than on the
            # dispatcher's next interval, so the button feels immediate.
            background_tasks.add_task(_dispatch_now)

    return {"status": "received"}


def _dispatch_now() -> None:
    """One extra outbox dispatch pass, the same pass the background
    dispatcher runs on its interval (safe to overlap - dispatch tolerates
    concurrent passes). A failure only delays delivery to the next pass."""
    if not settings.outbox_dispatch_enabled:
        return
    try:
        run_dispatch_pass()
    except Exception:  # noqa: BLE001 - never surface a delivery hiccup to the webhook
        logger.exception("Immediate dispatch pass after a Telegram button press failed.")
