from datetime import date, timedelta
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user, require_roles
from app.database import get_db
from app.models import Project, ProjectTask, TaskStatus, User, UserRole
from app.schemas.requests import ProjectIn, ProjectUpdateIn
from app.services.projects import create_project_with_tasks, update_project_record
from app.services.serializers import ensure_project_access, task_row

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("")
def create_project(payload: ProjectIn, actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin, UserRole.project_manager)), db: Session = Depends(get_db)):
    return create_project_with_tasks(payload, actor, db)


@router.put("/{project_id}")
def update_project(project_id: uuid.UUID, payload: ProjectUpdateIn, actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin, UserRole.project_manager)), db: Session = Depends(get_db)):
    return update_project_record(project_id, payload, actor, db)


@router.delete("/{project_id}")
def delete_project(project_id: uuid.UUID, actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin, UserRole.project_manager)), db: Session = Depends(get_db)):
    project = ensure_project_access(db.get(Project, project_id), actor)
    db.delete(project)
    db.commit()
    return {"message": "Project deleted."}


@router.get("/{project_id}/days")
def project_days(project_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = ensure_project_access(db.get(Project, project_id), user)
    tasks = db.scalars(select(ProjectTask).where(ProjectTask.project_id == project.id).order_by(ProjectTask.day_no)).all()
    days = []
    for day_no in range(1, 46):
        day_tasks = [task for task in tasks if task.day_no == day_no]
        done = len([task for task in day_tasks if task.status == TaskStatus.completed])
        scheduled = project.start_date + timedelta(days=day_no - 1)
        days.append({"day_no": day_no, "date": scheduled.isoformat(), "total": len(day_tasks), "done": done})
    return days


@router.get("/{project_id}/tasks")
def project_tasks(project_id: uuid.UUID, date_value: date | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = ensure_project_access(db.get(Project, project_id), user)
    stmt = select(ProjectTask).where(ProjectTask.project_id == project.id).order_by(ProjectTask.day_no, ProjectTask.scheduled_date, ProjectTask.title)
    if date_value:
        stmt = stmt.where(ProjectTask.scheduled_date == date_value)
    return [task_row(task) for task in db.scalars(stmt).all()]
