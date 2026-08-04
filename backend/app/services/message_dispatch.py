"""Phase 2 U5: message delivery tracking + provider-agnostic dispatch (R7).

`MessageDispatchService.process_pending` is an internal dispatch process
(not a user-facing portal route, so it is not actor-gated the way
`TaskLifecycleService`/`TaskVendorAssignmentService` etc. are) that reads
pending `OutboxEvent` rows (`app.execution_models.OutboxEvent`, written by
`OutboxService.emit` - see `app.services.outbox`) and attempts delivery to
every resolved recipient via a `WhatsAppProviderAdapter`.

This unit does NOT send real WhatsApp messages. `SandboxProviderAdapter` is
a deterministic fake used for infrastructure testing; a real provider
adapter (e.g. a Meta/WABA client) would implement the same
`WhatsAppProviderAdapter` protocol and be wired in behind an app.config
setting later. That real adapter's credentials (an access token, a phone
number ID, etc.) would be added to `backend/app/config.py`'s `Settings`
class, mirroring how `supabase_secret_key` is sourced - always from
environment/`.env`, never hardcoded, never committed. This unit needs no
such settings since the sandbox adapter requires no credentials.

Recipient resolution structurally excludes `UserRole.super_admin`: it only
ever queries `V2ProjectMembership.project_role in ('project_manager',
'site_supervisor')`, and `project_role` never stores `'super_admin'` (see
`app.project_models.V2ProjectMembership` - the column's only values are
`'project_manager'`, `'site_supervisor'`, `'internal_employee'`). A Super
Admin acting on a project is never a project *member* and therefore can
never be selected as a notification recipient by this code, independent of
their `User.role`.

Recipient resolution never silently drops a project member (PM/Supervisor)
or a vendor's primary contact for lacking a phone number: it always
resolves them to a `Recipient` (using `User.phone or ""` / `contact.phone
or contact.whatsapp or ""`) and lets them reach the adapter, which then
fails deterministically with `failure_code='missing_phone'`. This is a
deliberate deviation from an earlier draft of this unit's Approach notes,
which described silently skipping a phone-less recipient at resolution
time with "no delivery attempt for them, don't error". Two things pushed
this to resolve-then-fail instead: (1) the plan's own test scenarios
(a retry test that expects a first, failing `process_pending()` pass
against a recipient with no phone, and an error-path test that expects an
explicit `status='failed'` `MessageDelivery` row for exactly that
recipient) are only satisfiable if the recipient is actually resolved and
reaches the adapter - a silently-skipped recipient leaves no row and
nothing to retry; and (2) it is the better design regardless: a silently
dropped recipient leaves no queryable trace that a PM/Supervisor/vendor
contact couldn't be reached, whereas a `'failed'` row with
`failure_code='missing_phone'` is visible and actionable to ops. A
genuinely unresolvable recipient (no `EmployeeProfile` link, or no primary
vendor contact at all) is still skipped, since there is no row to even
construct in that case.

Idempotency / retry: `process_pending` never creates a second
`MessageDelivery` row for the same
(outbox_event_id, recipient, template) - see the unique index in
`supabase/migrations/202608040005_v2_message_deliveries.sql`. A recipient
whose prior attempt is `'failed'` is retried in place (existing row,
incremented `attempt_count`) rather than duplicated. A `'sent'`/
`'delivered'`/`'read'` prior attempt is left alone (already succeeded).

Outbox event re-selection: `process_pending` selects `OutboxEvent` rows
that are `status = 'pending'` OR are `status = 'dispatched'` but still have
at least one `MessageDelivery` row `status = 'failed'` against them - this
is a deliberate small widening of the plan's literal "query rows with
status='pending'" Approach note, needed to reconcile two requirements that
are otherwise in tension: (a) an event is marked `'dispatched'` after every
recipient has been attempted once, regardless of individual outcomes (so a
failed delivery to one recipient never blocks the others, and never leaves
the outbox event itself stuck mid-processing on a crash), and (b) a later
`process_pending()` call must still be able to retry a recipient whose
delivery previously failed (e.g. once their phone number is corrected).
Purely `'pending'`-only re-selection would satisfy (a) but never retry
anything after the first pass; this widened predicate satisfies both,
while a `'dispatched'` event with no failed deliveries is never
re-selected - so re-running `process_pending()` immediately after a fully
successful batch is still a safe no-op that creates zero new rows, exactly
as the plan's verification test scenario expects.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from app.execution_models import MessageDelivery, OutboxEvent, Task
from app.models import EmployeeProfile, User
from app.project_models import V2ProjectMembership
from app.vendor_models import TaskVendorAssignment, V2VendorContact

# The only two `V2ProjectMembership.project_role` values this service ever
# treats as notification recipients. `'super_admin'` is deliberately never
# in this tuple (and is not even a value `project_role` can hold - see the
# module docstring) - this is the structural proof R7 relies on.
_ACCOUNTABLE_ROLES = ("project_manager", "site_supervisor")

_SUCCEEDED_STATUSES = ("sent", "delivered", "read")


@dataclass(frozen=True)
class ProviderSendResult:
    """Outcome of one `WhatsAppProviderAdapter.send(...)` attempt."""

    ok: bool
    provider_message_id: str | None = None
    failure_code: str | None = None
    failure_reason: str | None = None


@dataclass(frozen=True)
class Recipient:
    """One resolved notification target. Exactly one of `employee_id` /
    `vendor_contact_id` is set, mirroring `MessageDelivery`'s own
    real-FK-pair recipient columns."""

    employee_id: uuid.UUID | None
    vendor_contact_id: uuid.UUID | None
    phone: str


class WhatsAppProviderAdapter(Protocol):
    """Provider-agnostic send interface. A real adapter (Meta/WABA, etc.)
    implements this same shape; `MessageDispatchService` never depends on
    provider-specific details beyond this method."""

    def send(self, recipient_phone: str, template: str, payload: dict) -> ProviderSendResult: ...


class SandboxProviderAdapter:
    """Deterministic fake provider for infra testing - no real network
    call, no real credentials. Succeeds for any non-empty
    `recipient_phone`; fails with `failure_code='missing_phone'` when the
    phone is falsy, which is this unit's only controllable way to exercise
    the failure path without real network mocking."""

    def send(self, recipient_phone: str, template: str, payload: dict) -> ProviderSendResult:
        if not recipient_phone:
            return ProviderSendResult(
                ok=False,
                failure_code="missing_phone",
                failure_reason="Recipient has no phone number on file.",
            )
        return ProviderSendResult(ok=True, provider_message_id=f"sandbox-{uuid.uuid4().hex}")


class MessageDispatchService:
    def __init__(self, db: Session, adapter: WhatsAppProviderAdapter | None = None):
        self.db = db
        self.adapter = adapter or SandboxProviderAdapter()

    # ---- recipient resolution -------------------------------------------

    def _resolve_pm_supervisor_recipients(self, project_id: uuid.UUID) -> list[Recipient]:
        rows = self.db.execute(
            select(V2ProjectMembership.employee_id, User.phone)
            .join(EmployeeProfile, EmployeeProfile.id == V2ProjectMembership.employee_id)
            .join(User, User.id == EmployeeProfile.user_id)
            .where(
                V2ProjectMembership.project_id == project_id,
                V2ProjectMembership.project_role.in_(_ACCOUNTABLE_ROLES),
                V2ProjectMembership.ends_at.is_(None),
            )
        ).all()
        # Every active PM/Supervisor member is resolved to a Recipient
        # regardless of phone - see the module docstring's "recipient
        # resolution never silently drops..." note. A missing phone
        # becomes an explicit, queryable failed delivery instead of a
        # silent no-op.
        return [
            Recipient(employee_id=employee_id, vendor_contact_id=None, phone=phone or "")
            for employee_id, phone in rows
        ]

    def _resolve_vendor_recipient(self, event: OutboxEvent) -> Recipient | None:
        """Only called for `event_type == 'task.vendor_assigned'`. Reads
        `vendor_id` directly off the payload (the shape
        `TaskVendorAssignmentService.assign_vendor` actually writes -
        `{"task_id", "project_id", "assignment_id", "vendor_id"}`), with a
        fallback re-derivation via `assignment_id` for robustness against a
        future payload shape change."""
        payload = event.payload or {}
        vendor_id_raw = payload.get("vendor_id")
        if not vendor_id_raw:
            assignment_id_raw = payload.get("assignment_id")
            if assignment_id_raw:
                assignment = self.db.get(TaskVendorAssignment, uuid.UUID(assignment_id_raw))
                if assignment is not None:
                    vendor_id_raw = str(assignment.vendor_id)
        if not vendor_id_raw:
            return None

        contact = self.db.scalar(
            select(V2VendorContact).where(
                V2VendorContact.vendor_id == uuid.UUID(vendor_id_raw),
                V2VendorContact.is_primary.is_(True),
            )
        )
        if contact is None:
            return None
        # As with PM/Supervisor resolution: resolve regardless of phone,
        # using phone falling back to whatsapp, falling back to "" - a
        # missing number surfaces as a failed delivery, not a silent skip.
        phone = contact.phone or contact.whatsapp or ""
        return Recipient(employee_id=None, vendor_contact_id=contact.id, phone=phone)

    def _resolve_recipients(self, event: OutboxEvent) -> list[Recipient]:
        recipients: list[Recipient] = []
        if event.aggregate_type == "task":
            task = self.db.get(Task, event.aggregate_id)
            if task is None:
                return []
            recipients.extend(self._resolve_pm_supervisor_recipients(task.project_id))
            if event.event_type == "task.vendor_assigned":
                vendor_recipient = self._resolve_vendor_recipient(event)
                if vendor_recipient is not None:
                    recipients.append(vendor_recipient)
        elif event.aggregate_type == "project":
            recipients.extend(self._resolve_pm_supervisor_recipients(event.aggregate_id))
        return recipients

    # ---- delivery -----------------------------------------------------

    def _existing_delivery(self, event_id: uuid.UUID, recipient: Recipient, template: str) -> MessageDelivery | None:
        stmt = select(MessageDelivery).where(
            MessageDelivery.outbox_event_id == event_id,
            MessageDelivery.template == template,
        )
        if recipient.employee_id is not None:
            stmt = stmt.where(
                MessageDelivery.recipient_employee_id == recipient.employee_id,
                MessageDelivery.recipient_vendor_contact_id.is_(None),
            )
        else:
            stmt = stmt.where(
                MessageDelivery.recipient_vendor_contact_id == recipient.vendor_contact_id,
                MessageDelivery.recipient_employee_id.is_(None),
            )
        return self.db.scalar(stmt)

    def _dispatch_to_recipient(self, event: OutboxEvent, recipient: Recipient, template: str) -> None:
        delivery = self._existing_delivery(event.id, recipient, template)
        if delivery is not None and delivery.status in _SUCCEEDED_STATUSES:
            return  # already succeeded - no re-send

        if delivery is None:
            delivery = MessageDelivery(
                outbox_event_id=event.id,
                recipient_employee_id=recipient.employee_id,
                recipient_vendor_contact_id=recipient.vendor_contact_id,
                recipient_phone=recipient.phone,
                template=template,
                status="queued",
                attempt_count=0,
            )
            self.db.add(delivery)
            self.db.flush()

        # Refresh the denormalized snapshot on every attempt (including a
        # retry) so it reflects the number this specific attempt targeted.
        delivery.recipient_phone = recipient.phone
        delivery.status = "sending"
        delivery.attempt_count += 1

        result = self.adapter.send(recipient_phone=recipient.phone, template=template, payload=event.payload or {})
        if result.ok:
            delivery.status = "sent"
            delivery.provider_message_id = result.provider_message_id
            delivery.failure_code = None
            delivery.failure_reason = None
        else:
            delivery.status = "failed"
            delivery.failure_code = result.failure_code
            delivery.failure_reason = result.failure_reason
        self.db.flush()

    # ---- entry point ------------------------------------------------

    def _select_events(self, limit: int) -> list[OutboxEvent]:
        has_failed_delivery = exists().where(
            MessageDelivery.outbox_event_id == OutboxEvent.id,
            MessageDelivery.status == "failed",
        )
        stmt = (
            select(OutboxEvent)
            .where(
                or_(
                    OutboxEvent.status == "pending",
                    and_(OutboxEvent.status == "dispatched", has_failed_delivery),
                )
            )
            .order_by(OutboxEvent.created_at)
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())

    def process_pending(self, limit: int = 50) -> int:
        """Processes up to `limit` outbox events (pending, plus dispatched
        events still carrying a failed delivery - see module docstring).
        Commits once per event so a crash mid-loop across recipients never
        leaves an event half-processed and uncommitted; re-running
        `process_pending()` afterward is safe because of the existing-row
        check in `_dispatch_to_recipient`. Returns the number of events
        processed in this call."""
        events = self._select_events(limit)
        for event in events:
            template = event.event_type
            for recipient in self._resolve_recipients(event):
                self._dispatch_to_recipient(event, recipient, template)
            event.status = "dispatched"
            self.db.add(event)
            self.db.commit()
        return len(events)
