import hashlib
import json
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError, PyJWTError

from app.config import settings

_TOKEN_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_TOKEN_CACHE_LOCK = threading.Lock()
_TOKEN_CACHE_TTL_SECONDS = 30

# JWKS-verified tokens are cached under the same TTL/lock as the legacy
# HTTP-verified path above, so both strategies share one cache.
_JWKS_CLIENT: PyJWKClient | None = None
_JWKS_CLIENT_LOCK = threading.Lock()
_JWKS_CACHE_TTL_SECONDS = 600


class SupabaseAuthError(Exception):
    def __init__(self, public_message: str, status_code: int = 502):
        self.public_message = public_message
        self.status_code = status_code
        super().__init__(public_message)


def _configuration() -> tuple[str, str, str]:
    url = settings.supabase_url.rstrip("/")
    if not url or not settings.supabase_publishable_key:
        raise SupabaseAuthError("Supabase Auth is not configured on the server.", 503)
    return url, settings.supabase_publishable_key, settings.supabase_secret_key


def _jwks_client() -> PyJWKClient:
    """Lazily build (and cache) the JWKS client for this process.

    Supabase projects created on the new API-key system (sb_publishable_/
    sb_secret_ prefixes, as used by this project) sign access tokens
    asymmetrically and publish a standard JWKS endpoint, so tokens can be
    verified locally without a round trip to Supabase on every request.
    PyJWKClient handles fetching + caching + rotating the signing keys.
    """
    global _JWKS_CLIENT
    with _JWKS_CLIENT_LOCK:
        if _JWKS_CLIENT is None:
            url = settings.supabase_url.rstrip("/")
            if not url:
                raise SupabaseAuthError("Supabase Auth is not configured on the server.", 503)
            _JWKS_CLIENT = PyJWKClient(
                f"{url}/auth/v1/.well-known/jwks.json",
                cache_keys=True,
                lifespan=_JWKS_CACHE_TTL_SECONDS,
            )
        return _JWKS_CLIENT


def _request(path: str, *, method: str = "GET", payload: dict[str, Any] | None = None, token: str | None = None, admin: bool = False) -> Any:
    url, publishable_key, secret_key = _configuration()
    key = secret_key if admin else publishable_key
    if admin and not key:
        raise SupabaseAuthError("Supabase secret key is not configured on the server.", 503)
    headers = {"apikey": key, "Authorization": f"Bearer {token or key}"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    try:
        with urlopen(Request(f"{url}/auth/v1{path}", data=body, headers=headers, method=method), timeout=10) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8"))
            message = detail.get("msg") or detail.get("message") or detail.get("error_description")
        except (ValueError, UnicodeDecodeError):
            message = None
        if admin and exc.code in {400, 422} and message:
            raise SupabaseAuthError(message, 409) from exc
        raise SupabaseAuthError(message or "Supabase Auth rejected the request.", exc.code) from exc
    except (URLError, TimeoutError) as exc:
        raise SupabaseAuthError("Supabase Auth is temporarily unavailable.", 503) from exc


def _verify_via_jwks(token: str) -> dict[str, Any] | None:
    """Verify a Supabase access token locally against its published JWKS.

    Returns the decoded claims (reshaped to look like the /auth/v1/user
    payload so callers don't need to know which strategy ran), or None if
    this token/project combination can't be verified this way (e.g. an
    HS256-signed token from a legacy shared-secret Supabase project) so the
    caller can fall back to the HTTP-verification path.
    """
    url = settings.supabase_url.rstrip("/")
    if not url:
        return None
    try:
        header = jwt.get_unverified_header(token)
    except PyJWTError:
        return None
    if header.get("alg") not in {"RS256", "ES256"}:
        # Shared-secret (HS256) Supabase projects don't publish a JWKS;
        # let the caller fall back to /auth/v1/user verification.
        return None
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience="authenticated",
            options={"require": ["exp", "sub"]},
        )
    except PyJWKClientError:
        # JWKS endpoint unreachable/misconfigured - fall back rather than
        # hard-failing every request on a transient network issue.
        return None
    except PyJWTError as exc:
        raise SupabaseAuthError("Verification link expired. Request a new link.", 401) from exc

    return {
        "id": claims.get("sub"),
        "email": claims.get("email"),
        "role": claims.get("role"),
        "user_metadata": claims.get("user_metadata", {}),
        "app_metadata": claims.get("app_metadata", {}),
    }


def verify_access_token(token: str) -> dict[str, Any]:
    cache_key = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = time.monotonic()
    with _TOKEN_CACHE_LOCK:
        cached = _TOKEN_CACHE.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]

    identity = _verify_via_jwks(token)
    if identity is None:
        # Fallback: HS256 project, or JWKS temporarily unavailable.
        identity = _request("/user", token=token)

    with _TOKEN_CACHE_LOCK:
        if len(_TOKEN_CACHE) >= 512:
            expired = [key for key, (expires_at, _) in _TOKEN_CACHE.items() if expires_at <= now]
            for key in expired or list(_TOKEN_CACHE)[:128]:
                _TOKEN_CACHE.pop(key, None)
        _TOKEN_CACHE[cache_key] = (now + _TOKEN_CACHE_TTL_SECONDS, identity)
    return identity


def admin_create_user(*, email: str, password: str, metadata: dict[str, Any]) -> dict[str, Any]:
    result = _request("/admin/users", method="POST", admin=True, payload={
        "email": email,
        "password": password,
        "email_confirm": True,
        "user_metadata": metadata,
    })
    return result.get("user", result)


def admin_update_user(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    result = _request(f"/admin/users/{user_id}", method="PUT", admin=True, payload=payload)
    return result.get("user", result)


def admin_delete_user(user_id: str) -> None:
    _request(f"/admin/users/{user_id}", method="DELETE", admin=True)


def admin_find_user_by_email(email: str) -> dict[str, Any] | None:
    result = _request("/admin/users?page=1&per_page=1000", admin=True)
    users = result.get("users", result if isinstance(result, list) else [])
    return next((item for item in users if item.get("email", "").lower() == email.lower()), None)



def request_password_recovery(email: str, redirect_to: str) -> None:
    query = urlencode({"redirect_to": redirect_to})
    _request(f"/recover?{query}", method="POST", payload={"email": email})

def request_email_verification(email: str, redirect_to: str, metadata: dict[str, Any] | None = None) -> None:
    """Send a magic-link verification without replacing the administrator browser session."""
    query = urlencode({"redirect_to": redirect_to})
    _request(f"/otp?{query}", method="POST", payload={
        "email": email,
        "create_user": True,
        "data": metadata or {},
    })