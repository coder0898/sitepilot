from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.services.supabase_auth import SupabaseAuthError, dev_login_session

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _local_dev_login_available() -> bool:
    if not settings.local_dev_login_enabled:
        return False
    supabase_url = settings.supabase_url.lower()
    return any(host in supabase_url for host in ("127.0.0.1", "localhost", "host.docker.internal"))


@router.get("/provider")
def provider():
    return {
        "provider": "supabase",
        "passwords_stored_by_siteops": False,
        "recovery": "google_oauth",
        "dev_login_enabled": _local_dev_login_available(),
    }


class DevLoginIn(BaseModel):
    email: str = Field(min_length=3)


# Local-only "sign in as any local test account" shortcut for testing
# without configuring real Google OAuth credentials against localhost.
# Double-gated so a stray env var alone can never expose this against a
# real deployment: LOCAL_DEV_LOGIN_ENABLED must be explicitly true (only
# docker-compose.yml sets it - render.yaml/prod never does), AND
# SUPABASE_URL itself must point at a local host. `email` need not already
# be a SiteOps user - typing an unregistered address exercises the exact
# same "first Google sign-in, no matching roster row" rejection
# current_user() (app/auth.py) gives a real first-time Google login.
@router.post("/dev-login")
def dev_login(payload: DevLoginIn):
    if not _local_dev_login_available():
        raise HTTPException(404)
    email = payload.email.strip().lower()
    if not email:
        raise HTTPException(422, "Email is required.")
    try:
        return dev_login_session(email)
    except SupabaseAuthError as exc:
        raise HTTPException(exc.status_code, exc.public_message) from exc
