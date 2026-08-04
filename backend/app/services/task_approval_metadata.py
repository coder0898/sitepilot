"""Structured task-class / approval metadata for the execution UI.

Everything here is derived, at read time, from a task's already-persisted
`task_kind`/`task_class`/`lifecycle_status` - per BR-008's exact rule and
`TaskVerificationService`/`TaskApprovalService`'s actual decision-service
transitions (see task_lifecycle.py's `_DECISION_SERVICE_ONLY_TARGETS`).
No new columns or migration: this is a read-side projection, not new state.

Per the PRD/MVP scope, only `task_class in ('standard', 'class_a')` and
`task_kind in ('work', 'approval_gate', 'milestone')` exist - there is no
Class B/C or a distinct Admin-approval class. Admin only ever acts as an
audited fallback for the Supervisor/PM roles named below (BR-007), never as
a class of its own.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.execution_models import is_work_task_kind

# `approval_summary` - the human-readable decision path this task's kind/
# class requires before it can complete:
#   - milestone: none (system-derived auto-completion)
#   - standard work: Supervisor verification only
#   - class_a work: Supervisor verification, then PM approval
#   - approval_gate: PM approval only (BR-008: gates skip verification)
APPROVAL_SUMMARY_NOT_REQUIRED = "not_required"
APPROVAL_SUMMARY_SUPERVISOR_VERIFICATION = "supervisor_verification"
APPROVAL_SUMMARY_SUPERVISOR_AND_PM = "supervisor_and_pm"
APPROVAL_SUMMARY_PM_APPROVAL = "pm_approval"

# `approval_status` - where the task currently sits in that decision path.
STATUS_NOT_REQUIRED = "not_required"
STATUS_NOT_STARTED = "not_started"
STATUS_AWAITING_VERIFICATION = "awaiting_verification"
STATUS_AWAITING_PM_APPROVAL = "awaiting_pm_approval"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_CANCELLED = "cancelled"


class ApprovalMetadataOut(BaseModel):
    task_class: str | None
    task_kind: str | None
    verification_required: bool
    approval_required: bool
    verifier_role: str | None
    approver_role: str | None
    approval_summary: str
    approval_status: str
    blocks_dependents_until_approved: bool

    model_config = ConfigDict(from_attributes=False)


def build_approval_metadata(task_kind: str | None, task_class: str | None, lifecycle_status: str) -> ApprovalMetadataOut:
    # `task_kind` is nullable - a task with no kind assigned during template
    # authoring is treated as ordinary `work` (see is_work_task_kind), the
    # same normalization TaskVerificationService.verify and
    # TaskDecisionModal's resolveAction use, so this summary never promises
    # a decision the actual verify/approve path won't accept.
    work_kind = is_work_task_kind(task_kind)
    verification_required = work_kind
    approval_required = task_kind == "approval_gate" or (work_kind and task_class == "class_a")

    if task_kind == "milestone":
        approval_summary = APPROVAL_SUMMARY_NOT_REQUIRED
        verifier_role: str | None = None
        approver_role: str | None = None
    elif task_kind == "approval_gate":
        approval_summary = APPROVAL_SUMMARY_PM_APPROVAL
        verifier_role = None
        approver_role = "project_manager"
    elif task_class == "class_a":
        approval_summary = APPROVAL_SUMMARY_SUPERVISOR_AND_PM
        verifier_role = "site_supervisor"
        approver_role = "project_manager"
    else:
        # standard work (or an unclassified task - task_kind/task_class are
        # both nullable on legacy rows, treated as standard work).
        approval_summary = APPROVAL_SUMMARY_SUPERVISOR_VERIFICATION
        verifier_role = "site_supervisor"
        approver_role = None

    if not verification_required and not approval_required:
        approval_status = STATUS_NOT_REQUIRED
    elif lifecycle_status in ("planned", "ready", "in_progress"):
        approval_status = STATUS_NOT_STARTED
    elif lifecycle_status == "submitted":
        approval_status = STATUS_AWAITING_VERIFICATION if verification_required else STATUS_AWAITING_PM_APPROVAL
    elif lifecycle_status in ("verified", "approval_pending"):
        # `verified` is a persisted, readable state only for class_a work
        # awaiting PM approval - anything else auto-completes past it in
        # the same TaskVerificationService.verify call (BR-008). Guarded on
        # approval_required (not assumed) so this never claims a PM step
        # exists for a task with no PM mechanism available.
        approval_status = STATUS_AWAITING_PM_APPROVAL if approval_required else STATUS_NOT_STARTED
    elif lifecycle_status == "rejected":
        approval_status = STATUS_REJECTED
    elif lifecycle_status == "completed":
        approval_status = STATUS_APPROVED
    elif lifecycle_status == "cancelled":
        approval_status = STATUS_CANCELLED
    else:
        approval_status = STATUS_NOT_STARTED

    return ApprovalMetadataOut(
        task_class=task_class,
        task_kind=task_kind,
        verification_required=verification_required,
        approval_required=approval_required,
        verifier_role=verifier_role,
        approver_role=approver_role,
        approval_summary=approval_summary,
        approval_status=approval_status,
        blocks_dependents_until_approved=approval_required,
    )
