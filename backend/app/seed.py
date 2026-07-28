from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ExecutionTemplate, ExecutionTemplateTask, User, UserRole
from app.services.supabase_auth import SupabaseAuthError, admin_create_user, admin_find_user_by_email

DEFAULT_TEMPLATE_TASKS = [
    (1, "Site preparation and safety setup", "Site preparation", "Safety barricades, floor protection, marking consumables"),
    (1, "Electrical and partition marking", "Electrical", "Marking chalk, conduits, junction boxes"),
    (1, "Material unloading and verification", "Logistics", "Day 1 approved material lot"),
    (2, "Partition and framing installation", "Civil & partition", "Channels, studs, gypsum boards and screws"),
    (2, "Electrical rough-in", "Electrical", "Cables, conduits, boxes and fasteners"),
    (2, "Ceiling framework", "Ceiling", "Ceiling channels, hangers and anchors"),
    (3, "Finishing and touch-ups", "Finishing", "Putty, primer, paint and consumables"),
    (3, "Quality inspection and snag closure", "Quality", "Testing tools and snag consumables"),
    (3, "Handover preparation", "Handover", "Cleaning material, labels and handover documents"),
]


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
    super_admin = _ensure_super_admin(db)
    template = db.scalar(select(ExecutionTemplate).where(ExecutionTemplate.name == "Interior Fit-out · 3 Day Standard"))
    if not template:
        template = ExecutionTemplate(name="Interior Fit-out · 3 Day Standard", project_type="Interior Fit-out", duration_days=3, created_by=super_admin.id)
        db.add(template)
        db.flush()
        for order, (day_no, title, category, materials) in enumerate(DEFAULT_TEMPLATE_TASKS, 1):
            db.add(ExecutionTemplateTask(template_id=template.id, day_no=day_no, title=title, category=category, priority="medium", instructions="Complete as per approved drawings and site safety requirements.", materials_required=materials, material_reminder=True, reminder_lead_days=1, sort_order=order))
    db.commit()
