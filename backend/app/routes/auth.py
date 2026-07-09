from datetime import datetime, timedelta, timezone
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import current_user, hash_password, make_token, verify_password
from app.database import get_db
from app.models import PasswordResetToken, User
from app.schemas.requests import ChangePasswordIn, LoginIn, ResetPasswordIn, ResetRequestIn
from app.services.serializers import public_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.email) == payload.email.lower()))
    if not user:
        raise HTTPException(401, "Invalid email or password.")
    if not user.active:
        raise HTTPException(401, "This account is inactive. Contact your Admin or Super Admin to reactivate access.")
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password.")
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    return {"token": make_token(user), "user": public_user(user)}


@router.post("/change-password")
def change_password(payload: ChangePasswordIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(400, "Current password was not correct.")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"message": "Password changed successfully."}


@router.post("/request-reset")
def request_reset(payload: ResetRequestIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.email) == payload.email.lower(), User.active.is_(True)))
    if not user:
        return {"message": "If this account exists, a reset link will be sent."}
    token = secrets.token_hex(24)
    db.add(PasswordResetToken(user_id=user.id, token=token, expires_at=datetime.now(timezone.utc) + timedelta(minutes=30)))
    db.commit()
    return {"message": "Reset token created for local testing.", "token": token}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordIn, db: Session = Depends(get_db)):
    reset = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token == payload.token, PasswordResetToken.used_at.is_(None), PasswordResetToken.expires_at > datetime.now(timezone.utc)))
    if not reset:
        raise HTTPException(400, "Reset token is invalid or expired.")
    user = db.get(User, reset.user_id)
    user.password_hash = hash_password(payload.password)
    reset.used_at = datetime.now(timezone.utc)
    db.commit()
    return {"message": "Password changed. You can login now."}
