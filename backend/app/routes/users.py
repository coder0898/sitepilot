import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import can_create_role, hash_password, require_roles
from app.database import get_db
from app.models import ExecutionProject, ExecutionTask, User, UserRole
from app.schemas.requests import PasswordIn, UserCreateIn, UserUpdateIn
from app.services.serializers import public_user

router = APIRouter(prefix="/api/users", tags=["users"])


@router.post("")
def create_user(payload: UserCreateIn, actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)), db: Session = Depends(get_db)):
    if not can_create_role(actor.role, payload.role):
        raise HTTPException(403, "You cannot create this role.")
    if len(payload.password) < 6:
        raise HTTPException(422, "Temporary password must be at least 6 characters.")
    user = User(name=payload.name.strip(), email=payload.email.lower(), phone=payload.phone, role=payload.role, password_hash=hash_password(payload.password), created_by=actor.id)
    db.add(user)
    db.commit()
    return public_user(user)


@router.put("/{user_id}")
def update_user(user_id: uuid.UUID, payload: UserUpdateIn, actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target or target.role == UserRole.super_admin:
        raise HTTPException(403, "You cannot edit this user.")
    if actor.role == UserRole.admin and target.role == UserRole.admin:
        raise HTTPException(403, "You cannot edit this user.")
    target_role = payload.role or target.role
    if target_role != target.role and not can_create_role(actor.role, target_role):
        raise HTTPException(403, "You cannot assign this role.")
    target.name = payload.name.strip()
    target.email = payload.email.lower()
    target.phone = payload.phone
    target.role = target_role
    db.commit()
    return public_user(target)


@router.patch("/{user_id}/active")
def toggle_user(user_id: uuid.UUID, active: bool, actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target or target.role == UserRole.super_admin or (actor.role == UserRole.admin and target.role == UserRole.admin):
        raise HTTPException(403, "You cannot change this user.")
    target.active = active
    db.commit()
    return public_user(target)


@router.post("/{user_id}/reset-password")
def reset_user_password(user_id: uuid.UUID, payload: PasswordIn, actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target or target.role == UserRole.super_admin or (actor.role == UserRole.admin and target.role == UserRole.admin):
        raise HTTPException(403, "You cannot reset this user.")
    if len(payload.password) < 6:
        raise HTTPException(422, "Password must be at least 6 characters.")
    target.password_hash = hash_password(payload.password)
    db.commit()
    return {"message": "Password reset successfully."}




@router.delete("/{user_id}")
def delete_user(user_id: uuid.UUID, actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target or target.role == UserRole.super_admin:
        raise HTTPException(403, "You cannot delete this user.")
    if actor.role == UserRole.admin and target.role == UserRole.admin:
        raise HTTPException(403, "You cannot delete this user.")
    referenced = db.query(ExecutionProject).filter((ExecutionProject.project_manager_id == user_id) | (ExecutionProject.supervisor_id == user_id)).first() or db.query(ExecutionTask).filter(ExecutionTask.assigned_supervisor_id == user_id).first()
    if referenced:
        raise HTTPException(409, "Reassign this user's projects and tasks before deleting the account.")
    db.delete(target)
    db.commit()
    return {"message": "User deleted."}
