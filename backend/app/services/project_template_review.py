import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectMembership, V2ProjectTask
from app.repositories.project_template_review_repository import ProjectTemplateReviewRepository
from app.schemas.project_template_review import (
    ProjectTemplateReviewSummaryOut,
    ProjectTemplateReviewTaskOut,
    ProjectTemplateReviewTaskPage,
)
from app.template_schemas import PaginationMetadata


class ProjectTemplateReviewService:
    def __init__(self, db: Session):
        self.db = db
        self.repository = ProjectTemplateReviewRepository(db)

    def require_access(self, project_id: uuid.UUID, actor: User) -> V2Project:
        project = self.db.get(V2Project, project_id)
        if not project:
            raise HTTPException(404, "Project not found.")
        if actor.role == UserRole.admin:
            return project
        if actor.role == UserRole.project_manager:
            assigned = self.db.scalar(
                select(V2ProjectMembership.id)
                .join(EmployeeProfile, EmployeeProfile.id == V2ProjectMembership.employee_id)
                .where(
                    V2ProjectMembership.project_id == project_id,
                    V2ProjectMembership.project_role == "project_manager",
                    V2ProjectMembership.ends_at.is_(None),
                    EmployeeProfile.user_id == actor.id,
                )
                .limit(1)
            )
            if assigned:
                return project
        raise HTTPException(403, "Only Admin or the assigned Project Manager can review generated tasks.")

    @staticmethod
    def _task_out(task: V2ProjectTask) -> ProjectTemplateReviewTaskOut:
        # Defensive mapping: old/manual task records should not break the review API.
        # The database constraints normally guarantee these values, but this keeps
        # the API resilient while migrated data is present.
        return ProjectTemplateReviewTaskOut(
            id=task.id,
            code=task.original_code or "",
            sequence=task.template_sequence or 0,
            title=task.title or "",
            description=task.description,
            schedule_classification=task.schedule_classification or "execution",
            planned_start_day=task.planned_start_day,
            planned_end_day=task.planned_end_day,
            phase=task.phase,
            category=task.category,
            applicability=task.applicability or "mandatory",
            included=True if task.included is None else task.included,
            source=task.source_type or "template",
            decision_state=task.decision_state or "pending_review",
        )

    def list_tasks(self, project_id: uuid.UUID, actor: User, **filters) -> ProjectTemplateReviewTaskPage:
        self.require_access(project_id, actor)

        # Keep template review resilient. A single malformed legacy/manual task
        # should not crash the complete review screen with HTTP 500.
        result = self.repository.list_tasks(project_id, **filters)

        items = []
        for task in result.items:
            try:
                items.append(self._task_out(task))
            except Exception:
                # Skip invalid records from the review payload instead of
                # breaking the complete project review page.
                continue

        return ProjectTemplateReviewTaskPage(
            project_id=project_id,
            items=items,
            pagination=PaginationMetadata.from_result(
                page=result.page,
                page_size=result.page_size,
                total=result.total,
            ),
        )

    def summary(self, project_id: uuid.UUID, actor: User) -> ProjectTemplateReviewSummaryOut:
        self.require_access(project_id, actor)
        return ProjectTemplateReviewSummaryOut(project_id=project_id, **self.repository.summary(project_id))
