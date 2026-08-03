import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.execution_models import TASK_LIFECYCLE_STATUSES

TaskLifecycleStatus = Literal[
    "planned", "ready", "in_progress", "submitted", "verified",
    "approval_pending", "rejected", "completed", "cancelled",
]


class TaskStatusTransitionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_status: TaskLifecycleStatus
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        return cleaned or None

    @field_validator("target_status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in TASK_LIFECYCLE_STATUSES:
            raise ValueError("Unknown task lifecycle status.")
        return value


class TaskOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    baseline_id: uuid.UUID
    original_code: str
    title: str
    task_kind: str | None
    task_class: str | None
    lifecycle_status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskEvidenceOut(BaseModel):
    id: uuid.UUID
    file_id: uuid.UUID
    evidence_type: str
    caption: str | None
    original_filename: str
    mime_type: str
    size_bytes: int

    model_config = ConfigDict(from_attributes=True)


class TaskVerificationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["verified", "rejected"]
    remarks: str | None = Field(default=None, max_length=2000)

    @field_validator("remarks")
    @classmethod
    def normalize_remarks(cls, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        return cleaned or None


class TaskApprovalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approved", "rejected"]
    remarks: str | None = Field(default=None, max_length=2000)

    @field_validator("remarks")
    @classmethod
    def normalize_remarks(cls, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        return cleaned or None


class TaskVerificationOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    submission_update_id: uuid.UUID
    decision: str
    remarks: str | None
    verified_by: uuid.UUID
    verified_at: datetime
    task: TaskOut

    model_config = ConfigDict(from_attributes=True)


class TaskApprovalOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    verification_id: uuid.UUID | None
    decision: str
    remarks: str | None
    decided_by: uuid.UUID
    decided_at: datetime
    task: TaskOut

    model_config = ConfigDict(from_attributes=True)


class TaskBlockerCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    owner_employee_id: uuid.UUID | None = None

    @field_validator("type", "description")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("This field cannot be blank.")
        return cleaned


class TaskBlockerOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    project_id: uuid.UUID
    type: str
    description: str
    owner_employee_id: uuid.UUID | None
    started_at: datetime
    resolved_at: datetime | None
    resolved_by: uuid.UUID | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


DelayResponsibilityType = Literal[
    "vendor", "client", "approval", "design", "site_readiness", "internal", "other",
]


class TaskDelayCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    responsibility_type: DelayResponsibilityType
    responsible_vendor_id: uuid.UUID | None = None
    reason: str = Field(min_length=1, max_length=2000)
    impact_days: int = Field(gt=0)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("This field cannot be blank.")
        return cleaned


class TaskDelayOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    project_id: uuid.UUID
    responsibility_type: str
    responsible_vendor_id: uuid.UUID | None
    reason: str
    impact_days: int
    recorded_by: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskSupportAssignmentCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_id: uuid.UUID
    responsibility: str = Field(min_length=1, max_length=2000)

    @field_validator("responsibility")
    @classmethod
    def normalize_responsibility(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("This field cannot be blank.")
        return cleaned


class TaskSupportAssignmentEndIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason_code: str = Field(min_length=1, max_length=200)
    reason_detail: str | None = Field(default=None, max_length=2000)

    @field_validator("reason_code")
    @classmethod
    def normalize_reason_code(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("This field cannot be blank.")
        return cleaned

    @field_validator("reason_detail")
    @classmethod
    def normalize_reason_detail(cls, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        return cleaned or None


class TaskSupportAssignmentOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    project_id: uuid.UUID
    employee_id: uuid.UUID
    responsibility: str
    status: str
    starts_at: datetime
    ends_at: datetime | None
    assigned_by: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskProgressUpdateOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    project_id: uuid.UUID
    update_type: str
    status_claim: str | None
    note: str | None
    submitted_by: uuid.UUID
    source: str
    created_at: datetime
    evidence: list[TaskEvidenceOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class TaskListItemOut(BaseModel):
    """List row for the execution board (TaskExecutionBoard). Blockers and
    support assignments are summarized as counts here - the full detail
    (individual blocker/delay/verification/approval/support records) is
    only fetched per-task, via TaskDetailOut, when a row is expanded."""

    id: uuid.UUID
    project_id: uuid.UUID
    baseline_id: uuid.UUID
    original_code: str
    template_sequence: int
    title: str
    task_kind: str | None
    task_class: str | None
    lifecycle_status: str
    schedule_classification: str
    planned_start_day: int | None
    planned_end_day: int | None
    phase: str | None
    category: str | None
    evidence_required: bool
    open_blocker_count: int
    active_support_count: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskDependencyRefOut(BaseModel):
    id: uuid.UUID
    original_code: str
    title: str
    lifecycle_status: str
    task_kind: str | None
    task_class: str | None
    dependency_type: str
    blocking: bool


class TaskVerificationSummaryOut(BaseModel):
    id: uuid.UUID
    decision: str
    remarks: str | None
    verified_by: uuid.UUID
    verified_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskApprovalSummaryOut(BaseModel):
    id: uuid.UUID
    verification_id: uuid.UUID | None
    decision: str
    remarks: str | None
    decided_by: uuid.UUID
    decided_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskDetailOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    baseline_id: uuid.UUID
    original_code: str
    template_sequence: int
    title: str
    description: str | None
    task_kind: str | None
    task_class: str | None
    lifecycle_status: str
    schedule_classification: str
    planned_start_day: int | None
    planned_end_day: int | None
    phase: str | None
    category: str | None
    evidence_required: bool
    created_at: datetime
    updated_at: datetime
    predecessors: list[TaskDependencyRefOut] = Field(default_factory=list)
    progress_updates: list[TaskProgressUpdateOut] = Field(default_factory=list)
    verifications: list[TaskVerificationSummaryOut] = Field(default_factory=list)
    approvals: list[TaskApprovalSummaryOut] = Field(default_factory=list)
    blockers: list[TaskBlockerOut] = Field(default_factory=list)
    delays: list[TaskDelayOut] = Field(default_factory=list)
    support_assignments: list[TaskSupportAssignmentOut] = Field(default_factory=list)
