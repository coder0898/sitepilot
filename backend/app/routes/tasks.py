from datetime import date, datetime, timezone
import shutil
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.config import settings
from app.database import get_db
from app.models import Project, ProjectTask, TaskStatus, User, UserRole
from app.schemas.requests import ReviewIn, TaskAdminIn
from app.services.serializers import ensure_project_access, task_row

router = APIRouter(prefix="/api", tags=["tasks"])


@router.get("/supervisor/today")
def supervisor_today(user: User = Depends(require_roles(UserRole.supervisor)), db: Session = Depends(get_db)):
    today = date.today()
    tasks = db.scalars(
        select(ProjectTask)
        .join(Project)
        .where(
            Project.supervisor_id == user.id,
            or_(
                ProjectTask.scheduled_date == today,
                and_(ProjectTask.scheduled_date < today, ProjectTask.status.in_([TaskStatus.pending, TaskStatus.in_progress, TaskStatus.submitted, TaskStatus.delayed, TaskStatus.blocked, TaskStatus.rejected])),
            ),
        )
        .order_by(ProjectTask.scheduled_date, ProjectTask.day_no)
    ).all()
    return [task_row(task) for task in tasks]


@router.put("/tasks/{task_id}")
def update_task_admin(task_id: uuid.UUID, payload: TaskAdminIn, actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin, UserRole.project_manager)), db: Session = Depends(get_db)):
    task = db.get(ProjectTask, task_id)
    ensure_project_access(db.get(Project, task.project_id) if task else None, actor)
    for key, value in payload.model_dump().items():
        setattr(task, key, value)
    db.commit()
    return task_row(task)


@router.post("/tasks/{task_id}/supervisor-update")
def supervisor_update(
    task_id: uuid.UUID,
    status: Annotated[TaskStatus, Form()],
    supervisor_note: Annotated[str | None, Form()] = None,
    delay_reason: Annotated[str | None, Form()] = None,
    proof_url: Annotated[str | None, Form()] = None,
    proof_file: Annotated[UploadFile | None, File()] = None,
    user: User = Depends(require_roles(UserRole.supervisor)),
    db: Session = Depends(get_db),
):
    task = db.get(ProjectTask, task_id)
    project = ensure_project_access(db.get(Project, task.project_id) if task else None, user)
    if project.supervisor_id != user.id:
        raise HTTPException(403, "Task is not assigned to you.")
    if proof_file and proof_file.filename:
        if not (proof_file.content_type or "").startswith("image/"):
            raise HTTPException(422, "Proof upload must be an image file.")
        suffix = Path(proof_file.filename).suffix.lower() or ".jpg"
        if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".heic"}:
            suffix = ".jpg"
        filename = f"{uuid.uuid4()}{suffix}"
        target = Path(settings.upload_dir) / filename
        with target.open("wb") as output:
            shutil.copyfileobj(proof_file.file, output)
        task.proof_url = f"/uploads/task-proofs/{filename}"
    elif proof_url:
        task.proof_url = proof_url
    task.status = TaskStatus.submitted if status == TaskStatus.submitted else status
    task.supervisor_note = supervisor_note
    task.delay_reason = delay_reason
    if task.status == TaskStatus.submitted:
        task.submitted_at = datetime.now(timezone.utc)
    db.commit()
    return task_row(task)


@router.post("/tasks/{task_id}/review")
def review_task(task_id: uuid.UUID, payload: ReviewIn, actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin, UserRole.project_manager)), db: Session = Depends(get_db)):
    task = db.get(ProjectTask, task_id)
    ensure_project_access(db.get(Project, task.project_id) if task else None, actor)
    if payload.action == "approve":
        task.status = TaskStatus.completed
        task.approved_at = datetime.now(timezone.utc)
        task.approved_by = actor.id
        task.rejection_reason = None
    elif payload.action == "reject":
        reason = (payload.rejection_reason or "").strip()
        if not reason:
            raise HTTPException(422, "Rejection reason is required.")
        task.status = TaskStatus.rejected
        task.rejection_reason = reason
    else:
        raise HTTPException(422, "Review action must be approve or reject.")
    db.commit()
    return task_row(task)
