import uuid

from sqlalchemy.orm import Session

from app.models import ExecutionTask, ExecutionTaskStatusHistory, Vendor, VendorStatusHistory


def record_new_task(db: Session, task: ExecutionTask, actor_id: uuid.UUID | None, reason: str = "Task created") -> None:
    db.add(ExecutionTaskStatusHistory(task_id=task.id, from_status=None, to_status=task.status, reason=reason, changed_by=actor_id))


def set_task_status(db: Session, task: ExecutionTask, status: str, actor_id: uuid.UUID | None, reason: str | None = None) -> bool:
    previous = task.status
    if previous == status:
        return False
    task.status = status
    db.add(ExecutionTaskStatusHistory(task_id=task.id, from_status=previous, to_status=status, reason=reason, changed_by=actor_id))
    return True


def record_new_vendor(db: Session, vendor: Vendor, actor_id: uuid.UUID | None, reason: str = "Vendor created") -> None:
    db.add(VendorStatusHistory(vendor_id=vendor.id, from_status=None, to_status=vendor.status, reason=reason, changed_by=actor_id))


def set_vendor_status(db: Session, vendor: Vendor, status: str, actor_id: uuid.UUID | None, reason: str | None = None) -> bool:
    previous = vendor.status
    if previous == status:
        return False
    vendor.status = status
    db.add(VendorStatusHistory(vendor_id=vendor.id, from_status=previous, to_status=status, reason=reason, changed_by=actor_id))
    return True