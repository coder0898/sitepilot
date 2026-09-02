from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.routes.auth import router as auth_router
from app.services.supabase_auth import SupabaseAuthError


class DevLoginRouteTests(unittest.TestCase):
    """Local-only "sign in as any local test account" shortcut
    (app/routes/auth.py dev_login) - double-gated on LOCAL_DEV_LOGIN_ENABLED
    plus SUPABASE_URL pointing at a local host, so it can never be reached
    against a real deployment even if the env var were set by mistake.
    """

    def setUp(self):
        self._original_enabled = settings.local_dev_login_enabled
        self._original_url = settings.supabase_url
        app = FastAPI()
        app.include_router(auth_router)
        self.client = TestClient(app)

    def tearDown(self):
        settings.local_dev_login_enabled = self._original_enabled
        settings.supabase_url = self._original_url
        self.client.close()

    def test_disabled_by_default_returns_404(self):
        settings.local_dev_login_enabled = False
        settings.supabase_url = "http://127.0.0.1:15431"
        response = self.client.post("/api/auth/dev-login", json={"email": "superadmin@siteops.local"})
        self.assertEqual(response.status_code, 404)

    def test_enabled_but_pointed_at_a_non_local_supabase_url_still_404s(self):
        """Defense in depth: even if LOCAL_DEV_LOGIN_ENABLED were somehow
        set true against a real deployment, the route independently
        refuses unless SUPABASE_URL itself is a local host."""
        settings.local_dev_login_enabled = True
        settings.supabase_url = "https://realproject.supabase.co"
        response = self.client.post("/api/auth/dev-login", json={"email": "superadmin@siteops.local"})
        self.assertEqual(response.status_code, 404)

    def test_enabled_and_local_mints_a_session(self):
        settings.local_dev_login_enabled = True
        settings.supabase_url = "http://host.docker.internal:15431"
        session = {"access_token": "tok", "refresh_token": "refresh", "user": {"email": "superadmin@siteops.local"}}
        with patch("app.routes.auth.dev_login_session", return_value=session) as mocked:
            response = self.client.post("/api/auth/dev-login", json={"email": "SuperAdmin@SiteOps.local"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), session)
        mocked.assert_called_once_with("superadmin@siteops.local")

    def test_supabase_error_is_surfaced_with_its_own_status(self):
        settings.local_dev_login_enabled = True
        settings.supabase_url = "http://127.0.0.1:15431"
        with patch("app.routes.auth.dev_login_session", side_effect=SupabaseAuthError("Not found.", 404)):
            response = self.client.post("/api/auth/dev-login", json={"email": "nobody@nowhere.local"})
        self.assertEqual(response.status_code, 404)

    def test_provider_reports_dev_login_availability(self):
        settings.local_dev_login_enabled = True
        settings.supabase_url = "http://127.0.0.1:15431"
        self.assertTrue(self.client.get("/api/auth/provider").json()["dev_login_enabled"])

        settings.local_dev_login_enabled = False
        self.assertFalse(self.client.get("/api/auth/provider").json()["dev_login_enabled"])


if __name__ == "__main__":
    unittest.main()
