import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.database import get_db
from app.models import ProjectTask, TaskStatus, User, UserRole, Vendor
from app.services.serializers import project_row, public_user, public_vendor, task_row, visible_projects_query

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return public_user(user)


@router.get("/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    users = []
    if user.role in {UserRole.super_admin, UserRole.admin}:
        stmt = select(User).order_by(
            case(
                (User.role == UserRole.super_admin, 0),
                (User.role == UserRole.admin, 1),
                (User.role == UserRole.project_manager, 2),
                else_=3,
            ),
            User.created_at.desc(),
        )
        if user.role == UserRole.admin:
            stmt = stmt.where(User.role != UserRole.super_admin)
        users = [public_user(item) for item in db.scalars(stmt).all()]
    elif user.role == UserRole.project_manager:
        # Project Managers need active supervisors in the project creation/edit form.
        stmt = (
            select(User)
            .where(User.active.is_(True), User.role.in_([UserRole.supervisor, UserRole.project_manager]))
            .order_by(
                case((User.role == UserRole.project_manager, 0), else_=1),
                User.created_at.desc(),
            )
        )
        users = [public_user(item) for item in db.scalars(stmt).all()]

    vendors = [public_vendor(vendor) for vendor in db.scalars(select(Vendor).order_by(Vendor.created_at.desc())).all()]
    projects = [project_row(project, db) for project in db.scalars(visible_projects_query(user)).all()]
    review_tasks = []
    if user.role != UserRole.supervisor:
        allowed_project_ids = [uuid.UUID(project["id"]) for project in projects]
        if allowed_project_ids:
            review_tasks = [
                task_row(task)
                for task in db.scalars(
                    select(ProjectTask)
                    .where(ProjectTask.project_id.in_(allowed_project_ids), ProjectTask.status == TaskStatus.submitted)
                    .order_by(ProjectTask.submitted_at.desc().nullslast())
                ).all()
            ]
    return {"user": public_user(user), "users": users, "vendors": vendors, "projects": projects, "review_tasks": review_tasks}


