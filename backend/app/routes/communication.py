import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.auth import current_user, require_roles
from app.database import get_db
from app.models import CommunicationLog, ContractorCategory, ContractorRelationship, ExecutionProject, ExecutionProjectContractor, User, UserRole, Vendor, VendorCategory, VendorContact
from app.schemas.requests import CommunicationLogIn, ContractorProfileIn, ContractorRelationshipIn, ProjectVendorIn, VendorCategoryIn, VendorContactIn

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

@router.get("")
def get_hub(user: User = Depends(current_user), db: Session = Depends(get_db)):
    projects = visible_execution_projects(user, db)
    project_ids = {project.id for project in projects}
    links_query = select(ExecutionProjectContractor)
    if user.role in {UserRole.project_manager, UserRole.supervisor}:
        links_query = links_query.where(ExecutionProjectContractor.project_id.in_(project_ids)) if project_ids else links_query.where(False)
    project_links = db.scalars(links_query).all()
    relationships = db.scalars(select(ContractorRelationship).order_by(ContractorRelationship.created_at)).all()
    # The Communication Hub is a company directory. Supervisors can see all active/inactive
    # contractors, while project links below remain limited to their assigned projects.
    vendor_query = select(Vendor).order_by(Vendor.created_at.desc(), Vendor.name)
    vendors = db.scalars(vendor_query).all()
    vendor_ids = {vendor.id for vendor in vendors}
    contacts = db.scalars(select(VendorContact).where(VendorContact.vendor_id.in_(vendor_ids)).order_by(VendorContact.is_primary.desc(), VendorContact.name)).all() if vendor_ids else []
    logs = db.scalars(select(CommunicationLog).where(CommunicationLog.vendor_id.in_(vendor_ids)).order_by(CommunicationLog.created_at.desc()).limit(200)).all() if vendor_ids else []
    log_users = {item.id: item.name for item in db.scalars(select(User).where(User.id.in_({log.created_by for log in logs}))).all()} if logs else {}
    categories = db.scalars(select(VendorCategory).where(VendorCategory.active.is_(True)).order_by(VendorCategory.name)).all()
    category_by_id = {item.id: item.name for item in categories}
    category_links = db.scalars(select(ContractorCategory).where(ContractorCategory.vendor_id.in_(vendor_ids))).all() if vendor_ids else []
    category_ids_by_vendor = {}
    for link in category_links:
        category_ids_by_vendor.setdefault(link.vendor_id, []).append(link.category_id)
    visible_relationships = [item for item in relationships if item.main_contractor_id in vendor_ids and item.subcontractor_id in vendor_ids]
    return {
        "vendors": [{"id": str(v.id), "name": v.name, "category": v.category, "category_ids": [str(item) for item in category_ids_by_vendor.get(v.id, [])], "categories": [category_by_id[item] for item in category_ids_by_vendor.get(v.id, []) if item in category_by_id] or [v.category], "status": v.status, "engagement_type": v.engagement_type, "email": v.email, "address": v.address, "gst_number": v.gst_number, "notes": v.notes, "created_at": v.created_at.isoformat()} for v in vendors],
        "contacts": [{"id": str(c.id), "vendor_id": str(c.vendor_id), "name": c.name, "designation": c.designation, "phone": c.phone, "whatsapp": c.whatsapp, "is_primary": c.is_primary} for c in contacts],
        "relationships": [{"id": str(r.id), "main_contractor_id": str(r.main_contractor_id), "subcontractor_id": str(r.subcontractor_id)} for r in visible_relationships],
        "categories": [{"id": str(c.id), "name": c.name} for c in categories],
        "projects": [{"id": str(p.id), "name": p.name, "status": p.status} for p in projects],
        "project_vendors": [{"id": str(link.id), "project_id": str(link.project_id), "vendor_id": str(link.contractor_id)} for link in project_links],
        "logs": [{"id": str(log.id), "vendor_id": str(log.vendor_id), "contact_id": str(log.contact_id) if log.contact_id else None, "project_id": str(log.execution_project_id) if log.execution_project_id else None, "channel": log.channel, "note": log.note, "created_by_name": log_users.get(log.created_by, "SiteOps user"), "created_at": log.created_at.isoformat()} for log in logs],
    }


