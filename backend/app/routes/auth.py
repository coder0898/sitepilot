from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_supabase_identity
from app.database import get_db
from app.models import User, UserAccountEvent

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/provider")
def provider():
    return {
        "provider": "supabase",
        "passwords_stored_by_siteops": False,
        "recovery": "supabase_email",
    }


@router.post("/complete-activation")
def complete_activation(
    identity: dict = Depends(current_supabase_identity),
    db: Session = Depends(get_db),
):
    identity_id = identity.get("id")
    if not identity_id:
        raise HTTPException(401, "Supabase identity is incomplete.")
    try:
        supabase_user_id = uuid.UUID(str(identity_id))
    except ValueError as exc:
        raise HTTPException(401, "Supabase identity is invalid.") from exc
    user = db.scalar(select(User).where(User.supabase_user_id == supabase_user_id))
    if not user:
        raise HTTPException(404, "Approved SiteOps account not found.")
    if not user.active:
        raise HTTPException(403, "This account is offboarded and cannot be activated.")
    if not user.activated_at:
        user.activated_at = datetime.now(timezone.utc)
        db.add(UserAccountEvent(
            user_id=user.id,
            event_type="ACCOUNT_ACTIVATED",
            from_role=None,
            to_role=user.role.value,
            reason="Initial password configured through Supabase recovery.",
            actor_id=user.id,
        ))
        db.commit()
    return {"message": "Account activation completed."}