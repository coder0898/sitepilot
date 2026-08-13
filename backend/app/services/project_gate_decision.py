"""U11: recording a decision against an execution-layer external approval (R8).

`ProjectGateDecisionService.decide` moves one `ProjectExternalApproval` from
`pending` to `approved` or `rejected`, recording who decided and when, and
`ProjectGateDecisionService.list_for_project` reads a project's approvals back
out for the Execution tab.

Why this writes to `ProjectExternalApproval` and never to the planning-layer
`V2ProjectExternalGate`: the gate's `status` is a Draft-time review marker,
CHECK-constrained to the single value `pending_review` and written only while
the project is still a draft. "Has the authority granted this?" is a runtime
question about a live project, and answering it on the gate would conflate the
planning question with the execution one and split one approval's state across
two families (KTD3/KTD8). `ProjectExternalApproval` exists precisely so that it
does not have to.

Authority mirrors `TaskApprovalService._require_approver` exactly - the
project's PM decides, with Admin/Super Admin as the audited fallback under
BR-007's PM-unavailable hierarchy. Deciding whether an external authority has
granted permission is the same accountability as approving the work that
depends on it, so it gets the same rule rather than a new one. Read access is
wider (any active project member): a Supervisor needs to see which approvals
are holding up their site even though they may not decide one, which is the
same split `ProjectGateApplicabilityService` already draws between
`_require_access` and `_require_decider`.

Three invariants this module is careful about:

- `ck_v2_project_external_approvals_decision_completeness` requires `status`,
  `decided_by` and `decided_at` to move together - a `pending` row must have
  both nulls, a decided row must have both set. They are therefore assigned in
  one place, never incrementally.
- `ck_v2_project_external_approvals_coverage_text` permits prose only on an
  `unresolved` approval, so a decision never touches the coverage columns. A
  decision answers "was it granted?", not "what does it cover?" - the two are
  independent, and an approval can perfectly well be granted while its scope is
  still unresolved for a human to pin down (R10).
- A decided approval is final here. Re-deciding is refused rather than
  overwritten, because the row carries the attribution of who granted what -
  silently replacing it would destroy the audit answer the row exists to give.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import ProjectExternalApproval, ProjectExternalApprovalTask
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectMembership
from app.services.outbox import OutboxService

GATE_DECISIONS = ("approved", "rejected")
"""The subset of `EXTERNAL_APPROVAL_STATUSES` a human may write - `pending` is
instantiation's starting point, not a decision anyone records, which is also
why `decide` treats "not pending" as "already decided"."""


@dataclass(frozen=True)
class ExternalApprovalView:
    """One approval as the Execution tab needs it: the runtime decision, the
    coverage facts readiness uses, and enough of the gate (code, name) to name
    it to a human without the frontend having to fetch the planning layer."""

    id: uuid.UUID
    project_id: uuid.UUID
    project_gate_id: uuid.UUID
    gate_code: str
    gate_name: str
    status: str
    blocking: bool
    coverage_state: str
    coverage_text: str | None
    covered_task_ids: tuple[uuid.UUID, ...]
    decided_by: uuid.UUID | None
    decided_by_name: str | None
    decided_at: datetime | None


class ProjectGateDecisionService:
    def __init__(self, db: Session):
        self.db = db

    # ---- access / role resolution -----------------------------------

    def _actor_project_roles(self, project_id: uuid.UUID, actor: User) -> set[str]:
        employee = self.db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == actor.id))
        if not employee:
            return set()
        rows = self.db.scalars(
            select(V2ProjectMembership.project_role).where(
                V2ProjectMembership.project_id == project_id,
                V2ProjectMembership.employee_id == employee.id,
                V2ProjectMembership.ends_at.is_(None),
            )
        )
        return set(rows)

    def _require_access(self, project_id: uuid.UUID, actor: User) -> V2Project:
        project = self.db.get(V2Project, project_id)
        if not project:
            raise HTTPException(404, "Project not found.")
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return project
        if self._actor_project_roles(project_id, actor):
            return project
        raise HTTPException(403, "You do not have access to this project.")

    def _require_approver(self, project: V2Project, actor: User) -> None:
        """Mirrors `TaskApprovalService._require_approver` deliberately: the
        project's PM decides, with Admin standing in as the audited fallback
        (BR-007's PM-unavailable hierarchy). Granting an external approval is
        the same accountability as approving the work it gates, so it does not
        get a rule of its own."""
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return
        roles = self._actor_project_roles(project.id, actor)
        if "project_manager" in roles:
            return
        raise HTTPException(
            403,
            "Only the project's PM, or an authorized Admin fallback, can decide an external approval.",
        )

    def _get_approval(self, project_id: uuid.UUID, approval_id: uuid.UUID) -> ProjectExternalApproval:
        approval = self.db.scalar(
            select(ProjectExternalApproval).where(
                ProjectExternalApproval.id == approval_id,
                ProjectExternalApproval.project_id == project_id,
            )
        )
        if not approval:
            raise HTTPException(404, "External approval not found for this project.")
        return approval

    # ---- decide ------------------------------------------------------

    def decide(
        self,
        project_id: uuid.UUID,
        approval_id: uuid.UUID,
        decision: str,
        actor: User,
        reason: str | None = None,
    ) -> ExternalApprovalView:
        project = self._require_access(project_id, actor)

        if decision not in GATE_DECISIONS:
            raise HTTPException(422, "An approval decision must be 'approved' or 'rejected'.")

        clean_reason = (reason or "").strip() or None
        # Same rule as rejecting a task (`TaskApprovalService.approve`): a
        # refusal that says nothing leaves nobody able to act on it.
        if decision == "rejected" and not clean_reason:
            raise HTTPException(422, "A reason is required to reject an external approval.")

        self._require_approver(project, actor)
        approval = self._get_approval(project.id, approval_id)

        if approval.status != "pending":
            raise HTTPException(
                409,
                f"This external approval has already been {approval.status}; a recorded decision cannot be replaced.",
            )

        previous_status = approval.status
        decided_at = datetime.now(timezone.utc)
        # Assigned together, in one place: the completeness CHECK rejects any
        # row where status and the decided_by/decided_at pair disagree, and
        # coverage_state/coverage_text are deliberately untouched.
        approval.status = decision
        approval.decided_by = actor.id
        approval.decided_at = decided_at
        self.db.add(approval)

        audit_reason = clean_reason or f"External approval {decision} by the accountable PM/Admin."
        self.db.add(V2AuditEvent(
            actor_user_id=actor.id,
            action="PROJECT_EXTERNAL_APPROVAL_DECIDED",
            entity_type="project_external_approval",
            entity_id=approval.id,
            project_id=project.id,
            source="portal",
            before_json={"status": previous_status, "decided_by": None, "decided_at": None},
            after_json={
                "status": decision,
                "decided_by": str(actor.id),
                "decided_at": decided_at.isoformat(),
            },
            reason=audit_reason,
            occurred_at=decided_at,
        ))
        self.db.flush()

        # Emitted before the commit, inside the same transaction as the row it
        # describes - `OutboxService.emit` never commits, so the event and the
        # decision land together or not at all. `aggregate_type` is the
        # approval rather than the project on purpose: the dispatcher fans a
        # `project` aggregate out to the PM and Supervisor over WhatsApp, and
        # notifying on gate decisions is not this unit's call to make.
        OutboxService(self.db).emit(
            event_type="project_external_approval.decided",
            aggregate_type="project_external_approval",
            aggregate_id=approval.id,
            payload={
                "approval_id": str(approval.id),
                "project_id": str(project.id),
                "project_gate_id": str(approval.project_gate_id),
                "decision": decision,
                "reason": clean_reason,
                "decided_by": str(actor.id),
                "decided_at": decided_at.isoformat(),
                "blocking": approval.blocking,
            },
            idempotency_key=f"project_external_approval:{approval.id}:project_external_approval.decided",
        )

        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(approval)
        # The decided row is returned in the same shape the listing uses, so a
        # caller can drop it straight back into the list it came from without
        # a second round trip.
        return self._view_for_approval(approval)

    # ---- read --------------------------------------------------------

    @staticmethod
    def _view(
        approval: ProjectExternalApproval,
        gate: V2ProjectExternalGate,
        covered_task_ids,
        decided_by_name: str | None,
    ) -> ExternalApprovalView:
        return ExternalApprovalView(
            id=approval.id,
            project_id=approval.project_id,
            project_gate_id=approval.project_gate_id,
            gate_code=gate.original_code,
            gate_name=gate.approval_name,
            status=approval.status,
            blocking=approval.blocking,
            coverage_state=approval.coverage_state,
            coverage_text=approval.coverage_text,
            covered_task_ids=tuple(covered_task_ids),
            decided_by=approval.decided_by,
            decided_by_name=decided_by_name,
            decided_at=approval.decided_at,
        )

    def _view_for_approval(self, approval: ProjectExternalApproval) -> ExternalApprovalView:
        """Single-row counterpart to `list_for_project`'s batched build - used
        by `decide`, where exactly one approval is in hand."""
        gate = self.db.get(V2ProjectExternalGate, approval.project_gate_id)
        covered_task_ids = list(self.db.scalars(
            select(ProjectExternalApprovalTask.task_id)
            .where(ProjectExternalApprovalTask.approval_id == approval.id)
            .order_by(ProjectExternalApprovalTask.task_id.asc())
        ))
        decided_by_name = (
            self.db.scalar(select(User.name).where(User.id == approval.decided_by))
            if approval.decided_by else None
        )
        return self._view(approval, gate, covered_task_ids, decided_by_name)

    def list_for_project(self, project_id: uuid.UUID, actor: User) -> list[ExternalApprovalView]:
        """Every execution-layer approval on one project, with the gate's
        identity, the decision, the coverage facts and the covered task ids.

        Read access is any active project member - a Supervisor must be able
        to see what is holding up their site even though `_require_approver`
        will not let them decide it.

        Three flat queries rather than a join per approval: the Execution tab
        renders the whole list at once, and a per-row lookup would grow with
        the project."""
        project = self._require_access(project_id, actor)

        rows = self.db.execute(
            select(ProjectExternalApproval, V2ProjectExternalGate)
            .join(V2ProjectExternalGate, V2ProjectExternalGate.id == ProjectExternalApproval.project_gate_id)
            .where(ProjectExternalApproval.project_id == project.id)
            .order_by(
                V2ProjectExternalGate.template_sequence.asc(),
                V2ProjectExternalGate.original_code.asc(),
            )
        ).all()
        if not rows:
            return []

        covered: dict[uuid.UUID, list[uuid.UUID]] = {}
        for link in self.db.scalars(
            select(ProjectExternalApprovalTask)
            .where(ProjectExternalApprovalTask.project_id == project.id)
            .order_by(ProjectExternalApprovalTask.task_id.asc())
        ):
            covered.setdefault(link.approval_id, []).append(link.task_id)

        decider_ids = {approval.decided_by for approval, _ in rows if approval.decided_by}
        decider_names: dict[uuid.UUID, str] = {}
        if decider_ids:
            decider_names = {
                row[0]: row[1]
                for row in self.db.execute(select(User.id, User.name).where(User.id.in_(decider_ids))).all()
            }

        return [
            self._view(
                approval,
                gate,
                covered.get(approval.id, ()),
                decider_names.get(approval.decided_by) if approval.decided_by else None,
            )
            for approval, gate in rows
        ]
