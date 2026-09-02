from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.supabase_auth import SupabaseAuthError, dev_login_session


class DevLoginSessionTests(unittest.TestCase):
    """dev_login_session (backend/app/services/supabase_auth.py), used by
    the local dev sign-in shortcut - mints a real session via
    admin_generate_link + /verify with no browser round trip."""

    def test_verifies_with_the_type_generate_link_actually_issued(self):
        """A brand-new email (no existing auth.users row) comes back from
        generate_link with verification_type "signup", not the requested
        "magiclink" - generate_link also creates that row. Regression case
        for a bug caught during manual testing: hardcoding "magiclink" for
        /verify made every first-time dev sign-in fail with GoTrue's
        "Token has expired or is invalid"."""
        responses = [
            {"email_otp": "123456", "verification_type": "signup"},
            {"access_token": "tok", "refresh_token": "refresh", "user": {"email": "new@test.local"}},
        ]
        with patch("app.services.supabase_auth._request", side_effect=responses) as mocked:
            session = dev_login_session("new@test.local")

        self.assertEqual(session["access_token"], "tok")
        self.assertEqual(mocked.call_count, 2)
        verify_call = mocked.call_args_list[1]
        self.assertEqual(verify_call.args[0], "/verify")
        self.assertEqual(verify_call.kwargs["payload"]["type"], "signup")
        self.assertEqual(verify_call.kwargs["payload"]["token"], "123456")

    def test_falls_back_to_magiclink_when_generate_link_omits_verification_type(self):
        responses = [
            {"email_otp": "654321"},
            {"access_token": "tok", "refresh_token": "refresh", "user": {"email": "existing@test.local"}},
        ]
        with patch("app.services.supabase_auth._request", side_effect=responses) as mocked:
            dev_login_session("existing@test.local")

        verify_call = mocked.call_args_list[1]
        self.assertEqual(verify_call.kwargs["payload"]["type"], "magiclink")

    def test_raises_when_generate_link_returns_no_otp(self):
        with patch("app.services.supabase_auth._request", return_value={}):
            with self.assertRaises(SupabaseAuthError):
                dev_login_session("nobody@test.local")


if __name__ == "__main__":
    unittest.main()
