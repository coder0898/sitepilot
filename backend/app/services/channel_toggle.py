"""U15 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md,
KTD1/KTD2): Admin/Super-Admin changes a person's active messaging channel,
singly or in bulk, with every change recorded in the existing generic
audit table.

A single-person toggle is simply a one-item call to the same bulk path -
both return one per-target result rather than raising on a business-rule
failure (missing `telegram_chat_id`), so a failure for one person in a
bulk batch never aborts the rest, and the single-person case reads its
own outcome the same way.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import EmployeeProfile
from app.project_models import V2AuditEvent
from app.vendor_models import V2VendorContact

_VALID_CHANNELS = ("whatsapp", "telegram")


class ChannelToggleTarget:
    """One target of a toggle call. Exactly one of `employee_id` /
    `vendor_contact_id` is set, mirroring `MessageDelivery`'s own
    exclusive-recipient-pair convention."""

    def __init__(self, *, employee_id: uuid.UUID | None = None, vendor_contact_id: uuid.UUID | None = None):
        self.employee_id = employee_id
        self.vendor_contact_id = vendor_contact_id


class ChannelToggleResult:
    def __init__(self, *, target: ChannelToggleTarget, success: bool, error: str | None = None):
        self.employee_id = target.employee_id
        self.vendor_contact_id = target.vendor_contact_id
        self.success = success
        self.error = error


class ChannelToggleService:
    def __init__(self, db: Session):
        self.db = db

    def toggle(self, *, actor, targets: list[ChannelToggleTarget], channel: str) -> list[ChannelToggleResult]:
        if channel not in _VALID_CHANNELS:
            raise ValueError(f"Unsupported channel: {channel!r}")
        return [self._toggle_one(actor=actor, target=target, channel=channel) for target in targets]

    def _toggle_one(self, *, actor, target: ChannelToggleTarget, channel: str) -> ChannelToggleResult:
        if target.employee_id is not None:
            row = self.db.get(EmployeeProfile, target.employee_id)
            entity_type = "employee"
        else:
            row = self.db.get(V2VendorContact, target.vendor_contact_id)
            entity_type = "vendor_contact"

        if row is None:
            return ChannelToggleResult(target=target, success=False, error="Person not found.")

        if channel == "telegram" and not row.telegram_chat_id:
            # AE1: toggling to telegram requires a connect step (U13) to
            # have already set telegram_chat_id. Toggling to whatsapp has
            # no such precondition.
            return ChannelToggleResult(
                target=target, success=False,
                error="This person has not connected Telegram yet - they must open the bot's Start link first.",
            )

        from_channel = row.active_channel
        if from_channel == channel:
            # Already on the requested channel - a no-op, still reported
            # as success (idempotent), but no audit row for a non-change.
            return ChannelToggleResult(target=target, success=True)

        row.active_channel = channel
        self.db.add(V2AuditEvent(
            actor_user_id=actor.id,
            action="channel_toggled",
            entity_type=entity_type,
            entity_id=row.id,
            before_json={"active_channel": from_channel},
            after_json={"active_channel": channel},
            reason=f"Channel switched from {from_channel} to {channel} by {actor.name}.",
        ))
        return ChannelToggleResult(target=target, success=True)
