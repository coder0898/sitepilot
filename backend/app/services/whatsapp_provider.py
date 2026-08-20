"""Real Meta WhatsApp Cloud API adapter (Graph API).

Implements the same `WhatsAppProviderAdapter` protocol as
`SandboxProviderAdapter` (see `app.services.message_dispatch`), so it can
later be wired into `MessageDispatchService` as a drop-in replacement -
`MessageDispatchService(db, adapter=MetaCloudApiAdapter())`. Not yet wired
in anywhere: `message_dispatch.py`'s own docstring notes turning on a real
provider is "a separate, deliberate decision". This module only sends -
callers own retries, persistence, and recipient resolution.

Only template messages are supported (`type: "template"` in the Graph API
request body), never free-form text: WhatsApp's Cloud API rejects a
business-initiated free-form text message outside a 24h customer-service
session (error 131047), so a template is the only message shape that
reliably sends on a fresh test number. `hello_world` is the one template
every WhatsApp Business Account has pre-approved from creation - it is what
`backend/app/scripts/test_whatsapp_send.py` uses to prove connectivity
before any custom template exists.
"""

from __future__ import annotations

import httpx

from app.config import settings
from app.services.message_dispatch import ProviderSendResult

GRAPH_API_BASE = "https://graph.facebook.com"


class MetaCloudApiAdapter:
    """Sends WhatsApp template messages via Meta's Graph API.

    Credentials default to `app.config.settings` (env-sourced) but can be
    overridden per-instance, e.g. for a one-off script run against a
    different test number without touching `.env`.
    """

    def __init__(
        self,
        *,
        access_token: str | None = None,
        phone_number_id: str | None = None,
        api_version: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.access_token = access_token or settings.whatsapp_access_token
        self.phone_number_id = phone_number_id or settings.whatsapp_phone_number_id
        self.api_version = api_version or settings.whatsapp_api_version
        self.timeout = timeout

    def send(self, recipient_phone: str, template: str, payload: dict) -> ProviderSendResult:
        if not recipient_phone:
            return ProviderSendResult(
                ok=False,
                failure_code="missing_phone",
                failure_reason="Recipient has no phone number on file.",
            )
        if not self.access_token or not self.phone_number_id:
            return ProviderSendResult(
                ok=False,
                failure_code="not_configured",
                failure_reason="WhatsApp access token / phone number id not set.",
            )

        url = f"{GRAPH_API_BASE}/{self.api_version}/{self.phone_number_id}/messages"
        body = self._build_body(recipient_phone, template, payload)

        try:
            response = httpx.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {self.access_token}"},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            return ProviderSendResult(ok=False, failure_code="network_error", failure_reason=str(exc))

        data = response.json() if response.content else {}

        if response.status_code >= 400:
            error = data.get("error", {})
            return ProviderSendResult(
                ok=False,
                failure_code=str(error.get("code", response.status_code)),
                failure_reason=error.get("message") or f"HTTP {response.status_code}",
            )

        messages = data.get("messages") or []
        provider_message_id = messages[0].get("id") if messages else None
        return ProviderSendResult(ok=True, provider_message_id=provider_message_id)

    @staticmethod
    def _build_body(recipient_phone: str, template: str, payload: dict) -> dict:
        language_code = payload.get("language_code", "en_US")
        template_body: dict = {"name": template, "language": {"code": language_code}}
        components = payload.get("components")
        if components:
            template_body["components"] = components
        return {
            "messaging_product": "whatsapp",
            "to": recipient_phone,
            "type": "template",
            "template": template_body,
        }
