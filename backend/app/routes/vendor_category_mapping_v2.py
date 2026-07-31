
import uuid
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.database import get_db
from app.models import User, UserRole, VendorCategory, TaskVendorCategoryMapping, TaskVendorCategoryMappingAudit, ExecutionTemplateTask

router = APIRouter(prefix="/api/v2/vendor-category-mapping", tags=["vendor-category-mapping"])

@router.get("/task-categories")
def task_categories(db: Session = Depends(get_db)):
    rows = db.execute(select(ExecutionTemplateTask.category).distinct()).scalars().all()
    return {"items": [{"id": c, "name": c} for c in rows if c]}

@router.get("/vendor-categories")
def vendor_categories(db: Session = Depends(get_db)):
    rows = db.scalars(select(VendorCategory).where(VendorCategory.active.is_(True)).order_by(VendorCategory.name)).all()
    return {"items": [{"id": str(x.id), "name": x.name} for x in rows]}

@router.get("")
def mappings(db: Session = Depends(get_db)):
    rows = db.scalars(select(TaskVendorCategoryMapping)).all()
    return {"items": [{"id": str(x.id), "task_category_id": x.task_category, "vendor_category_id": str(x.vendor_category_id) if x.vendor_category_id else None} for x in rows]}

@router.post("")
def map_category(payload: dict, actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)), db: Session = Depends(get_db)):
    task = payload["task_category_id"]
    vendor_id = uuid.UUID(str(payload["vendor_category_id"]))
    existing = db.scalar(select(TaskVendorCategoryMapping).where(TaskVendorCategoryMapping.task_category == task))
    action = "map"
    old = None
    if existing:
        old = existing.vendor_category_id
        existing.vendor_category_id = vendor_id
        mapping = existing
        action = "remap"
    else:
        mapping = TaskVendorCategoryMapping(task_category=task, vendor_category_id=vendor_id, created_by=actor.id)
        db.add(mapping)
    db.add(TaskVendorCategoryMappingAudit(task_category=task, action=action, old_vendor_category_id=old, new_vendor_category_id=vendor_id, changed_by=actor.id))
    db.commit()
    return {"ok": True}

@router.delete("/{task_category}")
def unmap_category(task_category: str, actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)), db: Session = Depends(get_db)):
    existing = db.scalar(select(TaskVendorCategoryMapping).where(TaskVendorCategoryMapping.task_category == task_category))
    if existing:
        db.add(TaskVendorCategoryMappingAudit(task_category=task_category, action="unmap", old_vendor_category_id=existing.vendor_category_id, changed_by=actor.id))
        db.delete(existing)
        db.commit()
    return {"ok": True}
