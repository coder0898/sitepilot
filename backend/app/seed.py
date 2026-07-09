from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TaskTemplate, User, UserRole

TASKS = [
    (1, 1, "Site handover, measurement verification, and access confirmation", "Project Setup", None, "Confirm access, working hours, lift rules, storage and society/site permissions."),
    (1, 2, "Vendor kickoff briefing with safety and schedule alignment", "Project Setup", None, "Brief all key vendors on the 45-day plan, safety, access rules and escalation process."),
    (1, 3, "Material storage zone and temporary protection setup", "Civil", "Civil", "Create a safe material storage area and protect finished/working surfaces from damage."),
    (2, 1, "Temporary lighting setup", "Electrical", "Electrical", "Install temporary lighting in primary work zones for safe execution."),
    (2, 2, "Temporary plug points and work power availability", "Electrical", "Electrical", "Confirm safe temporary power points are available to vendors."),
    (2, 3, "Initial floor level and civil condition check", "Civil", "Civil", "Check slab/floor level and note civil preparation requirements."),
    (3, 1, "Demolition or dismantling work start where applicable", "Civil", "Civil", "Start approved dismantling and isolate waste safely."),
    (3, 2, "Debris removal route and housekeeping plan confirmation", "Civil", "Civil", "Confirm debris route, lift timing and housekeeping frequency."),
    (3, 3, "Electrical chase marking and routing confirmation", "Electrical", "Electrical", "Mark electrical routes and confirm with layout."),
    (4, 1, "Civil repair and floor base preparation", "Civil", "Civil", "Prepare civil base and close visible repair points."),
    (4, 2, "Ceiling grid layout marking", "Ceiling", "Ceiling", "Mark ceiling grid based on approved reflected ceiling plan."),
    (4, 3, "HVAC indoor/outdoor routing coordination", "HVAC", "HVAC", "Coordinate AC piping, drain and outdoor unit routes."),
    (5, 1, "Partition layout marking and approval", "Carpentry", "Carpentry", "Mark partitions and confirm layout before execution."),
    (5, 2, "Electrical conduit work start", "Electrical", "Electrical", "Start conduit work after route approval."),
    (5, 3, "Fire line route verification", "Fire", "Fire", "Verify fire route and coordination requirements."),
]

CATEGORIES = ["Civil", "Electrical", "Carpentry", "Ceiling", "HVAC", "Fire", "IT", "Painting", "Flooring", "Glass", "Furniture", "Signage", "Housekeeping", "Quality", "Documentation", "Handover"]


def ensure_seed_data(db: Session) -> None:
    super_admin = db.scalar(select(User).where(User.email == "superadmin@siteops.local"))
    if super_admin:
        super_admin.name = "Developer Super Admin"
        super_admin.password_hash = "plain:admin123"
        super_admin.role = UserRole.super_admin
        super_admin.active = True
    else:
        db.add(User(
            name="Developer Super Admin",
            email="superadmin@siteops.local",
            password_hash="plain:admin123",
            role=UserRole.super_admin,
        ))

    if not db.scalar(select(TaskTemplate).limit(1)):
        seed_rows = list(TASKS)
        for day in range(6, 46):
            rotation = CATEGORIES[(day - 1) % len(CATEGORIES):] + CATEGORIES[:(day - 1) % len(CATEGORIES)]
            for offset, category in enumerate(rotation[:3]):
                seed_rows.append((
                    day,
                    offset + 1,
                    f"{category} execution checkpoint day {day}.{offset + 1}",
                    category,
                    category if category not in {"Quality", "Documentation", "Handover"} else None,
                    f"Complete the planned {category.lower()} activity for day {day} and report exceptions.",
                ))
        for day_no, sort_order, title, category, vendor_category, note in seed_rows:
            db.add(TaskTemplate(
                day_no=day_no,
                sort_order=sort_order,
                title=title,
                category=category,
                vendor_category=vendor_category,
                default_notes=note,
                description=note,
                supervisor_instruction="Confirm work status on site, coordinate with vendor, add note and proof.",
                pm_instruction="Check task note, proof and delay impact before approving.",
                proof_required="One clear site photo or proof reference.",
            ))
    db.commit()
