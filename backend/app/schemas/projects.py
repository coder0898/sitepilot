from datetime import date
import uuid

from pydantic import BaseModel, Field


class ProjectCreateIn(BaseModel):
    code: str
    name: str
    client_name: str
    site_address: str
    description: str | None = None
    start_date: date
    target_handover_date: date | None = None
    project_manager_employee_id: uuid.UUID | None = None
    supervisor_employee_id: uuid.UUID | None = None
    assignment_reason: str | None = None


class ProjectUpdateIn(BaseModel):
    name: str | None = None
    client_name: str | None = None
    site_address: str | None = None
    description: str | None = None
    start_date: date | None = None
    target_handover_date: date | None = None
    clear_target_handover_date: bool = False
    reason: str = Field(min_length=4)


class ProjectMembershipIn(BaseModel):
    employee_id: uuid.UUID
    project_role: str
    reason: str = Field(min_length=4)


class ProjectMembershipEndIn(BaseModel):
    reason: str = Field(min_length=4)


class ProjectStatusIn(BaseModel):
    status: str
    reason: str = Field(min_length=4)


class ProjectDeleteIn(BaseModel):
    confirmation: str
    reason: str = Field(min_length=4)
