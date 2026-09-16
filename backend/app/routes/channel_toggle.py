"""U15 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md):
Admin/Super-Admin-only route to view and change any person's active
messaging channel, singly or in bulk, plus a read endpoint for the audit
history. Both gated identically - the audit history exposes actor and
target identities plus channel-change history, which is behavioral
metadata, not public data.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.database import get_db
from app.models import User, UserRole
from app.project_models import V2AuditEvent
from app.services.channel_toggle import ChannelToggleService, ChannelToggleTarget

router = APIRouter(prefix="/api/v2/channel-toggle", tags=["v2-channel-toggle"])
ADMIN_ROLES = (UserRole.super_admin, UserRole.admin)


class ChannelToggleTargetIn(BaseModel):
    employee_id: uuid.UUID | None = None
    vendor_contact_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _exactly_one_id(self):
        if (self.employee_id is None) == (self.vendor_contact_id is None):
            raise ValueError("Exactly one of employee_id or vendor_contact_id must be set.")
        return self


class ChannelToggleIn(BaseModel):
    targets: list[ChannelToggleTargetIn] = Field(min_length=1)
    channel: Literal["whatsapp", "telegram"]


def _result_json(result) -> dict:
    return {
        "employee_id": str(result.employee_id) if result.employee_id else None,
        "vendor_contact_id": str(result.vendor_contact_id) if result.vendor_contact_id else None,
        "success": result.success,
        "error": result.error,
    }


def _audit_json(row: V2AuditEvent) -> dict:
    return {
        "id": str(row.id),
        "actor_user_id": str(row.actor_user_id) if row.actor_user_id else None,
        "entity_type": row.entity_type,
        "entity_id": str(row.entity_id),
        "before": row.before_json,
        "after": row.after_json,
        "reason": row.reason,
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
    }


@router.post("")
def toggle_channel(
    payload: ChannelToggleIn,
    actor: User = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """A single-person toggle is just a one-item `targets` list - both
    shapes return one per-target result rather than raising on a
    business-rule failure, so a bulk batch's other targets are unaffected
    by one person's failure."""
    targets = [
        ChannelToggleTarget(employee_id=t.employee_id, vendor_contact_id=t.vendor_contact_id)
        for t in payload.targets
    ]
    results = ChannelToggleService(db).toggle(actor=actor, targets=targets, channel=payload.channel)
    db.commit()
    return {"results": [_result_json(r) for r in results]}


@router.get("/audit")
def channel_toggle_audit(
    actor: User = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
):
    rows = db.scalars(
        select(V2AuditEvent)
        .where(V2AuditEvent.action == "channel_toggled")
        .order_by(V2AuditEvent.occurred_at.desc())
        .limit(limit)
    ).all()
    return {"results": [_audit_json(row) for row in rows]}
