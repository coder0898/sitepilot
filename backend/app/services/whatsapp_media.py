"""Phase 2 U9: inbound WhatsApp media download (R8, realizes F1).

Meta's Graph API never hands over an inbound attachment's bytes in the
webhook payload itself - only a `media_id` (see `whatsapp_webhook_v2.py`'s
`_extract_media_metadata`). Retrieving the actual bytes is a two-step flow:

    1. GET /{api_version}/{media_id}?phone_number_id={phone_number_id}
       (bearer token) - resolves a short-lived, one-time-use download URL
       plus the media's `mime_type`.
    2. GET {url} (same bearer token) - fetches the actual bytes from that
       URL before it expires.

`download_inbound_media` is a plain callable implementing exactly that -
it does not decide *when* it's worth calling. That decision belongs to a
later unit, which only spends this Graph API round trip once it already
knows there is an open evidence session to attach the result to AND the
mime_type is one this feature accepts - sparing a network call for an
attachment that was always going to be rejected.

Reuses `GRAPH_API_BASE`/`settings.whatsapp_api_version`/
`settings.whatsapp_access_token`/`settings.whatsapp_phone_number_id` from
`whatsapp_provider.py` - no new configuration.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import settings
from app.services.whatsapp_provider import GRAPH_API_BASE


@dataclass(frozen=True)
class MediaDownloadResult:
    """Outcome of one `download_inbound_media(...)` attempt - mirrors
    `ProviderSendResult`'s shape (`message_dispatch.py`)."""

    ok: bool
    bytes: bytes | None = None
    mime_type: str | None = None
    failure_code: str | None = None
    failure_reason: str | None = None


def download_inbound_media(
    media_id: str,
    *,
    access_token: str | None = None,
    phone_number_id: str | None = None,
    api_version: str | None = None,
    timeout: float = 15.0,
) -> MediaDownloadResult:
    """Downloads one inbound media attachment's bytes from Meta's Graph
    API, given the `media_id` a webhook payload's `image`/`document`
    message carried.

    Credentials default to `app.config.settings` (env-sourced), matching
    `MetaCloudApiAdapter`'s own convention, and can be overridden per-call
    for tests or a one-off script.
    """
    token = access_token or settings.whatsapp_access_token
    phone_id = phone_number_id or settings.whatsapp_phone_number_id
    version = api_version or settings.whatsapp_api_version

    if not token or not phone_id:
        return MediaDownloadResult(
            ok=False,
            failure_code="not_configured",
            failure_reason="WhatsApp access token / phone number id not set.",
        )

    headers = {"Authorization": f"Bearer {token}"}

    # Step 1: resolve the media_id to a temporary download URL + mime_type.
    lookup_url = f"{GRAPH_API_BASE}/{version}/{media_id}"
    try:
        lookup_response = httpx.get(
            lookup_url, params={"phone_number_id": phone_id}, headers=headers, timeout=timeout,
        )
    except httpx.HTTPError as exc:
        return MediaDownloadResult(ok=False, failure_code="network_error", failure_reason=str(exc))

    lookup_data = lookup_response.json() if lookup_response.content else {}

    if lookup_response.status_code >= 400:
        # Meta's documented failure here is an invalid/expired media_id
        # (code 100 / subcode 33) - the only failure step 1 actually
        # produces in practice, so any non-2xx maps to the same code.
        error = lookup_data.get("error", {})
        return MediaDownloadResult(
            ok=False,
            failure_code="media_not_found",
            failure_reason=error.get("message") or f"HTTP {lookup_response.status_code}",
        )

    download_url = lookup_data.get("url")
    mime_type = lookup_data.get("mime_type")
    if not download_url:
        return MediaDownloadResult(
            ok=False, failure_code="media_not_found", failure_reason="No download URL returned.",
        )

    # Step 2: fetch the actual bytes from the temporary URL before it
    # expires - same bearer token, per Meta's documented flow.
    try:
        download_response = httpx.get(download_url, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        return MediaDownloadResult(ok=False, failure_code="network_error", failure_reason=str(exc))

    if download_response.status_code == 404:
        return MediaDownloadResult(
            ok=False, failure_code="media_url_expired", failure_reason="Media download URL has expired.",
        )
    if download_response.status_code >= 400:
        return MediaDownloadResult(
            ok=False,
            failure_code=str(download_response.status_code),
            failure_reason=f"HTTP {download_response.status_code}",
        )

    return MediaDownloadResult(ok=True, bytes=download_response.content, mime_type=mime_type)
