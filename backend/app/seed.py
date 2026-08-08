from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User, UserRole
from app.services.supabase_auth import SupabaseAuthError, admin_create_user, admin_find_user_by_email


def _ensure_super_admin(db: Session) -> User:
    email = (settings.bootstrap_super_admin_email or "superadmin@siteops.local").strip().lower()
    super_admin = db.scalar(select(User).where(User.email == email))
    if super_admin and super_admin.supabase_user_id:
        return super_admin

    if not settings.bootstrap_super_admin_password:
        if super_admin:
            print("WARNING: Super Admin exists locally but is not linked to Supabase Auth. Set BOOTSTRAP_SUPER_ADMIN_EMAIL and BOOTSTRAP_SUPER_ADMIN_PASSWORD once.")
            return super_admin
        raise RuntimeError("A fresh database requires BOOTSTRAP_SUPER_ADMIN_EMAIL and BOOTSTRAP_SUPER_ADMIN_PASSWORD.")

    try:
        identity = admin_create_user(
            email=email,
            password=settings.bootstrap_super_admin_password,
            metadata={"name": "Developer Super Admin", "siteops_role": UserRole.super_admin.value},
        )
    except SupabaseAuthError as exc:
        if exc.status_code != 409:
            raise RuntimeError(exc.public_message) from exc
        identity = admin_find_user_by_email(email)
        if not identity:
            raise RuntimeError("Supabase account exists but could not be linked to the bootstrap Super Admin.") from exc

    if not super_admin:
        super_admin = User(name="Developer Super Admin", email=email, role=UserRole.super_admin, active=True, password_hash=None, activated_at=datetime.now(timezone.utc))
        db.add(super_admin)
    super_admin.name = "Developer Super Admin"
    super_admin.role = UserRole.super_admin
    super_admin.active = True
    super_admin.password_hash = None
    super_admin.supabase_user_id = identity["id"]
    super_admin.activated_at = super_admin.activated_at or datetime.now(timezone.utc)
    db.flush()
    return super_admin


def ensure_seed_data(db: Session) -> None:
    # Previously also seeded a legacy `ExecutionTemplate` ("Interior Fit-out
    # 3 Day Standard") and its tasks. Templates are governed by the V2
    # template system now (siteops_v2.v2_templates, see templates_v2.py), so
    # re-creating the legacy row on every boot would resurrect a table the
    # vendor consolidation drops.
    _ensure_super_admin(db)
    db.commit()
