"""U11: request/response shapes for execution-layer external approvals.

Kept out of `schemas/execution_tasks.py` because these describe an approval,
not a task - the two are related only in that an approval covers tasks, and an
approval's decision is not a task lifecycle event.

`ProjectExternalApprovalOut` is what U18's Execution tab renders: the runtime
status and its attribution, the `blocking`/`coverage_state` pair readiness
already reasons over, the prose an unresolved approval carries in place of
links (R10), and the covered task ids so the tab can point at the work being
held up.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectGateDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approved", "rejected"]
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        # Whitespace is not a reason. Normalising here means the service's
        # "rejection needs a reason" check sees None, not "   ".
        cleaned = (value or "").strip()
        return cleaned or None


class ProjectGateEvidenceOut(BaseModel):
    id: uuid.UUID
    file_id: uuid.UUID
    evidence_type: str
    caption: str | None
    original_filename: str
    mime_type: str
    size_bytes: int

    model_config = ConfigDict(from_attributes=True)


class ProjectGateSubmissionSummaryOut(BaseModel):
    """One past submission against an approval - the Admin's review context
    on a `submitted` gate, and PM/Supervisor's read-only history (R6).
    Mirrors `TaskProgressUpdateOut`'s shape for the same reason: append-only
    evidence trail, most recent first."""
    id: uuid.UUID
    submitted_by: uuid.UUID
    submitted_by_name: str | None
    note: str | None
    submitted_at: datetime
    evidence: list[ProjectGateEvidenceOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ProjectExternalApprovalOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_gate_id: uuid.UUID
    gate_code: str
    gate_name: str
    status: str
    blocking: bool
    coverage_state: str
    coverage_text: str | None
    covered_task_ids: list[uuid.UUID]
    assigned_to_user_id: uuid.UUID | None
    assigned_to_name: str | None
    assigned_by: uuid.UUID | None
    assigned_at: datetime | None
    rejection_reason: str | None
    decided_by: uuid.UUID | None
    decided_by_name: str | None
    decided_at: datetime | None
    submissions: list[ProjectGateSubmissionSummaryOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ProjectGateAssignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assignee_user_id: uuid.UUID


class ProjectGateSubmissionOut(BaseModel):
    id: uuid.UUID
    approval_id: uuid.UUID
    submitted_by: uuid.UUID
    note: str | None
    submitted_at: datetime
    approval: ProjectExternalApprovalOut

    model_config = ConfigDict(from_attributes=True)
