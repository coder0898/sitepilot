"""Phase 2 U6: inbound WhatsApp message matching (R8/R9).

`InboundMessageService.process` is the single entry point called after
`backend/app/routes/whatsapp_webhook_v2.py` has already verified the
webhook's HMAC signature. Its job is strictly: (1) de-duplicate by
`provider_message_id`, (2) match `sender_phone` to exactly one known
identity (an active employee, via `users.phone` joined to an active
`EmployeeProfile`; or a vendor contact, via `V2VendorContact.phone` /
`.whatsapp`), (3) parse a minimal command grammar scoped to that identity's
allowed command set, and (4) translate an approved command into the EXACT
SAME service call a portal action of that kind would make -
`TaskLifecycleService.transition` for employees,
`VendorAcknowledgementService.record_acknowledgement` for vendor contacts.
This module never mutates `Task.lifecycle_status` or any vendor-assignment
state directly - it only ever calls into those two existing services, which
already own all role/access/state-machine checks.

No phone-number normalization is applied anywhere in this codebase yet
(see the plan's gap note) - matching is raw string equality against
whatever is stored in `users.phone` / `V2VendorContact.phone` /
`V2VendorContact.whatsapp`.

Command grammar (deliberately minimal - this is new entry-point wiring for
R8/R9's identity/signature/same-service-path guarantees, not a UX-polish
exercise; a real product would need a friendlier conversational UX):

    Whitespace-split the message body. The first token is the command
    keyword, matched case-insensitively. Everything else is positional.

    Vendor-contact identity only:
        ACCEPT <assignment_ref>
        DECLINE <assignment_ref>
        CLARIFY <assignment_ref> <note...>

    where <assignment_ref> is the first 8 hex characters of a
    `TaskVendorAssignment.id` UUID with dashes stripped (matched
    case-insensitively against every assignment's id in that same form -
    zero or more than one match is an error, never resolved by a
    "most recent" or similar heuristic). <note...> (CLARIFY only) is
    whatever text follows the ref, verbatim.

    Employee identity only:
        STATUS <task_code> <target_status>

    where <task_code> is a `Task.original_code` (e.g. "T003" - unique only
    within a project, not globally) and <target_status> is passed through
    verbatim to `TaskLifecycleService.transition`, which validates it.

    A vendor contact sending STATUS, or an employee sending
    ACCEPT/DECLINE/CLARIFY, is rejected as "not available for your
    identity type" (BR-015). An unrecognized keyword is rejected as
    "Unrecognized command."

Actor substitution for vendor acknowledgements (the one genuinely
non-obvious design decision here): `VendorAcknowledgementService.
record_acknowledgement` requires a `User` actor because it runs its own
PM-only access check (`_require_pm`) - but a `V2VendorContact` has no
`User` row at all in this codebase (no `user_id` FK). R4 already
establishes that a PM records an acknowledgement "on the vendor's behalf";
R9 says this unit must produce "the identical record a PM's portal
acknowledgement would produce" for an approved vendor reply. Combining
those: the correct actor to pass is the project's currently active PM's
`User` (resolved via `V2ProjectMembership` for the assignment's project,
`project_role == 'project_manager'`, `ends_at IS NULL`, then that
membership's `EmployeeProfile.user_id`). This satisfies
`record_acknowledgement`'s own access check exactly as a real PM-driven
portal call would, while the `inbound_messages` row itself still records
the vendor contact as the identity that actually sent the message - the
PM substitution is purely an actor-parameter mechanic for the downstream
service call, never surfaced as who "did" the acknowledgement in this
table. If no active PM exists for the project, that is a `'rejected'`
outcome, not a crash - there is no one to record on the vendor's behalf.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.execution_models import InboundMessage, Task
from app.models import EmployeeProfile, User
from app.project_models import V2ProjectMembership
from app.services.task_lifecycle import TaskLifecycleService
from app.services.vendor_acknowledgement import VendorAcknowledgementService
from app.vendor_models import TaskVendorAssignment, V2VendorContact

VENDOR_COMMANDS = {"ACCEPT", "DECLINE", "CLARIFY"}
EMPLOYEE_COMMAND = "STATUS"

# The only project roles that may drive a task-lifecycle transition at all
# (TaskLifecycleService._require_role_for_transition) - reused verbatim as
# the pre-filter for resolving an ambiguous project-scoped task code,
# rather than inventing a separate role set for the WhatsApp path.
_STATUS_DRIVING_ROLES = ("site_supervisor", "project_manager")

_RESPONSE_BY_COMMAND = {
    "ACCEPT": "accepted",
    "DECLINE": "declined",
    "CLARIFY": "clarification_requested",
}

EmployeeIdentity = tuple[User, EmployeeProfile]


class InboundMessageService:
    def __init__(self, db: Session):
        self.db = db

    # ---- entry point ----------------------------------------------------

    def process(self, provider_message_id: str, sender_phone: str, message_text: str) -> InboundMessage:
        existing = self.db.scalar(
            select(InboundMessage).where(InboundMessage.provider_message_id == provider_message_id)
        )
        if existing is not None:
            # Duplicate webhook delivery: return the prior outcome
            # unchanged. No new row, no re-execution of any command.
            return existing

        employee_matches = self._match_employees(sender_phone)
        vendor_matches = self._match_vendor_contacts(sender_phone)
        total_matches = len(employee_matches) + len(vendor_matches)

        if total_matches == 0:
            return self._save(
                provider_message_id, sender_phone, message_text, None, None,
                "unmatched", "No identity matched this phone number.",
            )
        if total_matches > 1:
            return self._save(
                provider_message_id, sender_phone, message_text, None, None,
                "unmatched", "Phone number matched more than one identity; ambiguous.",
            )

        if employee_matches:
            return self._handle_employee(
                provider_message_id, sender_phone, message_text, employee_matches[0],
            )
        return self._handle_vendor_contact(
            provider_message_id, sender_phone, message_text, vendor_matches[0],
        )

    # ---- identity matching ------------------------------------------------

    def _match_employees(self, sender_phone: str) -> list[EmployeeIdentity]:
        rows = self.db.execute(
            select(User, EmployeeProfile)
            .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
            .where(User.phone == sender_phone, User.active.is_(True))
        ).all()
        return [(row[0], row[1]) for row in rows]

    def _match_vendor_contacts(self, sender_phone: str) -> list[V2VendorContact]:
        return list(
            self.db.scalars(
                select(V2VendorContact).where(
                    or_(V2VendorContact.phone == sender_phone, V2VendorContact.whatsapp == sender_phone)
                )
            ).all()
        )

    # ---- command parsing + dispatch ---------------------------------------

    def _handle_employee(
        self, provider_message_id: str, sender_phone: str, message_text: str, identity: EmployeeIdentity,
    ) -> InboundMessage:
        user, employee = identity
        parts = message_text.split()
        keyword = parts[0].upper() if parts else ""

        if keyword in VENDOR_COMMANDS:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", "This command is not available for your identity type.",
            )
        if keyword != EMPLOYEE_COMMAND or len(parts) < 3:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", "Unrecognized command.",
            )

        task_code, target_status = parts[1], parts[2]
        task = self._resolve_task_for_employee(task_code, employee)
        if task is None:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", "Could not uniquely resolve this task code to one of your projects.",
            )

        try:
            # The EXACT SAME service call a portal status-update action
            # would make - transition() owns all role/dependency/state
            # checks itself; nothing here duplicates that logic.
            TaskLifecycleService(self.db).transition(
                task.project_id, task.id, target_status, actor=user, reason="Reported via WhatsApp.",
            )
        except HTTPException as exc:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", str(exc.detail),
            )

        return self._save(
            provider_message_id, sender_phone, message_text, "employee", employee.id, "processed", None,
        )

    def _resolve_task_for_employee(self, task_code: str, employee: EmployeeProfile) -> Task | None:
        candidates = self.db.scalars(select(Task).where(Task.original_code == task_code)).all()
        matched: list[Task] = []
        for task in candidates:
            has_driving_role = self.db.scalar(
                select(V2ProjectMembership.id).where(
                    V2ProjectMembership.project_id == task.project_id,
                    V2ProjectMembership.employee_id == employee.id,
                    V2ProjectMembership.ends_at.is_(None),
                    V2ProjectMembership.project_role.in_(_STATUS_DRIVING_ROLES),
                )
            )
            if has_driving_role is not None:
                matched.append(task)
        if len(matched) != 1:
            return None
        return matched[0]

    def _handle_vendor_contact(
        self, provider_message_id: str, sender_phone: str, message_text: str, vendor_contact: V2VendorContact,
    ) -> InboundMessage:
        parts = message_text.split()
        keyword = parts[0].upper() if parts else ""

        if keyword == EMPLOYEE_COMMAND:
            return self._save(
                provider_message_id, sender_phone, message_text, "vendor_contact", vendor_contact.id,
                "rejected", "This command is not available for your identity type.",
            )
        if keyword not in VENDOR_COMMANDS or len(parts) < 2:
            return self._save(
                provider_message_id, sender_phone, message_text, "vendor_contact", vendor_contact.id,
                "rejected", "Unrecognized command.",
            )

        ref = parts[1]
        note = " ".join(parts[2:]) if keyword == "CLARIFY" and len(parts) > 2 else None

        assignment = self._resolve_assignment_by_ref(ref)
        if assignment is None:
            return self._save(
                provider_message_id, sender_phone, message_text, "vendor_contact", vendor_contact.id,
                "rejected", "No unique assignment matched this reference.",
            )
        if assignment.vendor_id != vendor_contact.vendor_id:
            return self._save(
                provider_message_id, sender_phone, message_text, "vendor_contact", vendor_contact.id,
                "rejected", "This assignment does not belong to your vendor.",
            )

        pm_actor = self._active_pm_user(assignment.project_id)
        if pm_actor is None:
            return self._save(
                provider_message_id, sender_phone, message_text, "vendor_contact", vendor_contact.id,
                "rejected", "No active PM on this project to record the acknowledgement.",
            )

        try:
            # The EXACT SAME service call a PM's portal acknowledgement
            # action would make - see this module's docstring for why
            # `pm_actor` (not the vendor contact, which has no User row)
            # is the correct `actor` here.
            VendorAcknowledgementService(self.db).record_acknowledgement(
                assignment.project_id, assignment.task_id, assignment.id,
                response=_RESPONSE_BY_COMMAND[keyword], actor=pm_actor, channel="whatsapp", note=note,
            )
        except HTTPException as exc:
            return self._save(
                provider_message_id, sender_phone, message_text, "vendor_contact", vendor_contact.id,
                "rejected", str(exc.detail),
            )

        return self._save(
            provider_message_id, sender_phone, message_text, "vendor_contact", vendor_contact.id,
            "processed", None,
        )

    def _resolve_assignment_by_ref(self, ref: str) -> TaskVendorAssignment | None:
        ref_lower = ref.lower()
        candidates = self.db.scalars(select(TaskVendorAssignment)).all()
        matched = [
            assignment for assignment in candidates
            if str(assignment.id).replace("-", "").lower()[:8] == ref_lower
        ]
        if len(matched) != 1:
            return None
        return matched[0]

    def _active_pm_user(self, project_id: uuid.UUID) -> User | None:
        membership = self.db.scalar(
            select(V2ProjectMembership).where(
                V2ProjectMembership.project_id == project_id,
                V2ProjectMembership.project_role == "project_manager",
                V2ProjectMembership.ends_at.is_(None),
            )
        )
        if membership is None:
            return None
        employee = self.db.get(EmployeeProfile, membership.employee_id)
        if employee is None:
            return None
        return self.db.get(User, employee.user_id)

    # ---- persistence --------------------------------------------------

    def _save(
        self,
        provider_message_id: str,
        sender_phone: str,
        raw_body: str,
        matched_identity_type: str | None,
        matched_identity_id: uuid.UUID | None,
        processing_status: str,
        rejection_reason: str | None,
    ) -> InboundMessage:
        row = InboundMessage(
            provider_message_id=provider_message_id,
            sender_phone=sender_phone,
            raw_body=raw_body,
            matched_identity_type=matched_identity_type,
            matched_identity_id=matched_identity_id,
            processing_status=processing_status,
            rejection_reason=rejection_reason,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row
