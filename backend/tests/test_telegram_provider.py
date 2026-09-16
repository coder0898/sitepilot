"""U1: standalone Telegram Bot API adapter (docs/plans/2026-09-16-001-feat-
telegram-messaging-channel-plan.md).

Mocks `httpx.post` directly (no real network calls), mirroring
`test_whatsapp_media_v2.py`'s pattern for `whatsapp_media.httpx.get`.
Nothing calls `TelegramProviderAdapter` yet - these tests exercise it in
isolation, the same POC-style manual check the plan's Verification field
calls for, done here as automated coverage instead.
"""

import unittest
from unittest.mock import patch

from app.services.telegram_provider import TelegramProviderAdapter


class _FakeResponse:
    """Minimal stand-in for an `httpx.Response` - only what
    `TelegramProviderAdapter._send` reads (`.status_code`, `.content`,
    `.json()`)."""

    def __init__(self, status_code: int, json_body: dict | None):
        self.status_code = status_code
        self._json_body = json_body
        self.content = b"x" if json_body is not None else b""

    def json(self):
        return self._json_body


class TelegramProviderAdapterTests(unittest.TestCase):
    def setUp(self):
        self.adapter = TelegramProviderAdapter(access_token="test-token")

    @patch("app.services.telegram_provider.httpx.post")
    def test_send_text_success_returns_provider_message_id(self, mock_post):
        mock_post.return_value = _FakeResponse(
            200, {"ok": True, "result": {"message_id": 42}},
        )

        result = self.adapter.send_text("12345", "hello")

        self.assertTrue(result.ok)
        self.assertEqual(result.provider_message_id, "42")
        call = mock_post.call_args
        self.assertEqual(call.kwargs["json"]["chat_id"], "12345")
        self.assertEqual(call.kwargs["json"]["text"], "hello")
        self.assertNotIn("reply_markup", call.kwargs["json"])

    @patch("app.services.telegram_provider.httpx.post")
    def test_send_with_buttons_includes_inline_keyboard_rows(self, mock_post):
        mock_post.return_value = _FakeResponse(
            200, {"ok": True, "result": {"message_id": 7}},
        )
        buttons = [[{"text": "Accept", "callback_data": "accept"}]]

        result = self.adapter.send_with_buttons("12345", "Approve?", buttons)

        self.assertTrue(result.ok)
        sent_body = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_body["reply_markup"], {"inline_keyboard": buttons})

    @patch("app.services.telegram_provider.httpx.post")
    def test_missing_chat_id_fails_without_network_call(self, mock_post):
        result = self.adapter.send_text("", "hello")

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_code, "missing_chat_id")
        mock_post.assert_not_called()

    @patch("app.services.telegram_provider.httpx.post")
    def test_missing_access_token_fails_without_network_call(self, mock_post):
        unconfigured = TelegramProviderAdapter(access_token="")

        result = unconfigured.send_text("12345", "hello")

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_code, "not_configured")
        mock_post.assert_not_called()

    @patch("app.services.telegram_provider.httpx.post")
    def test_telegram_api_error_response_returns_failure_not_exception(self, mock_post):
        mock_post.return_value = _FakeResponse(
            400, {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"},
        )

        result = self.adapter.send_text("12345", "hello")

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_code, "400")
        self.assertEqual(result.failure_reason, "Bad Request: chat not found")

    @patch("app.services.telegram_provider.httpx.post")
    def test_network_error_returns_failure_not_exception(self, mock_post):
        import httpx

        mock_post.side_effect = httpx.ConnectError("connection refused")

        result = self.adapter.send_text("12345", "hello")

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_code, "network_error")


if __name__ == "__main__":
    unittest.main()
