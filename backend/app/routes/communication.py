"""Vendor Hub, backed by the siteops_v2 vendor schema.

Vendor Hub previously read and wrote the legacy `public.vendors` family
while every project-side feature (mapping, delegation, task assignment)
read `siteops_v2.vendors`. Nothing bridged the two except a one-time
import, so a vendor created here was invisible to projects until someone
re-ran that import by hand. This module now reads and writes the V2
tables directly, which is what closes that gap - a vendor created in
Vendor Hub is immediately mappable to a project.

Two consequences of that move are deliberate:

  * Capability categories are the flat `siteops_v2.capability_categories`
    list, seeded from template phases (see `_ensure_phase_categories` in
    project_vendors_v2.py). The legacy two-level, archivable
    `vendor_categories` tree is gone along with its create/update/delete
    endpoints: those labels drove no behaviour, while a capability only
    means something if its name matches a `Task.phase` exactly - which is
    what `TaskVendorAssignmentService._vendor_matches_task_category`
    compares against. One vocabulary, and it is the one delegation uses.

  * Vendor status changes are recorded as `V2AuditEvent` rows rather than
    the legacy `vendor_status_history` table (never surfaced in the UI).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import current_user, require_roles
from app.database import get_db
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership
from app.schemas.requests import CommunicationLogIn, ContractorProfileIn, ContractorRelationshipIn, VendorContactIn
from app.vendor_models import (
    ProjectVendor,
    V2CapabilityCategory,
    V2Vendor,
    V2VendorCapability,
    V2VendorContact,
    V2VendorNote,
)

router = APIRouter(prefix="/api/communication-hub", tags=["communication-hub"])
MANAGER_ROLES = (UserRole.super_admin, UserRole.admin, UserRole.project_manager)
VALID_STATUSES = {"active", "inactive", "on_hold"}


# Any authenticated non-admin sees only projects they hold an active
# membership on, matching `projects_v2.list_projects`' access model - no
# special case for PM/Supervisor, membership of any role grants visibility.
def visible_v2_projects(user, db):
    statement = select(V2Project).order_by(V2Project.updated_at.desc())
    if user.role not in {UserRole.super_admin, UserRole.admin}:
        employee = db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == user.id))
        if not employee:
            return []
        visible_ids = select(V2ProjectMembership.project_id).where(
            V2ProjectMembership.employee_id == employee.id,
            V2ProjectMembership.ends_at.is_(None),
        )
        statement = statement.where(V2Project.id.in_(visible_ids))
    return db.scalars(statement).all()


def require_project(project_id, user, db):
    project = db.get(V2Project, project_id)
    if not project or project_id not in {item.id for item in visible_v2_projects(user, db)}:
        raise HTTPException(403, "Project is not assigned to you.")
    return project


def record_vendor_audit(db: Session, actor: User, vendor: V2Vendor, action: str, reason: str, before=None, after=None) -> None:
    """Vendor-scoped audit row. `project_id` is left null - a vendor is not
    owned by any one project (mirrors projects_v2.add_audit's shape)."""
    db.add(V2AuditEvent(
        actor_user_id=actor.id,
        action=action,
        entity_type="vendor",
        entity_id=vendor.id,
        before_json=before,
        after_json=after,
        reason=reason,
    ))


def set_vendor_status(db: Session, actor: User, vendor: V2Vendor, status: str, reason: str) -> bool:
    if vendor.status == status:
        return False
    record_vendor_audit(db, actor, vendor, "vendor_status_changed", reason, {"status": vendor.status}, {"status": status})
    vendor.status = status
    return True


def require_main_vendor(vendor_id, db) -> V2Vendor:
    vendor = db.get(V2Vendor, vendor_id)
    if not vendor:
        raise HTTPException(404, "Main vendor not found.")
    if vendor.engagement_type != "main":
        raise HTTPException(422, "The selected parent must be a main vendor.")
    if vendor.status != "active":
        raise HTTPException(409, "Only active main vendors can receive sub-vendors or new project assignments.")
    return vendor


def resolve_profile_parent(vendor: V2Vendor, requested_parent_id, db):
    parent_id = requested_parent_id or vendor.parent_vendor_id
    if not parent_id:
        raise HTTPException(422, "A parent vendor is required for every sub-vendor.")
    if parent_id == vendor.id:
        raise HTTPException(422, "A vendor cannot be its own parent.")
    require_main_vendor(parent_id, db)
    return parent_id


def set_vendor_capabilities(db: Session, vendor_id: uuid.UUID, category_ids: list[uuid.UUID]) -> None:
    valid = db.scalars(select(V2CapabilityCategory.id).where(V2CapabilityCategory.id.in_(category_ids))).all() if category_ids else []
    if len(set(valid)) != len(set(category_ids)):
        raise HTTPException(400, "One or more capability categories are invalid.")
    db.query(V2VendorCapability).filter(V2VendorCapability.vendor_id == vendor_id).delete()
    db.add_all([V2VendorCapability(vendor_id=vendor_id, category_id=category_id) for category_id in set(category_ids)])


@router.get("")
def get_hub(user: User = Depends(current_user), db: Session = Depends(get_db)):
    projects = visible_v2_projects(user, db)
    project_ids = {project.id for project in projects}

    links_query = select(ProjectVendor.id, ProjectVendor.project_id, ProjectVendor.vendor_id)
    if user.role in {UserRole.project_manager, UserRole.supervisor}:
        links_query = links_query.where(ProjectVendor.project_id.in_(project_ids)) if project_ids else links_query.where(False)
    project_links = db.execute(links_query).all()

    vendors = db.scalars(select(V2Vendor).order_by(V2Vendor.created_at.desc(), V2Vendor.name)).all()
    vendor_ids = {vendor.id for vendor in vendors}
    contacts = db.scalars(
        select(V2VendorContact).where(V2VendorContact.vendor_id.in_(vendor_ids)).order_by(V2VendorContact.is_primary.desc(), V2VendorContact.name)
    ).all() if vendor_ids else []
    notes = db.scalars(
        select(V2VendorNote).where(V2VendorNote.vendor_id.in_(vendor_ids)).order_by(V2VendorNote.created_at.desc()).limit(200)
    ).all() if vendor_ids else []
    note_users = {
        item.id: item.name
        for item in db.scalars(select(User).where(User.id.in_({note.created_by for note in notes if note.created_by}))).all()
    } if notes else {}

    categories = db.scalars(select(V2CapabilityCategory).order_by(V2CapabilityCategory.name)).all()
    category_by_id = {item.id: item.name for item in categories}
    capability_links = db.scalars(select(V2VendorCapability).where(V2VendorCapability.vendor_id.in_(vendor_ids))).all() if vendor_ids else []
    category_ids_by_vendor: dict[uuid.UUID, list[uuid.UUID]] = {}
    for link in capability_links:
        category_ids_by_vendor.setdefault(link.vendor_id, []).append(link.category_id)
    vendor_counts = dict(db.execute(select(V2VendorCapability.category_id, func.count()).group_by(V2VendorCapability.category_id)).all())

    parent_status_by_id = {vendor.id: vendor.status for vendor in vendors if vendor.engagement_type == "main"}

    def vendor_categories(vendor_id):
        return [category_by_id[item] for item in category_ids_by_vendor.get(vendor_id, []) if item in category_by_id]

    return {
        "vendors": [{
            "id": str(v.id), "name": v.name,
            # Legacy `vendors.category` (a single free-text column) has no V2
            # equivalent - capabilities are the many-to-many replacement, so
            # this stays for display only, derived from the first of them.
            "category": (vendor_categories(v.id) or ["Other"])[0],
            "category_ids": [str(item) for item in category_ids_by_vendor.get(v.id, [])],
            "categories": vendor_categories(v.id) or ["Other"],
            "status": v.status,
            "effective_status": "blocked_by_parent" if v.parent_vendor_id and parent_status_by_id.get(v.parent_vendor_id) != "active" else v.status,
            "blocked_by_parent": bool(v.parent_vendor_id and parent_status_by_id.get(v.parent_vendor_id) != "active"),
            "engagement_type": v.engagement_type,
            "parent_vendor_id": str(v.parent_vendor_id) if v.parent_vendor_id else None,
            "contact_person": v.contact_person, "phone": v.phone, "whatsapp": v.whatsapp,
            "email": v.email, "address": v.address, "gst_number": v.gst_number,
            "notes": v.notes, "created_at": v.created_at.isoformat(),
        } for v in vendors],
        "contacts": [{"id": str(c.id), "vendor_id": str(c.vendor_id), "name": c.name, "designation": c.designation, "phone": c.phone, "whatsapp": c.whatsapp, "is_primary": c.is_primary} for c in contacts],
        # Sub-vendor parentage lives solely on `V2Vendor.parent_vendor_id`;
        # the legacy `contractor_relationships` mirror was never migrated
        # (see the V2 vendor migration header). Derived here so the existing
        # directory grouping keeps working off one authoritative source.
        "relationships": [
            {"id": str(v.id), "main_contractor_id": str(v.parent_vendor_id), "subcontractor_id": str(v.id)}
            for v in vendors if v.parent_vendor_id and v.parent_vendor_id in vendor_ids
        ],
        "categories": [{
            "id": str(c.id), "name": c.name,
            # The V2 capability list is flat and derived from template
            # phases, so these three keep the existing client contract
            # without pretending a hierarchy or archive state still exists.
            "category_type": "service", "parent_id": None, "description": None, "active": True,
            "usage_count": vendor_counts.get(c.id, 0),
            "vendor_count": vendor_counts.get(c.id, 0),
            "child_count": 0,
        } for c in categories],
        "projects": [{"id": str(p.id), "name": p.name, "status": p.status} for p in projects],
        # Notes now tag a real V2 project. The legacy column pointed at
        # `execution_projects`, which nothing had populated since project
        # creation moved to V2, so this list was previously always empty.
        "note_projects": [{"id": str(p.id), "name": p.name, "status": p.status} for p in projects],
        "project_vendors": [{"id": str(link.id), "project_id": str(link.project_id), "vendor_id": str(link.vendor_id)} for link in project_links],
        "logs": [{
            "id": str(note.id), "vendor_id": str(note.vendor_id),
            "contact_id": str(note.contact_id) if note.contact_id else None,
            "project_id": str(note.project_id) if note.project_id else None,
            "channel": note.channel, "note": note.note,
            "created_by_name": note_users.get(note.created_by, "SiteOps user"),
            "created_at": note.created_at.isoformat(),
        } for note in notes],
    }


@router.put("/contractors/{vendor_id}")
def update_contractor(vendor_id: uuid.UUID, payload: ContractorProfileIn, actor: User = Depends(require_roles(*MANAGER_ROLES)), db: Session = Depends(get_db)):
    vendor = db.get(V2Vendor, vendor_id)
    if not vendor:
        raise HTTPException(404, "Contractor not found.")
    if payload.status not in VALID_STATUSES:
        raise HTTPException(400, "Invalid contractor status.")
    requested_type = "sub_vendor" if payload.engagement_type == "exclusive_subcontractor" else payload.engagement_type
    if requested_type == "independent":
        raise HTTPException(422, "Independent sub-vendors are no longer supported. Select a parent vendor.")
    if requested_type not in {"main", "sub_vendor"}:
        raise HTTPException(400, "Invalid contractor engagement type.")
    if requested_type == "sub_vendor":
        vendor.parent_vendor_id = resolve_profile_parent(vendor, payload.parent_vendor_id, db)
    else:
        if db.scalar(select(V2Vendor.id).where(V2Vendor.parent_vendor_id == vendor.id)):
            raise HTTPException(409, "A linked sub-vendor cannot be converted into a main vendor.")
        vendor.parent_vendor_id = None

    previous_status = vendor.status
    vendor.name = payload.name.strip()
    set_vendor_status(db, actor, vendor, payload.status, "Vendor profile updated")
    vendor.engagement_type = requested_type

    # Parent status is inherited at read/assignment time; do not overwrite a
    # child's own lifecycle decision. Recover only legacy children that this
    # endpoint previously inactivated through the old cascade behaviour.
    if requested_type == "main" and previous_status != "active" and payload.status == "active":
        children = db.scalars(select(V2Vendor).where(V2Vendor.parent_vendor_id == vendor.id, V2Vendor.status == "inactive")).all()
        for child in children:
            set_vendor_status(db, actor, child, "active", "Recovered legacy parent-status cascade")

    vendor.email = payload.email or None
    vendor.address = payload.address or None
    vendor.gst_number = payload.gst_number or None
    vendor.notes = payload.notes or None
    set_vendor_capabilities(db, vendor.id, payload.category_ids)
    db.commit()
    return {"id": str(vendor.id)}


@router.post("/contacts")
def create_contact(payload: VendorContactIn, actor: User = Depends(require_roles(*MANAGER_ROLES)), db: Session = Depends(get_db)):
    if not db.get(V2Vendor, payload.vendor_id):
        raise HTTPException(404, "Contractor not found.")
    if payload.is_primary:
        db.query(V2VendorContact).filter(V2VendorContact.vendor_id == payload.vendor_id).update({V2VendorContact.is_primary: False})
    contact = V2VendorContact(**payload.model_dump())
    db.add(contact)
    db.commit()
    return {"id": str(contact.id)}


@router.post("/relationships")
def create_relationship(payload: ContractorRelationshipIn, actor: User = Depends(require_roles(*MANAGER_ROLES)), db: Session = Depends(get_db)):
    if payload.main_contractor_id == payload.subcontractor_id:
        raise HTTPException(400, "A vendor cannot be its own sub-vendor.")
    require_main_vendor(payload.main_contractor_id, db)
    sub_vendor = db.get(V2Vendor, payload.subcontractor_id)
    if not sub_vendor:
        raise HTTPException(404, "Sub-vendor not found.")
    if sub_vendor.parent_vendor_id:
        if sub_vendor.parent_vendor_id == payload.main_contractor_id:
            raise HTTPException(409, "This sub-vendor is already linked to the selected parent.")
        raise HTTPException(409, "This sub-vendor already belongs to another parent vendor.")
    if db.scalar(select(V2Vendor.id).where(V2Vendor.parent_vendor_id == sub_vendor.id)):
        raise HTTPException(409, "A vendor with its own sub-vendors cannot become a sub-vendor.")
    sub_vendor.parent_vendor_id = payload.main_contractor_id
    sub_vendor.engagement_type = "sub_vendor"
    record_vendor_audit(db, actor, sub_vendor, "vendor_parent_linked", "Sub-vendor linked to parent", None, {"parent_vendor_id": str(payload.main_contractor_id)})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This sub-vendor already has a parent vendor.")
    return {"id": str(sub_vendor.id)}


@router.delete("/relationships/{relationship_id}")
def delete_relationship(relationship_id: uuid.UUID, _: User = Depends(require_roles(*MANAGER_ROLES)), db: Session = Depends(get_db)):
    if not db.get(V2Vendor, relationship_id):
        raise HTTPException(404, "Vendor relationship not found.")
    raise HTTPException(409, "A sub-vendor cannot be made independent. Reassign it to another parent or mark it inactive.")


@router.post("/logs")
def add_log(payload: CommunicationLogIn, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    if not db.get(V2Vendor, payload.vendor_id):
        raise HTTPException(404, "Contractor not found.")
    if payload.project_id:
        require_project(payload.project_id, actor, db)
    if actor.role == UserRole.supervisor and payload.project_id:
        vendor = db.get(V2Vendor, payload.vendor_id)
        candidate_ids = [payload.vendor_id] + ([vendor.parent_vendor_id] if vendor and vendor.parent_vendor_id else [])
        linked = db.scalar(select(ProjectVendor.id).where(ProjectVendor.project_id == payload.project_id, ProjectVendor.vendor_id.in_(candidate_ids)))
        if not linked:
            raise HTTPException(403, "Vendor is not assigned to this project.")
    note = V2VendorNote(
        vendor_id=payload.vendor_id,
        contact_id=payload.contact_id,
        project_id=payload.project_id,
        channel=payload.channel,
        note=payload.note,
        created_by=actor.id,
    )
    db.add(note)
    db.commit()
    return {"id": str(note.id)}
