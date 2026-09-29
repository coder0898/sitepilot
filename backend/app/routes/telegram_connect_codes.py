"""Admin-facing route to issue a Telegram connect code for a specific
employee or vendor contact - the missing generation half of U13's
`/start <token>` connect flow (`app.services.telegram_connect` only ever
consumed one; see that module's docstring). Admin/Super-Admin gated, same
as `channel_toggle.py`'s toggle route - issuing a code is an identity-
linking admin action.

Self-service (2026-09-29): the `/me/...` routes let any logged-in person
link or disconnect THEIR OWN Telegram from My Profile. They take no person
id at all - the target is always the session user's own employee profile -
and reuse the exact same generate/unlink code, so every link rule (hashed
one-time token, expiry, private chat, one chat <-> one person) applies.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user, require_roles
from app.database import get_db
from app.models import EmployeeProfile, User, UserRole
from app.services.telegram_connect import IssuedConnectCode, TelegramConnectService
from app.services.telegram_provider import TelegramProviderAdapter

router = APIRouter(prefix="/api/v2/telegram", tags=["v2-telegram-connect"])
ADMIN_ROLES = (UserRole.super_admin, UserRole.admin)


class ConnectCodeIn(BaseModel):
    employee_id: uuid.UUID | None = None
    vendor_contact_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _exactly_one_id(self):
        if (self.employee_id is None) == (self.vendor_contact_id is None):
            raise ValueError("Exactly one of employee_id or vendor_contact_id must be set.")
        return self


@router.post("/connect-code")
def generate_connect_code(
    payload: ConnectCodeIn,
    actor: User = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    issued = TelegramConnectService(db).generate_code(
        employee_id=payload.employee_id, vendor_contact_id=payload.vendor_contact_id,
    )
    return _code_response(issued)


def _code_response(issued: IssuedConnectCode) -> dict:
    # The raw token appears only in this response - the database holds its hash.
    username = TelegramProviderAdapter().bot_username()
    return {
        "code": issued.raw_token,
        "expires_at": issued.expires_at.isoformat(),
        "start_command": f"/start {issued.raw_token}",
        "link": f"https://t.me/{username}?start={issued.raw_token}" if username else None,
    }


class UnlinkIn(BaseModel):
    employee_id: uuid.UUID | None = None
    vendor_contact_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _exactly_one_id(self):
        if (self.employee_id is None) == (self.vendor_contact_id is None):
            raise ValueError("Exactly one of employee_id or vendor_contact_id must be set.")
        return self


@router.post("/unlink")
def unlink_telegram(
    payload: UnlinkIn,
    actor: User = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Frees this person's/contact's `telegram_chat_id` so a different
    identity can connect the same Telegram account. Never touches
    `active_channel`, role, membership, or any other field - see
    `TelegramConnectService.unlink_employee`/`unlink_vendor_contact`'s
    docstrings."""
    service = TelegramConnectService(db)
    if payload.employee_id is not None:
        profile = service.unlink_employee(employee_id=payload.employee_id, actor=actor)
        return {"employee_id": str(profile.id), "telegram_connected": bool(profile.telegram_chat_id)}
    contact = service.unlink_vendor_contact(vendor_contact_id=payload.vendor_contact_id, actor=actor)
    return {"vendor_contact_id": str(contact.id), "telegram_connected": bool(contact.telegram_chat_id)}


# ---- self-service (My Profile) ------------------------------------------


def _own_profile(db: Session, user: User) -> EmployeeProfile:
    profile = db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == user.id))
    if profile is None:
        raise HTTPException(404, "Your account has no employee profile to link Telegram to.")
    return profile


def _own_status(profile: EmployeeProfile) -> dict:
    return {
        "telegram_connected": bool(profile.telegram_chat_id),
        "telegram_chat_hint": f"•••{profile.telegram_chat_id[-4:]}" if profile.telegram_chat_id else None,
    }


@router.get("/me")
def my_telegram_status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _own_status(_own_profile(db, user))


@router.post("/me/connect-code")
def generate_my_connect_code(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """A one-time link for the session user's own profile. Refused (409)
    while they are already linked, same as the Admin route."""
    profile = _own_profile(db, user)
    return _code_response(TelegramConnectService(db).generate_code(employee_id=profile.id))


@router.post("/me/unlink")
def unlink_my_telegram(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Disconnects the session user's own Telegram - the same unlink (and
    audit row) an Admin uses, acting on themselves."""
    profile = TelegramConnectService(db).unlink_employee(employee_id=_own_profile(db, user).id, actor=user)
    return _own_status(profile)
