import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.database import get_db
from app.models import ExecutionTask, ProjectTask, User, UserRole, Vendor
from app.schemas.requests import VendorIn
from app.services.serializers import public_vendor
from app.services.history import record_new_vendor

router = APIRouter(prefix="/api/vendors", tags=["vendors"])


@router.post("")
def create_vendor(payload: VendorIn, actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin, UserRole.project_manager)), db: Session = Depends(get_db)):
    vendor = Vendor(**payload.model_dump(), created_by=actor.id)
    db.add(vendor)
    db.flush()
    record_new_vendor(db, vendor, actor.id)
    db.commit()
    return public_vendor(vendor)


@router.put("/{vendor_id}")
def update_vendor(vendor_id: uuid.UUID, payload: VendorIn, _: User = Depends(require_roles(UserRole.super_admin, UserRole.admin, UserRole.project_manager)), db: Session = Depends(get_db)):
    vendor = db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(404, "Vendor not found.")
    for key, value in payload.model_dump().items():
        setattr(vendor, key, value)
    db.commit()
    return public_vendor(vendor)


@router.delete("/{vendor_id}")
def delete_vendor(vendor_id: uuid.UUID, actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin, UserRole.project_manager)), db: Session = Depends(get_db)):
    vendor = db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(404, "Vendor not found.")
    linked_sub_vendor_count = len(db.scalars(select(Vendor.id).where(Vendor.parent_vendor_id == vendor_id)).all())
    if linked_sub_vendor_count:
        noun = "sub-vendor" if linked_sub_vendor_count == 1 else "sub-vendors"
        verb = "is" if linked_sub_vendor_count == 1 else "are"
        raise HTTPException(409, f"This main vendor cannot be deleted because {linked_sub_vendor_count} {noun} {verb} still linked. Transfer or delete them first, or mark the main vendor inactive.")
    assigned_task_count = len(db.scalars(select(ExecutionTask.id).where(
        (ExecutionTask.assigned_contractor_id == vendor_id) | (ExecutionTask.assigned_subcontractor_id == vendor_id)
    )).all())
    if assigned_task_count:
        noun = "task" if assigned_task_count == 1 else "tasks"
        raise HTTPException(409, f"This vendor cannot be deleted because it is assigned to {assigned_task_count} execution {noun}. Reassign those tasks or mark the vendor inactive to preserve assignment history.")
    db.query(ProjectTask).filter(ProjectTask.vendor_id == vendor_id).update({ProjectTask.vendor_id: None})
    db.delete(vendor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This vendor cannot be deleted because it is still linked to operational records. Remove those links or mark the vendor inactive.")
    return {"message": "Vendor deleted."}

