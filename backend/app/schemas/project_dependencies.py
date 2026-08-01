import uuid
from pydantic import BaseModel, ConfigDict

class ProjectDependencyGenerateOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: uuid.UUID
    status: str
    generated_dependency_count: int
    created_dependency_count: int
    excluded_warning_count: int
    no_op: bool

class ProjectDependencyItem(BaseModel):
    id: uuid.UUID
    sequence: int
    dependency_type: str
    blocking: bool
    rule_text: str | None
    predecessor_project_task_id: uuid.UUID
    predecessor_code: str
    predecessor_title: str
    predecessor_included: bool
    successor_project_task_id: uuid.UUID
    successor_code: str
    successor_title: str
    successor_included: bool
    excluded_task_warning: bool
    source: str

class ProjectDependencyListOut(BaseModel):
    project_id: uuid.UUID
    total: int
    excluded_warning_count: int
    items: list[ProjectDependencyItem]
