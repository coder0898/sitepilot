import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectTaskClassificationItemOut(BaseModel):
    id: uuid.UUID
    code: str
    sequence: int
    title: str
    phase: str | None
    task_kind: str | None
    # The published template's value this task was copied from; None for
    # project-manual tasks, which have no template row.
    template_task_class: str | None
    task_class: str | None
    # False for milestones and approval gates - Standard/Class A only applies
    # to ordinary work.
    classifiable: bool


class ProjectTaskClassificationListOut(BaseModel):
    project_id: uuid.UUID
    editable: bool
    items: list[ProjectTaskClassificationItemOut]


class ProjectTaskClassificationChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: uuid.UUID
    task_class: Literal["standard", "class_a"]


class ProjectTaskClassificationUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ProjectTaskClassificationChangeIn] = Field(min_length=1, max_length=1000)
