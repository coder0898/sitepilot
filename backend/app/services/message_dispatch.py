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

`_resolve_pm_supervisor_recipients` (and therefore `_ACCOUNTABLE_ROLES`)
structurally excludes `UserRole.super_admin`: it only ever queries
`V2ProjectMembership.project_role in ('project_manager', 'site_supervisor')`,
and `project_role` never stores `'super_admin'` (see
`app.project_models.V2ProjectMembership` - the column's only values are
`'project_manager'`, `'site_supervisor'`, `'internal_employee'`). A Super
Admin acting on a project is never a project *member* and therefore can
never be selected as a notification recipient via that path, independent of
their `User.role`.

This is narrower than a claim about `_resolve_recipients` as a whole,
though: `_resolve_admin_recipients` (Phase 1b) is a second, deliberately
separate resolver that DOES query `User.role in (admin, super_admin)`
directly - it is invoked only for an explicit allowlist of event types
(every `project_external_approval.*` event, `task.approval_recorded` via
`_ADMIN_CC_TASK_EVENTS`, and `report.weekly_summary_generated` via Phase 8's
`_ADMIN_CC_PROJECT_EVENTS`), never as a blanket widening of the PM/
Supervisor path, and never changes what `_ACCOUNTABLE_ROLES` itself means.
Admin becomes a WhatsApp *recipient* on those specific events (visibility),
never an approver - BR-008's PM-primary approval authority in
`task_approval.py` is untouched.

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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.execution_models import (
    MessageDelivery,
    OutboxEvent,
    ProjectExternalApproval,
    Task,
    TaskSupportAssignment,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2ProjectMembership
from app.services.message_templates import TemplateSpec, render_components, resolve
from app.vendor_models import TaskVendorAssignment, V2VendorContact

# The only two `V2ProjectMembership.project_role` values this service ever
# treats as notification recipients. `'super_admin'` is deliberately never
# in this tuple (and is not even a value `project_role` can hold - see the
# module docstring) - this is the structural proof R7 relies on.
_ACCOUNTABLE_ROLES = ("project_manager", "site_supervisor")

_SUCCEEDED_STATUSES = ("sent", "delivered", "read")

# Phase 1b (locked decision #1): Class A approval decisions are the one
# task-event class where Admin becomes a CC recipient - visibility only,
# never authority. BR-008's PM-primary approve/reject flow in
# task_approval.py is unchanged; this only widens who is *notified* of the
# outcome it already decided. Deliberately narrow - do not add every task
# event here.
#
# Phase 6 adds `task.escalated_to_admin` (`EscalationService.
# sweep_task_escalations`): a task that reaches the admin-escalation stage
# is, by definition, an Admin-visibility event - the same "visibility, not
# authority" rationale as the Class A decision above.
_ADMIN_CC_TASK_EVENTS = {"task.approval_recorded", "task.escalated_to_admin"}

# Plan Phase 8: mirrors `_ADMIN_CC_TASK_EVENTS`'s exact pattern for the
# `project` aggregate branch. Deliberately a narrow allowlist, not a
# blanket "every project.* event reaches Admin" widening - the plan's own
# framing is that Admin is pushed the weekly summary specifically, not
# every project-aggregate event `_resolve_pm_supervisor_recipients` already
# reaches PM/Supervisor for.
_ADMIN_CC_PROJECT_EVENTS = {"report.weekly_summary_generated"}

# Phase 7: the four daily-prompt event types `daily_task_prompts.py` emits.
# Per the doc's own §5-§6 readiness/start/midday/EOD templates, the assigned
# Internal Employee is a receiver on all four - unlike the vendor-eligible
# set below, this one is not narrowed to exclude the EOD check.
_EMPLOYEE_ELIGIBLE_TASK_EVENTS: set[str] = {
    "task.readiness_check",
    "task.start_check",
    "task.midday_check",
    "task.eod_check",
}

# Phase 7: three of the four daily-prompt event types - the doc's own tables
# mark readiness/start/midday as "Vendor if involved" but the EOD check's
# receiver list is PM/Supervisor/Internal Employee only, no vendor -
# `task.eod_check` is deliberately excluded here.
_VENDOR_ELIGIBLE_TASK_EVENTS: set[str] = {
    "task.readiness_check",
    "task.start_check",
    "task.midday_check",
}


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

    def _primary_vendor_contact_recipient(self, vendor_id: uuid.UUID) -> Recipient | None:
        """Shared tail of vendor recipient resolution: given a `vendor_id`,
        find its primary `V2VendorContact` and build a `Recipient`. Used by
        both `_resolve_vendor_recipient` (payload-driven, `task.
        vendor_assigned`) and `_resolve_vendor_recipient_for_task`
        (lookup-driven, Phase 7's readiness/start/midday checks)."""
        contact = self.db.scalar(
            select(V2VendorContact).where(
                V2VendorContact.vendor_id == vendor_id,
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

        return self._primary_vendor_contact_recipient(uuid.UUID(vendor_id_raw))

    def _resolve_vendor_recipient_for_task(self, task: Task) -> Recipient | None:
        """Phase 7: lookup-driven vendor resolution for the readiness/start/
        midday daily-prompt events (`_VENDOR_ELIGIBLE_TASK_EVENTS`). Unlike
        `_resolve_vendor_recipient`, these events' payloads (written by
        `DailyTaskPromptsService._emit_for_tasks` - `task_id`, `project_id`,
        `lifecycle_status`, `planned_start_date`) carry no vendor info at
        all, since a prompt sweep doesn't know per-task vendor assignment
        without querying for it.

        "Active" here mirrors `vendor_acknowledgement.py`'s
        `RESOLVED_ASSIGNMENT_STATUSES` framing in reverse: a
        `TaskVendorAssignment` is still "the vendor is involved" as long as
        it hasn't been explicitly `declined` - `pending_ack` (not yet
        responded) and `acknowledged` (accepted) both count. When more than
        one non-declined assignment exists on the same task (e.g. a re-
        delegation), the most recently created one wins.

        Returns `None` (not an error) when the task has no active vendor
        assignment or that vendor has no primary contact - "vendor not
        involved" is the normal case for most tasks, per the doc's "if
        involved" language."""
        assignment = self.db.scalar(
            select(TaskVendorAssignment)
            .where(
                TaskVendorAssignment.task_id == task.id,
                TaskVendorAssignment.status != "declined",
            )
            .order_by(TaskVendorAssignment.created_at.desc())
            .limit(1)
        )
        if assignment is None:
            return None
        return self._primary_vendor_contact_recipient(assignment.vendor_id)

    def _resolve_admin_recipients(self) -> list[Recipient]:
        """All active users with `role in (admin, super_admin)`. Deliberately
        "all admins" - there is no per-project Admin assignment anywhere in
        the schema (`V2ProjectMembership.project_role` cannot hold
        `'admin'`/`'super_admin'` - see the module docstring) to narrow this
        to project scope, so every project's `project_external_approval.*`
        event and every `task.approval_recorded` event notifies the same
        Admin set. This is a locked decision (plan Decisions section), not
        an oversight.

        Follows the same resolve-then-fail-visibly pattern as
        `_resolve_pm_supervisor_recipients`/`_resolve_vendor_recipient`: an
        Admin with no phone on file is still resolved to a `Recipient` and
        reaches the adapter, surfacing as an explicit `failed`/
        `missing_phone` delivery row rather than silently vanishing.
        """
        rows = self.db.execute(
            select(EmployeeProfile.id, User.phone)
            .join(User, User.id == EmployeeProfile.user_id)
            .where(User.role.in_((UserRole.admin, UserRole.super_admin)), User.active.is_(True))
        ).all()
        return [
            Recipient(employee_id=employee_id, vendor_contact_id=None, phone=phone or "")
            for employee_id, phone in rows
        ]

    def _resolve_gate_assignee_recipient(self, approval: ProjectExternalApproval) -> list[Recipient]:
        """Resolves a `project_external_approval` gate's own assignee
        (`assigned_to_user_id`) to a `Recipient`. Returns `[]` - a genuinely
        unresolvable recipient, skipped rather than resolved-then-failed,
        matching this module's own precedent for "no row to even construct"
        cases (see `_resolve_vendor_recipient`'s `None` returns) - when the
        gate has no assignee yet (`unassigned` status) or the assignee's
        `EmployeeProfile`/`User` link can't be found."""
        if approval.assigned_to_user_id is None:
            return []
        employee = self.db.scalar(
            select(EmployeeProfile).where(EmployeeProfile.user_id == approval.assigned_to_user_id)
        )
        if employee is None:
            return []
        user = self.db.get(User, approval.assigned_to_user_id)
        if user is None:
            return []
        return [Recipient(employee_id=employee.id, vendor_contact_id=None, phone=user.phone or "")]

    def _resolve_internal_employee_recipient(self, task: Task) -> list[Recipient]:
        """Resolves every active `TaskSupportAssignment` on `task` to its
        employee's `Recipient`. Scaffolded in Phase 1, wired up in Phase 7 -
        called for every event type in `_EMPLOYEE_ELIGIBLE_TASK_EVENTS`
        (the four daily-prompt events: readiness/start/midday/EOD)."""
        rows = self.db.execute(
            select(EmployeeProfile.id, User.phone)
            .join(User, User.id == EmployeeProfile.user_id)
            .join(TaskSupportAssignment, TaskSupportAssignment.employee_id == EmployeeProfile.id)
            .where(TaskSupportAssignment.task_id == task.id, TaskSupportAssignment.status == "active")
        ).all()
        return [
            Recipient(employee_id=employee_id, vendor_contact_id=None, phone=phone or "")
            for employee_id, phone in rows
        ]

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
            if event.event_type in _ADMIN_CC_TASK_EVENTS:
                recipients.extend(self._resolve_admin_recipients())
            if event.event_type in _EMPLOYEE_ELIGIBLE_TASK_EVENTS:
                recipients.extend(self._resolve_internal_employee_recipient(task))
            if event.event_type in _VENDOR_ELIGIBLE_TASK_EVENTS:
                vendor_task_recipient = self._resolve_vendor_recipient_for_task(task)
                if vendor_task_recipient is not None:
                    recipients.append(vendor_task_recipient)
        elif event.aggregate_type == "project":
            recipients.extend(self._resolve_pm_supervisor_recipients(event.aggregate_id))
            if event.event_type in _ADMIN_CC_PROJECT_EVENTS:
                recipients.extend(self._resolve_admin_recipients())
        elif event.aggregate_type == "project_external_approval":
            approval = self.db.get(ProjectExternalApproval, event.aggregate_id)
            if approval is None:
                return []
            recipients.extend(self._resolve_gate_assignee_recipient(approval))
            # Every project_external_approval.* event resolves Admin - this
            # is where doc #27's "Admin review-required push" falls out of,
            # `submitted` included (Phase 1b).
            recipients.extend(self._resolve_admin_recipients())
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

    def _dispatch_to_recipient(self, event: OutboxEvent, recipient: Recipient, spec: TemplateSpec) -> None:
        template = spec.meta_template_name
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
            try:
                self.db.flush()
            except IntegrityError:
                # Lost a race against a concurrent dispatch pass that already
                # inserted the same (event, recipient, template) delivery -
                # `uq_v2_message_deliveries_event_recipient_template` caught
                # it. Benign: roll back our half-started insert and fall back
                # to the row the other pass already committed, same as if
                # `_existing_delivery` above had found it in the first place.
                self.db.rollback()
                delivery = self._existing_delivery(event.id, recipient, template)
                if delivery is None or delivery.status in _SUCCEEDED_STATUSES:
                    return

        # Refresh the denormalized snapshot on every attempt (including a
        # retry) so it reflects the number this specific attempt targeted.
        delivery.recipient_phone = recipient.phone
        delivery.status = "sending"
        delivery.attempt_count += 1

        # Merge `components` into a copy of the event payload rather than
        # mutating `event.payload` itself - the outbox row's payload is the
        # durable record of what happened; `components` is dispatch-time
        # rendering derived from it, not part of that record.
        components = render_components(spec, event.payload or {})
        send_payload = {**(event.payload or {}), "components": components, "language_code": spec.language}

        result = self.adapter.send(recipient_phone=recipient.phone, template=template, payload=send_payload)
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
            spec = resolve(event.event_type)
            for recipient in self._resolve_recipients(event):
                self._dispatch_to_recipient(event, recipient, spec)
            event.status = "dispatched"
            self.db.add(event)
            self.db.commit()
        return len(events)
