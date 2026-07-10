from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.auth import require_roles
from app.database import get_db
from app.models import RoleModulePermission, User, UserRole
from app.schemas.requests import ModulePermissionIn

router = APIRouter(prefix="/api/role-permissions", tags=["role-permissions"])
MODULES = ("communication", "users", "overview", "projects", "approvals", "today", "security")
MANAGED_ROLES = (UserRole.admin, UserRole.project_manager, UserRole.supervisor)
DEFAULTS = {"admin": {"communication", "users"}, "project_manager": {"communication"}, "supervisor": {"communication"}}


def matrix(db):
    saved = {(item.role, item.module_key): item.can_view for item in db.scalars(select(RoleModulePermission)).all()}
    return [{"role": role.value, "module_key": module, "can_view": saved.get((role.value, module), module in DEFAULTS[role.value]), "locked": module == "communication"} for role in MANAGED_ROLES for module in MODULES]


@router.get("")
def get_permissions(_: User = Depends(require_roles(UserRole.super_admin)), db: Session = Depends(get_db)):
    return {"modules": list(MODULES), "permissions": matrix(db)}


@router.put("")
def save_permissions(payload: ModulePermissionIn, actor: User = Depends(require_roles(UserRole.super_admin)), db: Session = Depends(get_db)):
    allowed_roles = {role.value for role in MANAGED_ROLES}
    incoming = {(item.role.value, item.module_key): item.can_view for item in payload.permissions}
    if any(role not in allowed_roles or module not in MODULES for role, module in incoming):
        raise HTTPException(400, "Invalid role permission entry.")
    for role in allowed_roles:
        incoming[(role, "communication")] = True
    existing = {(item.role, item.module_key): item for item in db.scalars(select(RoleModulePermission)).all()}
    for role in allowed_roles:
        for module in MODULES:
            value = incoming.get((role, module), False)
            item = existing.get((role, module))
            if item:
                item.can_view = value
                item.updated_by = actor.id
            else:
                db.add(RoleModulePermission(role=role, module_key=module, can_view=value, updated_by=actor.id))
    db.commit()
    return {"permissions": matrix(db)}


@router.post("/reset")
def reset_permissions(actor: User = Depends(require_roles(UserRole.super_admin)), db: Session = Depends(get_db)):
    db.query(RoleModulePermission).delete()
    for role, modules in DEFAULTS.items():
        for module in modules:
            db.add(RoleModulePermission(role=role, module_key=module, can_view=True, updated_by=actor.id))
    db.commit()
    return {"permissions": matrix(db)}