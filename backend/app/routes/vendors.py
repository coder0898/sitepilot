import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.database import get_db
from app.models import ExecutionTask, ProjectTask, User, UserRole, Vendor
from app.schemas.requests import VendorIn
from app.services.serializers import public_vendor

router = APIRouter(prefix="/api/vendors", tags=["vendors"])


@router.post("")
def create_vendor(payload: VendorIn, actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin, UserRole.project_manager)), db: Session = Depends(get_db)):
    vendor = Vendor(**payload.model_dump(), created_by=actor.id)
    db.add(vendor)
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
def delete_vendor(vendor_id: uuid.UUID, _: User = Depends(require_roles(UserRole.super_admin, UserRole.admin, UserRole.project_manager)), db: Session = Depends(get_db)):
    vendor = db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(404, "Vendor not found.")
    db.query(ProjectTask).filter(ProjectTask.vendor_id == vendor_id).update({ProjectTask.vendor_id: None})
    db.query(ExecutionTask).filter(ExecutionTask.assigned_subcontractor_id == vendor_id).update({ExecutionTask.assigned_subcontractor_id: None}, synchronize_session=False)
    db.query(ExecutionTask).filter(ExecutionTask.assigned_contractor_id == vendor_id).update({ExecutionTask.assigned_contractor_id: None, ExecutionTask.assigned_subcontractor_id: None}, synchronize_session=False)
    db.delete(vendor)
    db.commit()
    return {"message": "Vendor deleted."}

