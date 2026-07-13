from fastapi import APIRouter, Depends
from sqlalchemy import case, select
from sqlalchemy.orm import Session
from app.auth import current_user
from app.database import get_db
from app.models import RoleModulePermission, User, UserRole
from app.services.serializers import public_user

router = APIRouter(prefix="/api", tags=["dashboard"])

@router.get("/health")
def health(): return {"ok": True}

@router.get("/me")
def me(user: User = Depends(current_user)): return public_user(user)

@router.get("/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    users=[]
    if user.role in {UserRole.super_admin,UserRole.admin}:
        stmt=select(User).order_by(case((User.role==UserRole.super_admin,0),(User.role==UserRole.admin,1),(User.role==UserRole.project_manager,2),else_=3),User.created_at.desc())
        if user.role==UserRole.admin: stmt=stmt.where(User.role!=UserRole.super_admin)
        users=[public_user(item) for item in db.scalars(stmt).all()]
    elif user.role==UserRole.project_manager:
        users=[public_user(item) for item in db.scalars(select(User).where(User.active.is_(True),User.role.in_([UserRole.project_manager,UserRole.supervisor])).order_by(User.name)).all()]
    if user.role==UserRole.super_admin: modules=["execution","communication","users","permissions"]
    else:
        modules=[item.module_key for item in db.scalars(select(RoleModulePermission).where(RoleModulePermission.role==user.role.value,RoleModulePermission.can_view.is_(True))).all()]
        if not modules: modules=["execution","communication"]
    return {"user":public_user(user),"users":users,"module_permissions":modules}