import uuid
from pydantic import BaseModel, ConfigDict

class ProjectGateGenerateOut(BaseModel):
    project_id: uuid.UUID
    status: str
    generated_gate_count: int
    created_gate_count: int
    exact_mapping_count: int
    no_op: bool

class ProjectGateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    sequence: int
    approval_name: str
    description: str | None
    external_party: str | None
    required_by_type: str | None
    required_by_value: str | None
    impact: str | None
    mapping_classification: str
    broad_mapping_text: str | None
    requires_configuration: bool
    status: str
    applicability_state: str
    source: str
    accountable_pm_user_id: uuid.UUID
    accountable_pm_name: str
    exact_task_count: int
    blocking: bool
    creation_reason: str | None

class ProjectGateListOut(BaseModel):
    project_id: uuid.UUID
    total: int
    items: list[ProjectGateOut]
