"""Phase 3 U3: daily/weekly report generation (R5/R6, BR-016).

Every payload is built from U1's `ProjectVisibilityService.summarize` plus
report-type-specific extras, then frozen into `ReportSnapshot.payload_json`
at generation time - see the plan's Key Technical Decision that a report
never silently changes after the fact.

Known gap, deliberately not solved here: R6 asks for "schedule movement
(from Phase 1's `task_schedule_revisions`)" but no such table (or any
task-reschedule mutation that would populate it) exists anywhere in Phase
1's actual implementation - only in this plan's own Context section. Adding
a new reschedule-mutation subsystem is out of this unit's scope (its Files
list only introduces `report_snapshots` and the report service/routes), so
`schedule_revisions` is always `[]` here, with this comment as the marker
for the follow-up that will need to land the real mutation and revisit this.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.execution_models import SupportAssignmentChange, Task, TaskSupportAssignment
from app.models import User
from app.project_models import ProjectRoleChange, V2Project
from app.report_models import REPORT_TYPES, ReportSnapshot
from app.routes.projects_v2 import get_project
from app.services.project_visibility import ProjectVisibilityService


def _pending_role_changes(db: Session, project_id: uuid.UUID) -> list[dict]:
    rows = db.scalars(
        select(ProjectRoleChange).where(
            ProjectRoleChange.project_id == project_id, ProjectRoleChange.status == "pending",
        )
    ).all()
    return [
        {
            "id": str(row.id), "role_type": row.role_type, "change_type": row.change_type,
            "reason_code": row.reason_code, "requested_at": row.requested_at.isoformat(),
        }
        for row in rows
    ]


def _ownership_changes_in_window(db: Session, project_id: uuid.UUID, start: datetime, end: datetime) -> dict:
    role_changes = db.scalars(
        select(ProjectRoleChange).where(
            ProjectRoleChange.project_id == project_id,
            ProjectRoleChange.status.in_(("approved", "rejected")),
            ProjectRoleChange.decided_at >= start,
            ProjectRoleChange.decided_at < end,
        )
    ).all()

    support_change_rows = db.execute(
        select(SupportAssignmentChange, TaskSupportAssignment)
        .join(TaskSupportAssignment, TaskSupportAssignment.id == SupportAssignmentChange.task_support_assignment_id)
        .where(
            TaskSupportAssignment.project_id == project_id,
            SupportAssignmentChange.created_at >= start,
            SupportAssignmentChange.created_at < end,
        )
    ).all()

    return {
        "role_changes": [
            {
                "id": str(row.id), "role_type": row.role_type, "status": row.status,
                "reason_code": row.reason_code, "decided_at": row.decided_at.isoformat() if row.decided_at else None,
            }
            for row in role_changes
        ],
        "support_changes": [
            {
                "id": str(change.id), "task_id": str(assignment.task_id), "reason_code": change.reason_code,
                "created_at": change.created_at.isoformat(),
            }
            for change, assignment in support_change_rows
        ],
    }


def _milestone_progress(db: Session, project_id: uuid.UUID) -> list[dict]:
    milestones = db.scalars(
        select(Task).where(Task.project_id == project_id, Task.task_kind == "milestone")
    ).all()
    return [
        {"id": str(t.id), "original_code": t.original_code, "title": t.title, "lifecycle_status": t.lifecycle_status}
        for t in milestones
    ]


class ReportGenerationService:
    def __init__(self, db: Session):
        self.db = db

    def _require_project(self, project_id: uuid.UUID, actor: User) -> V2Project:
        return get_project(self.db, project_id, actor)

    def _next_version_no(self, project_id: uuid.UUID, report_type: str, period_start: datetime, period_end: datetime) -> int:
        existing = self.db.scalars(
            select(ReportSnapshot.version_no).where(
                ReportSnapshot.project_id == project_id,
                ReportSnapshot.report_type == report_type,
                ReportSnapshot.period_start == period_start,
                ReportSnapshot.period_end == period_end,
            )
        ).all()
        return (max(existing) + 1) if existing else 1

    def _build_payload(self, project_id: uuid.UUID, actor: User, report_type: str, period_start: datetime, period_end: datetime) -> dict:
        summary = ProjectVisibilityService(self.db).summarize(project_id, actor)
        payload = {
            "summary": summary.model_dump(mode="json"),
            "role_and_support_changes_required": _pending_role_changes(self.db, project_id),
        }
        if report_type == "weekly":
            payload["milestone_progress"] = _milestone_progress(self.db, project_id)
            payload["schedule_revisions"] = []  # see module docstring - Phase 1 gap, not this unit's scope
            payload["ownership_changes"] = _ownership_changes_in_window(self.db, project_id, period_start, period_end)
            payload["management_decisions_required"] = {
                "pending_approvals": [t.model_dump(mode="json") for t in summary.pending_approvals],
                "reassignment_required": [r.model_dump(mode="json") for r in summary.reassignment_required],
                "approval_gates_at_risk": [g.model_dump(mode="json") for g in summary.approval_gates_at_risk],
            }
        return payload

    def generate(
        self, project_id: uuid.UUID, report_type: str, period_start: datetime, period_end: datetime, actor: User,
    ) -> ReportSnapshot:
        if report_type not in REPORT_TYPES:
            raise HTTPException(422, "report_type must be 'daily' or 'weekly'.")
        if period_end <= period_start:
            raise HTTPException(422, "period_end must be after period_start.")

        self._require_project(project_id, actor)

        payload = self._build_payload(project_id, actor, report_type, period_start, period_end)

        # Concurrent POSTs for the same (project_id, report_type, period)
        # can both read the same next version_no before either commits -
        # the DB's uq_v2_report_snapshots_period_version constraint catches
        # the resulting duplicate, but the second insert must retry with a
        # freshly recomputed version_no rather than surface a raw
        # IntegrityError as an unhandled 500.
        for attempt in range(2):
            version_no = self._next_version_no(project_id, report_type, period_start, period_end)
            snapshot = ReportSnapshot(
                project_id=project_id, report_type=report_type, period_start=period_start, period_end=period_end,
                version_no=version_no, payload_json=payload, generated_by=actor.id,
                generated_at=datetime.now(timezone.utc),
            )
            self.db.add(snapshot)
            try:
                self.db.commit()
            except IntegrityError:
                self.db.rollback()
                if attempt == 1:
                    raise HTTPException(409, "This report period was just generated by another request. Please retry.")
                continue
            else:
                self.db.refresh(snapshot)
                return snapshot

    def list_snapshots(
        self, project_id: uuid.UUID, actor: User, report_type: str | None = None,
    ) -> list[ReportSnapshot]:
        self._require_project(project_id, actor)
        statement = select(ReportSnapshot).where(ReportSnapshot.project_id == project_id)
        if report_type:
            statement = statement.where(ReportSnapshot.report_type == report_type)
        statement = statement.order_by(ReportSnapshot.period_start.desc(), ReportSnapshot.version_no.desc())
        return list(self.db.scalars(statement).all())
