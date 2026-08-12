"""U6/U7 read models.

Reasons carry codes and titles, never bare ids: R23 wants a site user to
read why work is held up without a second lookup per blocker.
"""

import uuid

from pydantic import BaseModel, ConfigDict, Field


class TaskReadinessReasonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: str
    """`predecessor`, `gate`, `excluded_predecessor`, or `unresolved_gate`."""
    code: str
    title: str
    detail: str
    status: str
    enforced: bool
    """False means the transition guard will not actually stop the task -
    the reason is information, not a block. Only `excluded_predecessor` and
    `unresolved_gate` are advisory today."""


class TaskReadinessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: uuid.UUID
    original_code: str
    title: str
    lifecycle_status: str
    state: str
    """`ready`, `blocked`, `in_progress`, `completed` or `cancelled`."""
    startable: bool
    reasons: list[TaskReadinessReasonOut] = Field(default_factory=list)
    guard_diverges: bool = False
    """KTD8: this task reads as startable because a Start-to-Start
    predecessor has begun, but the transition guard still requires that
    predecessor to be finished. The one accepted disagreement between the
    advisor and the guard; anything else is a defect."""


class ProjectTaskReadinessOut(BaseModel):
    project_id: uuid.UUID
    total: int
    startable_count: int
    items: list[TaskReadinessOut] = Field(default_factory=list)
    unresolved_gates: list[TaskReadinessReasonOut] = Field(default_factory=list)
    """Blocking gates that cover no task, so approving them releases
    nothing. Named rather than hidden - this is the demo's own stated
    limitation and the six broad-text gates in the 45-day template all land
    here until their coverage is authored."""
