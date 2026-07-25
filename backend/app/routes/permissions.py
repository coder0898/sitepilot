from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_roles
from app.models import User, UserRole
from app.services.access_control import access_catalog

router = APIRouter(prefix="/api/role-permissions", tags=["role-permissions"])


@router.get("")
def get_permissions(_: User = Depends(require_roles(UserRole.super_admin, UserRole.admin))):
    return {"mutable": False, "roles": access_catalog()}


@router.put("")
def save_permissions(_: User = Depends(require_roles(UserRole.super_admin))):
    raise HTTPException(409, "Release 1 permissions are fixed by the approved role matrix.")


@router.post("/reset")
def reset_permissions(_: User = Depends(require_roles(UserRole.super_admin))):
    raise HTTPException(409, "Release 1 permissions are fixed by the approved role matrix.")
