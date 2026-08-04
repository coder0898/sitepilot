import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import current_user, require_roles
from app.database import get_db
from app.models import CommunicationLog, ContractorCategory, ContractorRelationship, ExecutionProject, ExecutionProjectContractor, ExecutionTask, ExecutionTemplateTask, User, UserRole, Vendor, VendorCategory, VendorContact, VendorStatusHistory
from app.schemas.requests import CommunicationLogIn, ContractorProfileIn, ContractorRelationshipIn, ProjectVendorIn, VendorCategoryIn, VendorCategoryUpdateIn, VendorContactIn
from app.services.history import set_vendor_status

router = APIRouter(prefix="/api/communication-hub", tags=["communication-hub"])
MANAGER_ROLES = (UserRole.super_admin, UserRole.admin, UserRole.project_manager)
VALID_STATUSES = {"active", "inactive", "on_hold"}


def visible_execution_projects(user, db):
    stmt = select(ExecutionProject).order_by(ExecutionProject.created_at.desc())
    if user.role == UserRole.project_manager:
        stmt = stmt.where(ExecutionProject.project_manager_id == user.id)
    if user.role == UserRole.supervisor:
        stmt = stmt.where(ExecutionProject.supervisor_id == user.id)
    return db.scalars(stmt).all()


def allowed_project_ids(user, db):
    return {project.id for project in visible_execution_projects(user, db)}


def require_project(project_id, user, db):
    project = db.get(ExecutionProject, project_id)
    if not project or project_id not in allowed_project_ids(user, db):
        raise HTTPException(403, "Project is not assigned to you.")
    return project


def ensure_task_category_vendor_categories(db: Session) -> None:
    """Auto-creates a root-level, `service`-type VendorCategory for every
    distinct ExecutionTemplateTask.category value that doesn't already have
    a case-insensitive name match - so a vendor's capability picker always
    offers every real task category (Ceiling, Electrical, ...) without
    anyone having to pre-create it. This replaces the old, separate
    "Vendor Category Mapping" page's manual one-to-one linking step; the
    existing category picker/manager here remains the manual path for
    anything beyond the task-category set (e.g. material categories)."""
    task_categories = {
        (value or "").strip()
        for value in db.scalars(select(ExecutionTemplateTask.category)).all()
    }
    task_categories.discard("")
    if not task_categories:
        return
    existing_names = {
        name.lower() for name in db.scalars(select(VendorCategory.name)).all()
    }
    missing = [name for name in task_categories if name.lower() not in existing_names]
    if not missing:
        return
    for name in missing:
        db.add(VendorCategory(name=name, category_type="service"))
    try:
        db.commit()
    except IntegrityError:
        # Concurrent request already created one of these names - safe to
        # discard this attempt since the category now exists either way.
        db.rollback()


def require_main_vendor(vendor_id, db):
    vendor = db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(404, "Main vendor not found.")
    if vendor.engagement_type != "main":
        raise HTTPException(422, "The selected parent must be a main vendor.")
    if vendor.status != "active":
        raise HTTPException(409, "Only active main vendors can receive sub-vendors or new project assignments.")
    return vendor


def resolve_profile_parent(vendor, requested_parent_id, db):
    parent_id = requested_parent_id or vendor.parent_vendor_id
    if not parent_id:
        relationship = db.scalar(select(ContractorRelationship).where(ContractorRelationship.subcontractor_id == vendor.id))
        parent_id = relationship.main_contractor_id if relationship else None
    if not parent_id:
        raise HTTPException(422, "A parent vendor is required for every sub-vendor.")
    if parent_id == vendor.id:
        raise HTTPException(422, "A vendor cannot be its own parent.")
    require_main_vendor(parent_id, db)
    return parent_id


