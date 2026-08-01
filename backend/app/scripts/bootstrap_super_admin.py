"""Standalone, explicitly-invoked Super Admin bootstrap for staging/production.

This is the staging/production counterpart to `app.seed._ensure_super_admin`,
which only runs locally (ENVIRONMENT=local). Run this once against a fresh
staging/production database to create the first Super Admin account.

What it does:
- Creates the Super Admin's Supabase Auth account directly via the Supabase
  Admin API (service role key), NOT by hitting SiteOps's own signup/API
  endpoints.
- Creates (or, on rerun, verifies) the matching SiteOps `User` row with
  role=super_admin, linked via `supabase_user_id`.
- Is idempotent: rerunning after a successful run is a no-op that verifies
  state and exits 0. It never resets the password of an already-existing,
  correctly role-mapped account.
- Fails loudly (non-zero exit, no DB writes) if the Supabase Auth account
  already exists but is NOT correctly linked to a super_admin User row. It
  does not attempt to silently repair that state - a human must resolve it.
- Never logs or prints the password, at any log level, in any branch.

Required environment variables:
    BOOTSTRAP_SUPER_ADMIN=true   # opt-in switch; script refuses to run otherwise
    SUPER_ADMIN_EMAIL            # (alias of BOOTSTRAP_SUPER_ADMIN_EMAIL)
    SUPER_ADMIN_PASSWORD         # (alias of BOOTSTRAP_SUPER_ADMIN_PASSWORD)
    SUPER_ADMIN_NAME             # optional, defaults to "Super Admin"
    SUPABASE_URL                 # (alias of SUPABASE_BACKEND_URL-derived SUPABASE_URL)
    SUPABASE_SERVICE_ROLE_KEY    # (alias of SUPABASE_SECRET_KEY)

Usage (from the backend/ directory, with env vars set in the target
environment - e.g. a one-off Render shell/job, never committed anywhere):

    python -m app.scripts.bootstrap_super_admin

After a successful run, unset BOOTSTRAP_SUPER_ADMIN (or set it back to
false) in that environment's configuration. Leaving it set is harmless
(the script is idempotent and will not reset the password or duplicate
the account) but is unnecessary attack surface and should not remain on.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import User, UserRole
from app.services.supabase_auth import SupabaseAuthError, admin_create_user, admin_find_user_by_email


class BootstrapError(RuntimeError):
    """Raised for any condition that must stop the bootstrap without writing to the DB."""


def _validate_config() -> tuple[str, str, str]:
    if not settings.bootstrap_super_admin_enabled:
        raise BootstrapError(
            "Refusing to run: BOOTSTRAP_SUPER_ADMIN is not set to true. "
            "This is an explicit opt-in safeguard - set BOOTSTRAP_SUPER_ADMIN=true "
            "for this one invocation only, then unset it."
        )
    email = settings.bootstrap_super_admin_email.strip().lower()
    password = settings.bootstrap_super_admin_password
    if not email:
        raise BootstrapError("SUPER_ADMIN_EMAIL (or BOOTSTRAP_SUPER_ADMIN_EMAIL) is required.")
    if not password or len(password) < 8:
        raise BootstrapError("SUPER_ADMIN_PASSWORD (or BOOTSTRAP_SUPER_ADMIN_PASSWORD) must be set to at least 8 characters.")
    if not settings.supabase_url:
        raise BootstrapError("SUPABASE_URL is required.")
    if not settings.supabase_secret_key:
        raise BootstrapError("SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_SECRET_KEY) is required.")
    return email, password, settings.super_admin_name or "Super Admin"


def _find_existing_user(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


def run() -> None:
    email, password, name = _validate_config()

    with SessionLocal() as db:
        existing_user = _find_existing_user(db, email)

        # Case 1: a SiteOps User row already exists for this email.
        if existing_user is not None:
            if existing_user.supabase_user_id and existing_user.role == UserRole.super_admin:
                # Already fully bootstrapped. Idempotent no-op - do NOT touch
                # the password or re-create anything.
                print(f"Super Admin already bootstrapped for {email} (user_id={existing_user.id}). No changes made.")
                return
            if existing_user.supabase_user_id and existing_user.role != UserRole.super_admin:
                raise BootstrapError(
                    f"A SiteOps user already exists for {email} and is linked to a Supabase Auth account, "
                    f"but its role is {existing_user.role.value!r}, not 'super_admin'. Refusing to silently "
                    "change role. Resolve manually (e.g. via an authorized role-change flow) before rerunning."
                )
            if not existing_user.supabase_user_id:
                raise BootstrapError(
                    f"A SiteOps user already exists for {email} but has no linked Supabase Auth account "
                    "(supabase_user_id is null). Refusing to silently create/link one - this looks like "
                    "partially-migrated legacy data. Investigate before rerunning "
                    "(see app.scripts.link_supabase_users for the legacy backfill path)."
                )

        # Case 2: no local User row yet. Check whether a Supabase Auth
        # account for this email already exists (e.g. a previous run got
        # interrupted after creating the auth account but before the DB
        # commit).
        identity = admin_find_user_by_email(email)
        if identity is not None:
            # Auth account exists but there is no matching super_admin User
            # row - this is exactly the "exists but not correctly linked"
            # case the spec requires failing loudly on, rather than
            # silently creating a duplicate-looking local record or
            # resetting the password.
            raise BootstrapError(
                f"A Supabase Auth account already exists for {email} (id={identity.get('id')}) but no matching "
                "SiteOps super_admin User row was found. Refusing to auto-link or reset its password. "
                "If this is expected (e.g. retrying after a failed first run), manually create/link the "
                "SiteOps User row with role=super_admin and supabase_user_id set to the id above, then rerun "
                "this script to verify."
            )

        # Case 3: genuinely fresh - create both the Supabase Auth account
        # and the local User row.
        try:
            identity = admin_create_user(
                email=email,
                password=password,
                metadata={"name": name, "siteops_role": UserRole.super_admin.value},
            )
        except SupabaseAuthError as exc:
            raise BootstrapError(f"Failed to create Supabase Auth account: {exc.public_message}") from exc

        user = User(
            name=name,
            email=email,
            role=UserRole.super_admin,
            active=True,
            password_hash=None,
            supabase_user_id=identity["id"],
            activated_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        print(f"Created Super Admin {email} (user_id={user.id}, supabase_user_id={identity['id']}).")
        print("Reminder: set BOOTSTRAP_SUPER_ADMIN back to false/unset in this environment now that bootstrap is complete.")


if __name__ == "__main__":
    try:
        run()
    except BootstrapError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
