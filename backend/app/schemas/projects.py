from datetime import date
import uuid

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ProjectCreateIn(BaseModel):
    """Create a draft project anchored to one published V2 template version.

    The validation aliases retain compatibility with the existing Phase 2 field
    names while making the Phase 3 API vocabulary explicit.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    code: str | None = None
    name: str = Field(validation_alias=AliasChoices("name", "project_name"))
    client_name: str = Field(validation_alias=AliasChoices("client_name", "client"))
    site_address: str = Field(validation_alias=AliasChoices("site_address", "location"))
    description: str | None = None
    start_date: date = Field(validation_alias=AliasChoices("start_date", "proposed_start_date"))
    target_handover_date: date | None = None
    project_manager_user_id: uuid.UUID = Field(
        validation_alias=AliasChoices("project_manager_user_id", "pm_user_id")
    )
    supervisor_user_id: uuid.UUID
    template_version_id: uuid.UUID
    assignment_reason: str | None = None


class ProjectUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    client_name: str | None = None
    site_address: str | None = None
    description: str | None = None
    start_date: date | None = None
    target_handover_date: date | None = None
    template_version_id: uuid.UUID | None = None
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


class ProjectActivateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=4)


class ProjectTeamUpdateIn(BaseModel):
    project_manager_employee_id: uuid.UUID | None = None
    supervisor_employee_id: uuid.UUID | None = None
    reason: str = Field(min_length=4)


class ProjectRoleChangeRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_type: str
    replacement_employee_id: uuid.UUID
    change_type: str = "replacement"
    reason: str = Field(min_length=4)


class ProjectRoleChangeRejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=4)
