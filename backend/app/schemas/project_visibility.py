"""Phase 3 U1: response shape for `ProjectVisibilityService.summarize`.

One schema shared by U2's dashboard route and U3's report generator (both
call the same service) - see the plan's Key Technical Decision that the two
must never disagree on these numbers for the same project at the same
instant.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class TaskRefOut(BaseModel):
    id: uuid.UUID
    original_code: str
    title: str
    lifecycle_status: str


class OverdueTaskOut(TaskRefOut):
    due_at: datetime


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
