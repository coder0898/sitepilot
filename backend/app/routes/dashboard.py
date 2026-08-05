from fastapi import APIRouter, Depends
from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.database import get_db
from app.models import User, UserRole
from app.services.access_control import access_catalog, manageable_roles
from app.services.serializers import public_user

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return public_user(user, db)


@router.get("/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    users = []
    if user.role == UserRole.super_admin:
        statement = select(User).order_by(
            case(
                (User.role == UserRole.super_admin, 0),
                (User.role == UserRole.admin, 1),
                (User.role == UserRole.project_manager, 2),
                (User.role == UserRole.supervisor, 3),
                else_=4,
            ),
            User.name,
        )
        users = [public_user(item, db) for item in db.scalars(statement).all()]
    elif user.role == UserRole.admin:
        managed = manageable_roles(user.role)
        statement = select(User).where(or_(User.id == user.id, User.role.in_(managed))).order_by(User.active.desc(), User.name)
        users = [public_user(item, db) for item in db.scalars(statement).all()]
    elif user.role in {UserRole.project_manager, UserRole.supervisor}:
        statement = select(User).where(User.active.is_(True), User.role.in_([UserRole.project_manager, UserRole.supervisor])).order_by(User.name)
        users = [public_user(item, db) for item in db.scalars(statement).all()]

    if user.role in {UserRole.super_admin, UserRole.admin, UserRole.project_manager, UserRole.supervisor}:
        modules = ["projects", "execution", "communication", "users"]
    elif user.role == UserRole.internal_employee:
        # Execution is scoped server-side (list_project_tasks/get_project_task
        # in execution_tasks_v2.py) to only this actor's actively assigned
        # tasks - granting the module here is safe because the underlying
        # data is already filtered, not just the nav entry.
        modules = ["projects", "execution", "users"]
    else:
        modules = ["projects", "users"]

    return {
        "user": public_user(user, db),
        "users": users,
        "module_permissions": modules,
        "access_catalog": access_catalog(),
        "manageable_roles": [role.value for role in manageable_roles(user.role)],
    }
