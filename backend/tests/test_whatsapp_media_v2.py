"""Phase 2 U9: `download_inbound_media`'s two-step Graph API flow
(`app.services.whatsapp_media`).

Mocks `httpx.get` directly (no real network calls), mirroring how
`MetaCloudApiAdapter` (`whatsapp_provider.py`) itself talks to the Graph
API - `httpx.get(url, ...)` for a plain GET, JSON body on success, an
`error` object on a >=400 response.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.config import settings
from app.services.whatsapp_media import MediaDownloadResult, download_inbound_media


class _FakeResponse:
    """Minimal stand-in for an `httpx.Response` - only what
    `download_inbound_media` actually reads (`status_code`, `.json()`,
    `.content`)."""

    def __init__(self, status_code: int, json_data: dict | None = None, content: bytes | None = None):
        self.status_code = status_code
        self._json_data = json_data or {}
        # `download_inbound_media` treats an empty `.content` as "no body
        # to parse" (mirroring `MetaCloudApiAdapter`'s own convention) -
        # default to a non-empty placeholder so a `json_data`-bearing fake
        # response is actually read, unless a real body (`content=...`) is
        # given explicitly.
        self.content = content if content is not None else b"{}"

    def json(self):
        return self._json_data


class DownloadInboundMediaTests(unittest.TestCase):
    def setUp(self):
        self._original_token = settings.whatsapp_access_token
        self._original_phone_id = settings.whatsapp_phone_number_id
        self._original_version = settings.whatsapp_api_version
        settings.whatsapp_access_token = "test-access-token"
        settings.whatsapp_phone_number_id = "test-phone-number-id"
        settings.whatsapp_api_version = "v20.0"

    def tearDown(self):
        settings.whatsapp_access_token = self._original_token
        settings.whatsapp_phone_number_id = self._original_phone_id
        settings.whatsapp_api_version = self._original_version

    @patch("app.services.whatsapp_media.httpx.get")
    def test_valid_media_id_returns_bytes_and_mime_type(self, mock_get):
        mock_get.side_effect = [
            _FakeResponse(
                200,
                json_data={
                    "url": "https://lookaside.example/media-abc",
                    "mime_type": "image/jpeg",
                    "id": "media-abc",
                },
            ),
            _FakeResponse(200, content=b"raw-image-bytes"),
        ]

        result = download_inbound_media("media-abc")

        self.assertIsInstance(result, MediaDownloadResult)
        self.assertTrue(result.ok)
        self.assertEqual(result.bytes, b"raw-image-bytes")
        self.assertEqual(result.mime_type, "image/jpeg")
        self.assertIsNone(result.failure_code)

        # Step 1: resolves the media_id via the Graph API, bearer-authed,
        # phone_number_id as a query param - same convention
        # MetaCloudApiAdapter uses for sending.
        first_call = mock_get.call_args_list[0]
        self.assertEqual(first_call.args[0], "https://graph.facebook.com/v20.0/media-abc")
        self.assertEqual(first_call.kwargs["params"], {"phone_number_id": "test-phone-number-id"})
        self.assertEqual(first_call.kwargs["headers"], {"Authorization": "Bearer test-access-token"})

        # Step 2: fetches from the temporary URL step 1 returned, same
        # bearer token, no additional params.
        second_call = mock_get.call_args_list[1]
        self.assertEqual(second_call.args[0], "https://lookaside.example/media-abc")
        self.assertEqual(second_call.kwargs["headers"], {"Authorization": "Bearer test-access-token"})

    @patch("app.services.whatsapp_media.httpx.get")
    def test_invalid_media_id_returns_media_not_found(self, mock_get):
        mock_get.return_value = _FakeResponse(
            400,
            json_data={"error": {"code": 100, "message": "Unsupported get request.", "error_subcode": 33}},
        )

        result = download_inbound_media("bad-media-id")

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_code, "media_not_found")
        self.assertIsNone(result.bytes)
        mock_get.assert_called_once()  # Step 2 is never attempted.

    @patch("app.services.whatsapp_media.httpx.get")
    def test_expired_download_url_returns_media_url_expired(self, mock_get):
        mock_get.side_effect = [
            _FakeResponse(
                200,
                json_data={"url": "https://lookaside.example/expired", "mime_type": "application/pdf"},
            ),
            _FakeResponse(404),
        ]

        result = download_inbound_media("media-expired")

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_code, "media_url_expired")
        self.assertIsNone(result.bytes)
        self.assertEqual(mock_get.call_count, 2)

    @patch("app.services.whatsapp_media.httpx.get")
    def test_not_configured_when_credentials_missing(self, mock_get):
        settings.whatsapp_access_token = ""

        result = download_inbound_media("media-abc")

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_code, "not_configured")
        mock_get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
