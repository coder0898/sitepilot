"""Phase 3 U1: response shape for `ProjectVisibilityService.summarize`.

One schema shared by U2's dashboard route and U3's report generator (both
call the same service) - see the plan's Key Technical Decision that the two
must never disagree on these numbers for the same project at the same
instant.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class TaskRefOut(BaseModel):
    id: uuid.UUID
    original_code: str
    title: str
    lifecycle_status: str


class OverdueTaskOut(TaskRefOut):
    due_at: datetime


class ComputedDelayOut(TaskRefOut):
    """45-day POC U10: delay as a measurement, not an entry.

    `delay_days` is the completion reference minus the target finish -
    actual finish where the task has one, otherwise now - floored at zero.
    Getting those operands the other way round yields zero for every late
    task and silently neutralises the at-risk flag built on the same
    number, so the order matters more than it looks.
    """

    target_finish_at: datetime
    actual_finish_at: datetime | None
    delay_days: int
    projected_finish_at: datetime
    """Target finish plus the delay accrued so far - what the task is now
    on course to finish by."""


class NoUpdateTaskOut(TaskRefOut):
    last_activity_at: datetime
    update_sla_hours: int


class ApprovalGateAtRiskOut(TaskRefOut):
    due_at: datetime | None


class ReassignmentRequiredOut(BaseModel):
    membership_id: uuid.UUID
    role_type: str
    employee_id: uuid.UUID
    availability: str


class ProjectVisibilitySummary(BaseModel):
    project_id: uuid.UUID
    generated_at: datetime

    status_counts: dict[str, int]
    planned_count: int
    active_count: int
    completed_count: int
    cancelled_count: int
    total_count: int

    blocked_tasks: list[TaskRefOut]
    delayed_tasks: list[TaskRefOut]
    overdue_tasks: list[OverdueTaskOut]
    no_update_tasks: list[NoUpdateTaskOut]

    pending_verifications: list[TaskRefOut]
    pending_approvals: list[TaskRefOut]
    approval_gates_at_risk: list[ApprovalGateAtRiskOut]

    reassignment_required: list[ReassignmentRequiredOut]

    # 45-day POC U10. Added, never replacing - every field above is
    # unchanged so already-shipped screens keep working (R48).
    computed_delays: list[ComputedDelayOut] = Field(default_factory=list)
    handover_at_risk: bool = False
    handover_at_risk_tasks: list[ComputedDelayOut] = Field(default_factory=list)
    """The tasks whose projected finish passes the project's handover date -
    named, not counted, so the answer to "why is this at risk?" needs no
    second lookup."""
    target_handover_date: date | None = None
