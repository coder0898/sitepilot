from dataclasses import dataclass
import uuid

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.project_models import V2ProjectTask


@dataclass(frozen=True)
class ProjectTaskReviewPage:
    items: list[V2ProjectTask]
    total: int
    page: int
    page_size: int


class ProjectTemplateReviewRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_tasks(
        self,
        project_id: uuid.UUID,
        *,
        search: str | None,
        phase: str | None,
        category: str | None,
        applicability: str | None,
        included: bool | None,
        source: str | None,
        page: int,
        page_size: int,
    ) -> ProjectTaskReviewPage:
        filters = [V2ProjectTask.project_id == project_id]
        term = (search or "").strip()
        if term:
            pattern = f"%{term}%"
            filters.append(or_(
                V2ProjectTask.original_code.ilike(pattern),
                V2ProjectTask.title.ilike(pattern),
                V2ProjectTask.description.ilike(pattern),
            ))
        if phase and phase.strip():
            filters.append(func.lower(V2ProjectTask.phase) == phase.strip().lower())
        if category and category.strip():
            filters.append(func.lower(V2ProjectTask.category) == category.strip().lower())
        if applicability:
            filters.append(V2ProjectTask.applicability == applicability)
        if included is not None:
            filters.append(V2ProjectTask.included.is_(included))
        if source and source.strip():
            filters.append(func.lower(V2ProjectTask.source_type) == source.strip().lower())

        total = self.db.scalar(
            select(func.count()).select_from(V2ProjectTask).where(*filters)
        ) or 0
        schedule_order = case(
            (V2ProjectTask.schedule_classification == "pre_activation", 0),
            (V2ProjectTask.schedule_classification == "execution", 1),
            else_=2,
        )
        day_order = case(
            (V2ProjectTask.schedule_classification == "pre_activation", 0),
            else_=func.coalesce(V2ProjectTask.planned_start_day, 32767),
        )
        rows = list(self.db.scalars(
            select(V2ProjectTask)
            .where(*filters)
            .order_by(
                schedule_order,
                day_order,
                V2ProjectTask.template_sequence,
                V2ProjectTask.original_code,
                V2ProjectTask.id,
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all())
        return ProjectTaskReviewPage(items=rows, total=int(total), page=page, page_size=page_size)

    def summary(self, project_id: uuid.UUID) -> dict[str, int]:
        row = self.db.execute(
            select(
                func.count(V2ProjectTask.id).label("total"),
                func.sum(case((V2ProjectTask.included.is_(True), 1), else_=0)).label("included"),
                func.sum(case((V2ProjectTask.included.is_(False), 1), else_=0)).label("excluded"),
                func.sum(case((V2ProjectTask.decision_state == "pending_review", 1), else_=0)).label("pending_review"),
                func.sum(case((V2ProjectTask.decision_state != "pending_review", 1), else_=0)).label("decided"),
                func.sum(case((V2ProjectTask.applicability == "mandatory", 1), else_=0)).label("mandatory"),
                func.sum(case((V2ProjectTask.applicability == "conditional", 1), else_=0)).label("conditional"),
            ).where(V2ProjectTask.project_id == project_id)
        ).mappings().one()
        return {key: int(value or 0) for key, value in row.items()}