@router.get("")
def get_hub(user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_task_category_vendor_categories(db)
    projects = visible_execution_projects(user, db)
    project_ids = {project.id for project in projects}
    links_query = select(ExecutionProjectContractor)
    if user.role in {UserRole.project_manager, UserRole.supervisor}:
        links_query = links_query.where(ExecutionProjectContractor.project_id.in_(project_ids)) if project_ids else links_query.where(False)
    project_links = db.scalars(links_query).all()
    relationships = db.scalars(select(ContractorRelationship).order_by(ContractorRelationship.created_at)).all()
    vendors = db.scalars(select(Vendor).order_by(Vendor.created_at.desc(), Vendor.name)).all()
    vendor_ids = {vendor.id for vendor in vendors}
    contacts = db.scalars(select(VendorContact).where(VendorContact.vendor_id.in_(vendor_ids)).order_by(VendorContact.is_primary.desc(), VendorContact.name)).all() if vendor_ids else []
    logs = db.scalars(select(CommunicationLog).where(CommunicationLog.vendor_id.in_(vendor_ids)).order_by(CommunicationLog.created_at.desc()).limit(200)).all() if vendor_ids else []
    log_users = {item.id: item.name for item in db.scalars(select(User).where(User.id.in_({log.created_by for log in logs}))).all()} if logs else {}
    category_query = select(VendorCategory).order_by(VendorCategory.category_type, VendorCategory.parent_id.nullsfirst(), VendorCategory.name)
    if user.role == UserRole.supervisor:
        category_query = category_query.where(VendorCategory.active.is_(True))
    categories = db.scalars(category_query).all()
    category_by_id = {item.id: item.name for item in categories}
    parent_status_by_id = {vendor.id: vendor.status for vendor in vendors if vendor.engagement_type == "main"}
    contractor_category_counts = dict(db.execute(select(ContractorCategory.category_id, func.count()).group_by(ContractorCategory.category_id)).all())
    task_category_counts = {}
    for category_id, count in db.execute(select(ExecutionTask.category_id, func.count()).where(ExecutionTask.category_id.is_not(None)).group_by(ExecutionTask.category_id)).all():
        task_category_counts[category_id] = task_category_counts.get(category_id, 0) + count
    for category_id, count in db.execute(select(ExecutionTask.subcategory_id, func.count()).where(ExecutionTask.subcategory_id.is_not(None)).group_by(ExecutionTask.subcategory_id)).all():
        task_category_counts[category_id] = task_category_counts.get(category_id, 0) + count
    template_category_counts = {}
    for category_id, count in db.execute(select(ExecutionTemplateTask.category_id, func.count()).where(ExecutionTemplateTask.category_id.is_not(None)).group_by(ExecutionTemplateTask.category_id)).all():
        template_category_counts[category_id] = template_category_counts.get(category_id, 0) + count
    for category_id, count in db.execute(select(ExecutionTemplateTask.subcategory_id, func.count()).where(ExecutionTemplateTask.subcategory_id.is_not(None)).group_by(ExecutionTemplateTask.subcategory_id)).all():
        template_category_counts[category_id] = template_category_counts.get(category_id, 0) + count
    child_counts = dict(db.execute(select(VendorCategory.parent_id, func.count()).where(VendorCategory.parent_id.is_not(None)).group_by(VendorCategory.parent_id)).all())
    category_links = db.scalars(select(ContractorCategory).where(ContractorCategory.vendor_id.in_(vendor_ids))).all() if vendor_ids else []
    category_ids_by_vendor = {}
    for link in category_links:
        category_ids_by_vendor.setdefault(link.vendor_id, []).append(link.category_id)
    visible_relationships = [item for item in relationships if item.main_contractor_id in vendor_ids and item.subcontractor_id in vendor_ids]
    return {
        "vendors": [{
            "id": str(v.id), "name": v.name, "category": v.category,
            "category_ids": [str(item) for item in category_ids_by_vendor.get(v.id, [])],
            "categories": [category_by_id[item] for item in category_ids_by_vendor.get(v.id, []) if item in category_by_id] or [v.category],
            "status": v.status,
            "effective_status": "blocked_by_parent" if v.parent_vendor_id and parent_status_by_id.get(v.parent_vendor_id) != "active" else v.status,
            "blocked_by_parent": bool(v.parent_vendor_id and parent_status_by_id.get(v.parent_vendor_id) != "active"),
            "engagement_type": v.engagement_type,
            "parent_vendor_id": str(v.parent_vendor_id) if v.parent_vendor_id else None,
            "migration_status": v.migration_status,
            "email": v.email, "address": v.address, "gst_number": v.gst_number,
            "notes": v.notes, "created_at": v.created_at.isoformat(),
        } for v in vendors],
        "contacts": [{"id": str(c.id), "vendor_id": str(c.vendor_id), "name": c.name, "designation": c.designation, "phone": c.phone, "whatsapp": c.whatsapp, "is_primary": c.is_primary} for c in contacts],
        "relationships": [{"id": str(r.id), "main_contractor_id": str(r.main_contractor_id), "subcontractor_id": str(r.subcontractor_id)} for r in visible_relationships],
        "categories": [{
            "id": str(c.id), "name": c.name, "category_type": c.category_type,
            "parent_id": str(c.parent_id) if c.parent_id else None,
            "description": c.description, "active": c.active,
            "usage_count": contractor_category_counts.get(c.id, 0) + task_category_counts.get(c.id, 0) + template_category_counts.get(c.id, 0),
            "vendor_count": contractor_category_counts.get(c.id, 0),
            "task_count": task_category_counts.get(c.id, 0),
            "template_task_count": template_category_counts.get(c.id, 0),
            "child_count": child_counts.get(c.id, 0),
        } for c in categories],
        "projects": [{"id": str(p.id), "name": p.name, "status": p.status} for p in projects],
        "project_vendors": [{"id": str(link.id), "project_id": str(link.project_id), "vendor_id": str(link.contractor_id)} for link in project_links],
        "logs": [{"id": str(log.id), "vendor_id": str(log.vendor_id), "contact_id": str(log.contact_id) if log.contact_id else None, "project_id": str(log.execution_project_id) if log.execution_project_id else None, "channel": log.channel, "note": log.note, "created_by_name": log_users.get(log.created_by, "SiteOps user"), "created_at": log.created_at.isoformat()} for log in logs],
    }


@router.put("/contractors/{vendor_id}")
def update_contractor(vendor_id: uuid.UUID, payload: ContractorProfileIn, actor: User = Depends(require_roles(*MANAGER_ROLES)), db: Session = Depends(get_db)):
    vendor = db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(404, "Contractor not found.")
    if payload.status not in VALID_STATUSES:
        raise HTTPException(400, "Invalid contractor status.")
    requested_type = "sub_vendor" if payload.engagement_type == "exclusive_subcontractor" else payload.engagement_type
    if requested_type == "independent":
        raise HTTPException(422, "Independent sub-vendors are no longer supported. Select a parent vendor.")
    if requested_type not in {"main", "sub_vendor", "migration_pending"}:
        raise HTTPException(400, "Invalid contractor engagement type.")
    if requested_type == "migration_pending" and vendor.migration_status != "parent_required":
        raise HTTPException(422, "Only migrated legacy records can remain pending parent mapping.")
    if requested_type == "sub_vendor":
        vendor.parent_vendor_id = resolve_profile_parent(vendor, payload.parent_vendor_id, db)
        vendor.migration_status = "ready"
    elif requested_type == "main":
        if vendor.parent_vendor_id or db.scalar(select(ContractorRelationship).where(ContractorRelationship.subcontractor_id == vendor.id)):
            raise HTTPException(409, "A linked sub-vendor cannot be converted into a main vendor.")
        vendor.parent_vendor_id = None
        vendor.migration_status = "ready"
    categories = db.scalars(select(VendorCategory).where(VendorCategory.id.in_(payload.category_ids), VendorCategory.active.is_(True))).all() if payload.category_ids else []
    if len(categories) != len(set(payload.category_ids)):
        raise HTTPException(400, "One or more contractor categories are invalid.")
    previous_status = vendor.status
    vendor.name = payload.name.strip()
    set_vendor_status(db, vendor, payload.status, actor.id, "Vendor profile updated")
    vendor.engagement_type = requested_type

    # Parent status is inherited at read/assignment time; do not overwrite a
    # child's own lifecycle decision. Recover only legacy children that this
    # endpoint previously inactivated through the old cascade behaviour.
    if requested_type == "main" and previous_status != "active" and payload.status == "active":
        children = db.scalars(select(Vendor).where(Vendor.parent_vendor_id == vendor.id, Vendor.status == "inactive")).all()
        for child in children:
            latest = db.scalar(
                select(VendorStatusHistory)
                .where(VendorStatusHistory.vendor_id == child.id)
                .order_by(VendorStatusHistory.created_at.desc())
                .limit(1)
            )
            if latest and latest.reason == "Parent vendor was made inactive":
                set_vendor_status(db, child, "active", actor.id, "Recovered legacy parent-status cascade")
    vendor.email = payload.email or None
    vendor.address = payload.address or None
    vendor.gst_number = payload.gst_number or None
    vendor.notes = payload.notes or None
    vendor.category = categories[0].name if categories else "Other"
    db.query(ContractorCategory).filter(ContractorCategory.vendor_id == vendor.id).delete()
    db.add_all([ContractorCategory(vendor_id=vendor.id, category_id=category.id) for category in categories])
    db.commit()
    return {"id": str(vendor.id)}


@router.post("/contacts")
def create_contact(payload: VendorContactIn, actor: User = Depends(require_roles(*MANAGER_ROLES)), db: Session = Depends(get_db)):
    if not db.get(Vendor, payload.vendor_id):
        raise HTTPException(404, "Contractor not found.")
    if payload.is_primary:
        db.query(VendorContact).filter(VendorContact.vendor_id == payload.vendor_id).update({VendorContact.is_primary: False})
    contact = VendorContact(**payload.model_dump(), created_by=actor.id)
    db.add(contact)
    db.commit()
    return {"id": str(contact.id)}


@router.post("/relationships")
def create_relationship(payload: ContractorRelationshipIn, actor: User = Depends(require_roles(*MANAGER_ROLES)), db: Session = Depends(get_db)):
    if payload.main_contractor_id == payload.subcontractor_id:
        raise HTTPException(400, "A vendor cannot be its own sub-vendor.")
    require_main_vendor(payload.main_contractor_id, db)
    sub_vendor = db.get(Vendor, payload.subcontractor_id)
    if not sub_vendor:
        raise HTTPException(404, "Sub-vendor not found.")
    existing = db.scalar(select(ContractorRelationship).where(ContractorRelationship.subcontractor_id == sub_vendor.id))
    if existing:
        if existing.main_contractor_id == payload.main_contractor_id:
            raise HTTPException(409, "This sub-vendor is already linked to the selected parent.")
        raise HTTPException(409, "This sub-vendor already belongs to another parent vendor.")
    if sub_vendor.parent_vendor_id and sub_vendor.parent_vendor_id != payload.main_contractor_id:
        raise HTTPException(409, "This sub-vendor already belongs to another parent vendor.")
    sub_vendor.parent_vendor_id = payload.main_contractor_id
    sub_vendor.engagement_type = "sub_vendor"
    sub_vendor.migration_status = "ready"
    item = ContractorRelationship(**payload.model_dump(), created_by=actor.id)
    db.add(item)
    db.flush()
    db.execute(text("update vendor_parent_migration_candidates set resolved_at = now(), resolved_by = :actor where vendor_id = :vendor"), {"actor": actor.id, "vendor": sub_vendor.id})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This sub-vendor already has a parent vendor.")
    return {"id": str(item.id)}


@router.delete("/relationships/{relationship_id}")
def delete_relationship(relationship_id: uuid.UUID, _: User = Depends(require_roles(*MANAGER_ROLES)), db: Session = Depends(get_db)):
    if not db.get(ContractorRelationship, relationship_id):
        raise HTTPException(404, "Vendor relationship not found.")
    raise HTTPException(409, "A sub-vendor cannot be made independent. Reassign it to another parent or mark it inactive.")


@router.post("/categories")
def create_category(payload: VendorCategoryIn, actor: User = Depends(require_roles(*MANAGER_ROLES)), db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "Category name is required.")
    category_type = payload.category_type.strip().lower()
    if category_type not in {"material", "service"}:
        raise HTTPException(422, "Category type must be Material or Service.")
    parent = db.get(VendorCategory, payload.parent_id) if payload.parent_id else None
    if payload.parent_id and not parent:
        raise HTTPException(404, "Parent category not found.")
    if parent and not parent.active:
        raise HTTPException(409, "New subcategories require an active parent category.")
    if parent and parent.parent_id:
        raise HTTPException(422, "Only Main Category and Subcategory levels are supported.")
    if parent and parent.category_type != category_type:
        raise HTTPException(422, "Subcategory type must match its parent category.")
    duplicate = db.scalar(select(VendorCategory).where(func.lower(VendorCategory.name) == name.lower()))
    if duplicate:
        raise HTTPException(409, "A category with this name already exists.")
    item = VendorCategory(name=name, category_type=category_type, parent_id=payload.parent_id, description=(payload.description or "").strip() or None, created_by=actor.id)
    db.add(item)
    db.commit()
    return {"id": str(item.id), "name": item.name, "category_type": item.category_type, "parent_id": str(item.parent_id) if item.parent_id else None}


def category_usage_count(category_id: uuid.UUID, db: Session) -> int:
    vendor_links = db.scalar(select(func.count()).select_from(ContractorCategory).where(ContractorCategory.category_id == category_id)) or 0
    tasks = db.scalar(
        select(func.count()).select_from(ExecutionTask).where(
            or_(ExecutionTask.category_id == category_id, ExecutionTask.subcategory_id == category_id)
        )
    ) or 0
    template_tasks = db.scalar(
        select(func.count()).select_from(ExecutionTemplateTask).where(
            or_(ExecutionTemplateTask.category_id == category_id, ExecutionTemplateTask.subcategory_id == category_id)
        )
    ) or 0
    return vendor_links + tasks + template_tasks


@router.put("/categories/{category_id}")
def update_category(category_id: uuid.UUID, payload: VendorCategoryUpdateIn, actor: User = Depends(require_roles(*MANAGER_ROLES)), db: Session = Depends(get_db)):
    item = db.get(VendorCategory, category_id)
    if not item:
        raise HTTPException(404, "Category not found.")
    name = payload.name.strip()
    category_type = payload.category_type.strip().lower()
    if not name:
        raise HTTPException(422, "Category name is required.")
    if category_type not in {"material", "service"}:
        raise HTTPException(422, "Category type must be Material or Service.")
    if payload.parent_id == item.id:
        raise HTTPException(422, "A category cannot be its own parent.")

    parent = db.get(VendorCategory, payload.parent_id) if payload.parent_id else None
    if payload.parent_id and not parent:
        raise HTTPException(404, "Parent category not found.")
    if parent and parent.parent_id:
        raise HTTPException(422, "Only Main Category and Subcategory levels are supported.")
    if parent and parent.category_type != category_type:
        raise HTTPException(422, "Subcategory type must match its parent category.")
    if payload.active and parent and not parent.active:
        raise HTTPException(409, "Reactivate the parent category before this subcategory.")

    children = db.scalars(select(VendorCategory).where(VendorCategory.parent_id == item.id)).all()
    if children and (payload.parent_id or category_type != item.category_type):
        raise HTTPException(409, "A main category with subcategories cannot change level or type.")
    duplicate = db.scalar(
        select(VendorCategory).where(
            VendorCategory.id != item.id,
            func.lower(VendorCategory.name) == name.lower(),
        )
    )
    if duplicate:
        raise HTTPException(409, "A category with this name already exists.")

    item.name = name
    item.category_type = category_type
    item.parent_id = payload.parent_id
    item.description = (payload.description or "").strip() or None
    item.active = payload.active
    if not payload.active:
        for child in children:
            child.active = False
    db.commit()
    return {"id": str(item.id), "active": item.active}


@router.delete("/categories/{category_id}")
def delete_category(category_id: uuid.UUID, actor: User = Depends(require_roles(*MANAGER_ROLES)), db: Session = Depends(get_db)):
    item = db.get(VendorCategory, category_id)
    if not item:
        raise HTTPException(404, "Category not found.")
    child_count = db.scalar(select(func.count()).select_from(VendorCategory).where(VendorCategory.parent_id == item.id)) or 0
    if child_count:
        raise HTTPException(409, "Delete or archive the subcategories before deleting this main category.")
    if category_usage_count(item.id, db):
        raise HTTPException(409, "This category is already used. Archive it to preserve vendor and task history.")
    db.delete(item)
    db.commit()
    return {"message": "Category deleted."}

@router.post("/project-vendors")
def link_vendor(payload: ProjectVendorIn, actor: User = Depends(require_roles(*MANAGER_ROLES)), db: Session = Depends(get_db)):
    require_project(payload.project_id, actor, db)
    contractor = require_main_vendor(payload.vendor_id, db)
    if contractor.migration_status != "ready":
        raise HTTPException(409, "Resolve this vendor's parent migration before assigning it to a project.")
    link = ExecutionProjectContractor(project_id=payload.project_id, contractor_id=payload.vendor_id, created_by=actor.id)
    db.add(link)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Vendor is already linked to this project.")
    return {"id": str(link.id)}


@router.post("/logs")
def add_log(payload: CommunicationLogIn, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    if payload.project_id:
        require_project(payload.project_id, actor, db)
    if actor.role == UserRole.supervisor:
        linked = db.scalar(select(ExecutionProjectContractor).where(ExecutionProjectContractor.project_id == payload.project_id, ExecutionProjectContractor.contractor_id == payload.vendor_id))
        if not linked:
            vendor = db.get(Vendor, payload.vendor_id)
            parent_id = vendor.parent_vendor_id if vendor else None
            linked = db.scalar(select(ExecutionProjectContractor).where(ExecutionProjectContractor.project_id == payload.project_id, ExecutionProjectContractor.contractor_id == parent_id)) if parent_id else None
        if not linked:
            raise HTTPException(403, "Vendor is not assigned to this project.")
    log = CommunicationLog(**payload.model_dump(exclude={"project_id"}), execution_project_id=payload.project_id, created_by=actor.id)
    db.add(log)
    db.commit()
    return {"id": str(log.id)}