from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import ExecutionTemplate, ExecutionTemplateTask, User, UserRole

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

def ensure_seed_data(db: Session) -> None:
    super_admin = db.scalar(select(User).where(User.email == "superadmin@siteops.local"))
    if super_admin:
        super_admin.name = "Developer Super Admin"
        super_admin.password_hash = "plain:admin123"
        super_admin.role = UserRole.super_admin
        super_admin.active = True
    else:
        super_admin = User(name="Developer Super Admin", email="superadmin@siteops.local", password_hash="plain:admin123", role=UserRole.super_admin)
        db.add(super_admin)
    db.flush()
    template = db.scalar(select(ExecutionTemplate).where(ExecutionTemplate.name == "Interior Fit-out · 3 Day Standard"))
    if not template:
        template = ExecutionTemplate(name="Interior Fit-out · 3 Day Standard", project_type="Interior Fit-out", duration_days=3, created_by=super_admin.id)
        db.add(template)
        db.flush()
        for order, (day_no, title, category, materials) in enumerate(DEFAULT_TEMPLATE_TASKS, 1):
            db.add(ExecutionTemplateTask(template_id=template.id, day_no=day_no, title=title, category=category, priority="medium", instructions="Complete as per approved drawings and site safety requirements.", materials_required=materials, material_reminder=True, reminder_lead_days=1, sort_order=order))
    db.commit()

