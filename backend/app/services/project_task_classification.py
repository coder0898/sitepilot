"""Draft-only Standard/Class A override for a project's copied tasks.

A project's tasks are copied from the published template when the project is
created (`generate_task_snapshot`), and activation copies them on into the
baseline and execution tasks. Changing `project_tasks.task_class` while the
project is still Draft is therefore the one place a per-project override can
live: it never touches the template, and active/closed projects cannot be
changed because the project must be Draft.
"""
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import is_work_task_kind
from app.models import User
from app.project_models import V2AuditEvent, V2Project, V2ProjectTask
from app.schemas.project_task_classification import (
    ProjectTaskClassificationItemOut,
    ProjectTaskClassificationListOut,
    ProjectTaskClassificationUpdateIn,
)
from app.services.project_template_review import ProjectTemplateReviewService
from app.template_models import V2TemplateTask


class ProjectTaskClassificationService:
    def __init__(self, db: Session):
        self.db = db

    def _require_access(self, project_id: uuid.UUID, actor: User) -> V2Project:
        # Same people who review the generated tasks: Admin, Super Admin and the assigned PM.
        return ProjectTemplateReviewService(self.db).require_access(project_id, actor)

    def list(self, project_id: uuid.UUID, actor: User) -> ProjectTaskClassificationListOut:
        project = self._require_access(project_id, actor)
        rows = self.db.execute(
            select(V2ProjectTask, V2TemplateTask.task_class)
            .outerjoin(V2TemplateTask, V2TemplateTask.id == V2ProjectTask.template_task_id)
            .where(V2ProjectTask.project_id == project.id)
            .order_by(V2ProjectTask.template_sequence.asc(), V2ProjectTask.original_code.asc())
        ).all()
        return ProjectTaskClassificationListOut(
            project_id=project.id,
            editable=project.status == "draft",
            items=[
                ProjectTaskClassificationItemOut(
                    id=task.id,
                    code=task.original_code or "",
                    sequence=task.template_sequence or 0,
                    title=task.title or "",
                    phase=task.phase,
                    task_kind=task.task_kind,
                    template_task_class=template_class,
                    task_class=task.task_class,
                    classifiable=is_work_task_kind(task.task_kind),
                )
                for task, template_class in rows
            ],
        )

    def update(
        self, project_id: uuid.UUID, actor: User, payload: ProjectTaskClassificationUpdateIn,
    ) -> ProjectTaskClassificationListOut:
        project = self._require_access(project_id, actor)
        if project.status != "draft":
            raise HTTPException(409, "Task classification can only be changed while the project is Draft.")

        wanted = {item.task_id: item.task_class for item in payload.items}
        if len(wanted) != len(payload.items):
            raise HTTPException(422, "Each task can appear only once.")

        tasks = self.db.scalars(
            select(V2ProjectTask)
            .where(V2ProjectTask.project_id == project.id, V2ProjectTask.id.in_(wanted))
            .with_for_update()
        ).all()
        if len(tasks) != len(wanted):
            raise HTTPException(404, "One or more tasks were not found in this project.")
        not_work = sorted(task.original_code for task in tasks if not is_work_task_kind(task.task_kind))
        if not_work:
            raise HTTPException(
                422,
                f"Approval gates and milestones cannot be set to Standard or Class A: {', '.join(not_work)}.",
            )

        now = datetime.now(timezone.utc)
        try:
            for task in tasks:
                new_class = wanted[task.id]
                if task.task_class == new_class:
                    continue
                before = task.task_class
                task.task_class = new_class
                self.db.add(V2AuditEvent(
                    actor_user_id=actor.id,
                    action="PROJECT_TASK_CLASSIFICATION_CHANGED",
                    entity_type="project_task",
                    entity_id=task.id,
                    project_id=project.id,
                    source="portal",
                    before_json={"code": task.original_code, "task_class": before},
                    after_json={"code": task.original_code, "task_class": new_class},
                    reason="Task classification set during Draft review.",
                    occurred_at=now,
                ))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.list(project.id, actor)
