"""Telegram Bot API adapter.

Implements a Telegram-equivalent send surface to `whatsapp_provider.py`'s
`MetaCloudApiAdapter` - not the same `WhatsAppProviderAdapter` protocol
(`send(recipient_phone, template, payload)`), since Telegram has no
Meta-style named-template system (KTD8 in
`docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md`).
This module only sends - callers own retries, persistence, and recipient
resolution, mirroring `whatsapp_provider.py`'s own scope.

Standalone at this point (U1): nothing calls this yet. Wiring it into
`MessageDispatchService` as a real per-recipient adapter option, and
resolving how event payloads become Telegram text/buttons instead of
Meta template components, is deferred to U9/U10/KTD8's open question
(see the plan's Deferred / Open Questions section) - out of scope here.
"""

from __future__ import annotations

import httpx

from app.config import settings
from app.services.message_dispatch import ProviderSendResult

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramProviderAdapter:
    """Sends Telegram messages via the Bot API's `sendMessage` method.

    Credentials default to `app.config.settings` (env-sourced) but can be
    overridden per-instance, mirroring `MetaCloudApiAdapter`'s pattern.
    """

    def __init__(
        self,
        *,
        access_token: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.access_token = access_token or settings.telegram_access_token
        self.timeout = timeout

    def send_text(self, chat_id: str, text: str) -> ProviderSendResult:
        """Sends a plain-text message. No inline keyboard."""
        return self._send(chat_id, text, reply_markup=None)

    def send_with_buttons(self, chat_id: str, text: str, buttons: list[list[dict]]) -> ProviderSendResult:
        """Sends a text message with an inline keyboard.

        `buttons` is a list of button rows, each row a list of
        `{"text": ..., "callback_data": ...}` dicts, matching Telegram's
        own `inline_keyboard` shape directly - no translation layer, since
        nothing in this codebase has an opinion on button shape yet.
        """
        reply_markup = {"inline_keyboard": buttons}
        return self._send(chat_id, text, reply_markup=reply_markup)

    def _send(self, chat_id: str, text: str, *, reply_markup: dict | None) -> ProviderSendResult:
        if not chat_id:
            return ProviderSendResult(
                ok=False,
                failure_code="missing_chat_id",
                failure_reason="Recipient has no Telegram chat id on file.",
            )
        if not self.access_token:
            return ProviderSendResult(
                ok=False,
                failure_code="not_configured",
                failure_reason="Telegram access token not set.",
            )

        url = f"{TELEGRAM_API_BASE}/bot{self.access_token}/sendMessage"
        body: dict = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            body["reply_markup"] = reply_markup

        try:
            response = httpx.post(url, json=body, timeout=self.timeout)
        except httpx.HTTPError as exc:
            return ProviderSendResult(ok=False, failure_code="network_error", failure_reason=str(exc))

        data = response.json() if response.content else {}

        if response.status_code >= 400 or not data.get("ok", False):
            return ProviderSendResult(
                ok=False,
                failure_code=str(data.get("error_code", response.status_code)),
                failure_reason=data.get("description") or f"HTTP {response.status_code}",
            )

        result = data.get("result") or {}
        message_id = result.get("message_id")
        return ProviderSendResult(ok=True, provider_message_id=str(message_id) if message_id is not None else None)
