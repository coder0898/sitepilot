import uuid

from sqlalchemy.orm import Session

from app.models import ExecutionTask, ExecutionTaskAssignmentHistory, ExecutionTaskStatusHistory, Vendor, VendorStatusHistory


def record_new_task(db: Session, task: ExecutionTask, actor_id: uuid.UUID | None, reason: str = "Task created") -> None:
    db.add(ExecutionTaskStatusHistory(task_id=task.id, from_status=None, to_status=task.status, reason=reason, changed_by=actor_id))


def set_task_status(db: Session, task: ExecutionTask, status: str, actor_id: uuid.UUID | None, reason: str | None = None) -> bool:
    previous = task.status
    if previous == status:
        return False
    task.status = status
    db.add(ExecutionTaskStatusHistory(task_id=task.id, from_status=previous, to_status=status, reason=reason, changed_by=actor_id))
    return True



def record_task_assignment(
    db: Session,
    task: ExecutionTask,
    actor_id: uuid.UUID | None,
    previous_contractor_id: uuid.UUID | None,
    previous_subcontractor_id: uuid.UUID | None,
    reason: str | None = None,
) -> ExecutionTaskAssignmentHistory | None:
    current = (task.assigned_contractor_id, task.assigned_subcontractor_id)
    previous = (previous_contractor_id, previous_subcontractor_id)
    if current == previous:
        return None
    if current == (None, None):
        event_type = "TASK_UNASSIGNED"
    elif previous == (None, None):
        event_type = "TASK_ASSIGNED"
    else:
        event_type = "TASK_REASSIGNED"
    clean_reason = (reason or "").strip()
    if event_type != "TASK_ASSIGNED" and len(clean_reason) < 3:
        raise ValueError("Provide a reassignment reason of at least 3 characters.")
    item = ExecutionTaskAssignmentHistory(
        task_id=task.id,
        event_type=event_type,
        from_contractor_id=previous_contractor_id,
        from_subcontractor_id=previous_subcontractor_id,
        to_contractor_id=task.assigned_contractor_id,
        to_subcontractor_id=task.assigned_subcontractor_id,
        reason=clean_reason or "Initial assignment",
        changed_by=actor_id,
    )
    db.add(item)
    return item


def record_new_vendor(db: Session, vendor: Vendor, actor_id: uuid.UUID | None, reason: str = "Vendor created") -> None:    db.add(VendorStatusHistory(vendor_id=vendor.id, from_status=None, to_status=vendor.status, reason=reason, changed_by=actor_id))


def set_vendor_status(db: Session, vendor: Vendor, status: str, actor_id: uuid.UUID | None, reason: str | None = None) -> bool:
    previous = vendor.status
    if previous == status:
        return False
    vendor.status = status
    db.add(VendorStatusHistory(vendor_id=vendor.id, from_status=previous, to_status=status, reason=reason, changed_by=actor_id))
    return True