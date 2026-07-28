from datetime import datetime, timedelta, timezone
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserAccountEvent, UserRole
from app.services.supabase_auth import SupabaseAuthError, verify_access_token

bearer = HTTPBearer(auto_error=False)


def current_supabase_identity(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    """Validate a Supabase session without requiring a provisioned SiteOps user."""
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email verification session required.")
    try:
        return verify_access_token(credentials.credentials)
    except SupabaseAuthError as exc:
        if exc.status_code >= 500:
            raise HTTPException(status_code=exc.status_code, detail=exc.public_message) from exc
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Verification link expired. Request a new link.") from exc

def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required.")
    try:
        auth_identity = verify_access_token(credentials.credentials)
        supabase_user_id = uuid.UUID(auth_identity["id"])
    except SupabaseAuthError as exc:
        if exc.status_code >= 500:
            raise HTTPException(status_code=exc.status_code, detail=exc.public_message) from exc
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired. Please login again.") from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired. Please login again.") from exc

    user = db.scalar(select(User).where(User.supabase_user_id == supabase_user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your Supabase identity has not been provisioned in SiteOps. Contact an administrator.")
    if not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="This account is inactive. Contact your Admin or Super Admin.")
    now = datetime.now(timezone.utc)
    if not user.activated_at:
        user.activated_at = now
        db.add(UserAccountEvent(
            user_id=user.id,
            event_type="ACCOUNT_ACTIVATED",
            from_role=None,
            to_role=user.role.value,
            reason="Account activated on first authenticated portal session.",
            actor_id=user.id,
        ))
    if not user.last_login_at or user.last_login_at < now - timedelta(minutes=5):
        user.last_login_at = now
    if db.is_modified(user):
        db.commit()
    return user


def require_roles(*roles: UserRole):
    def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission for this action.")
        return user
    return dependency


def can_create_role(actor_role: UserRole, target_role: UserRole) -> bool:
    if actor_role == UserRole.super_admin:
        return target_role in {UserRole.admin, UserRole.project_manager, UserRole.supervisor, UserRole.internal_employee}
    if actor_role == UserRole.admin:
        return target_role in {UserRole.project_manager, UserRole.supervisor, UserRole.internal_employee}
    return False