@router.put("/contractors/{vendor_id}")
def update_contractor(vendor_id: uuid.UUID, payload: ContractorProfileIn, _: User = Depends(require_roles(*MANAGER_ROLES)), db: Session = Depends(get_db)):
    vendor = db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(404, "Contractor not found.")
    if payload.status not in VALID_STATUSES:
        raise HTTPException(400, "Invalid contractor status.")
    if payload.engagement_type not in {"main", "exclusive_subcontractor", "independent"}:
        raise HTTPException(400, "Invalid contractor engagement type.")
    categories = db.scalars(select(VendorCategory).where(VendorCategory.id.in_(payload.category_ids), VendorCategory.active.is_(True))).all() if payload.category_ids else []
    if len(categories) != len(set(payload.category_ids)):
        raise HTTPException(400, "One or more contractor categories are invalid.")
    vendor.name = payload.name.strip()
    vendor.status = payload.status
    vendor.engagement_type = payload.engagement_type
    if payload.status == "inactive" and payload.engagement_type == "main":
        child_ids = list(db.scalars(select(ContractorRelationship.subcontractor_id).where(ContractorRelationship.main_contractor_id == vendor.id)).all())
        if child_ids:
            db.query(Vendor).filter(Vendor.id.in_(child_ids), Vendor.engagement_type == "exclusive_subcontractor").update({Vendor.status: "inactive"}, synchronize_session=False)
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
        raise HTTPException(400, "A contractor cannot be its own subcontractor.")
    if not db.get(Vendor, payload.main_contractor_id) or not db.get(Vendor, payload.subcontractor_id):
        raise HTTPException(404, "Contractor not found.")
    reverse = db.scalar(select(ContractorRelationship).where(ContractorRelationship.main_contractor_id == payload.subcontractor_id, ContractorRelationship.subcontractor_id == payload.main_contractor_id))
    if reverse:
        raise HTTPException(409, "This link would create a circular contractor relationship.")
    subcontractor = db.get(Vendor, payload.subcontractor_id)
    subcontractor.engagement_type = "exclusive_subcontractor"
    item = ContractorRelationship(**payload.model_dump(), created_by=actor.id)
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This subcontractor is already linked to the main contractor.")
    return {"id": str(item.id)}


@router.delete("/relationships/{relationship_id}")
def delete_relationship(relationship_id: uuid.UUID, _: User = Depends(require_roles(*MANAGER_ROLES)), db: Session = Depends(get_db)):
    item = db.get(ContractorRelationship, relationship_id)
    if not item:
        raise HTTPException(404, "Contractor relationship not found.")
    subcontractor = db.get(Vendor, item.subcontractor_id)
    if subcontractor:
        subcontractor.engagement_type = "independent"
    db.delete(item)
    db.commit()
    return {"message": "Subcontractor converted to independent."}


@router.post("/categories")
def create_category(payload: VendorCategoryIn, actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)), db: Session = Depends(get_db)):
    item = VendorCategory(name=payload.name.strip(), created_by=actor.id)
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Category already exists.")
    return {"id": str(item.id), "name": item.name}


@router.post("/project-vendors")
def link_vendor(payload: ProjectVendorIn, actor: User = Depends(require_roles(*MANAGER_ROLES)), db: Session = Depends(get_db)):
    require_project(payload.project_id, actor, db)
    contractor = db.get(Vendor, payload.vendor_id)
    if not contractor:
        raise HTTPException(404, "Contractor not found.")
    if contractor.engagement_type == "exclusive_subcontractor":
        raise HTTPException(400, "Exclusive subcontractors inherit project access from their main contractor.")
    link = ExecutionProjectContractor(project_id=payload.project_id, contractor_id=payload.vendor_id, created_by=actor.id)
    db.add(link)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Contractor is already linked to this project.")
    return {"id": str(link.id)}


@router.post("/logs")
def add_log(payload: CommunicationLogIn, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    if payload.project_id:
        require_project(payload.project_id, actor, db)
    if actor.role == UserRole.supervisor:
        linked = db.scalar(select(ExecutionProjectContractor).where(ExecutionProjectContractor.project_id == payload.project_id, ExecutionProjectContractor.contractor_id == payload.vendor_id))
        if not linked:
            related_ids = {r.subcontractor_id for r in db.scalars(select(ContractorRelationship).where(ContractorRelationship.main_contractor_id == payload.vendor_id)).all()}
            related_ids.update({r.main_contractor_id for r in db.scalars(select(ContractorRelationship).where(ContractorRelationship.subcontractor_id == payload.vendor_id)).all()})
            linked = db.scalar(select(ExecutionProjectContractor).where(ExecutionProjectContractor.project_id == payload.project_id, ExecutionProjectContractor.contractor_id.in_(related_ids))) if related_ids else None
        if not linked:
            raise HTTPException(403, "Contractor is not assigned to this project.")
    log = CommunicationLog(**payload.model_dump(exclude={"project_id"}), execution_project_id=payload.project_id, created_by=actor.id)
    db.add(log)
    db.commit()
    return {"id": str(log.id)}
