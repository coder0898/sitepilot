"""Admin-facing route to issue a Telegram connect code for a specific
employee or vendor contact - the missing generation half of U13's
`/start <token>` connect flow (`app.services.telegram_connect` only ever
consumed one; see that module's docstring). Admin/Super-Admin gated, same
as `channel_toggle.py`'s toggle route - issuing a code is an identity-
linking admin action, not self-service.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.database import get_db
from app.models import User, UserRole
from app.services.telegram_connect import TelegramConnectService

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
    token = TelegramConnectService(db).generate_code(
        employee_id=payload.employee_id, vendor_contact_id=payload.vendor_contact_id,
    )
    return {
        "code": token.token,
        "expires_at": token.expires_at.isoformat(),
        "start_command": f"/start {token.token}",
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
