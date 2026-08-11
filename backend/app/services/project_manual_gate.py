import re
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import EmployeeProfile, User, UserRole
from app.project_models import (
    V2AuditEvent,
    V2Project,
    V2ProjectExternalGate,
    V2ProjectExternalGateTask,
    V2ProjectMembership,
    V2ProjectTask,
)
from app.schemas.project_manual_gate import ProjectManualGateCreateIn, ProjectManualGateCreateOut

MANUAL_GATE_CODE = re.compile(r"^MANUAL-GATE-(\d+)$")


class ProjectManualGateService:
    def __init__(self, db: Session):
        self.db = db

    def _project_and_pm(self, project_id: uuid.UUID, actor: User) -> tuple[V2Project, User]:
        project = self.db.scalar(select(V2Project).where(V2Project.id == project_id).with_for_update())
        if not project:
            raise HTTPException(404, "Project not found.")
        # Same authority as deciding gate applicability: Admin. The gate still
        # records the project's PM as accountable for chasing it (below) - they
        # own the follow-up, not the decision to add it.
        if actor.role != UserRole.admin:
            raise HTTPException(403, "Only Admin can add a manual approval.")
        if project.status != "draft":
            raise HTTPException(409, "Manual approvals can only be added while the project is Draft.")
        pm = self.db.scalar(
            select(User)
            .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
            .join(V2ProjectMembership, V2ProjectMembership.employee_id == EmployeeProfile.id)
            .where(
                V2ProjectMembership.project_id == project.id,
                V2ProjectMembership.project_role == "project_manager",
                V2ProjectMembership.ends_at.is_(None),
                User.active.is_(True),
                User.role == UserRole.project_manager,
            )
            .order_by(V2ProjectMembership.starts_at.desc())
        )
        if not pm:
            raise HTTPException(422, "Assign an active Project Manager before adding an approval.")
        return project, pm

    def _next_code_sequence(self, project_id: uuid.UUID) -> tuple[str, int]:
        rows = self.db.execute(
            select(V2ProjectExternalGate.original_code, V2ProjectExternalGate.template_sequence)
            .where(V2ProjectExternalGate.project_id == project_id)
        ).all()
        used, maximum = set(), 0
        for code, sequence in rows:
            maximum = max(maximum, int(sequence))
            match = MANUAL_GATE_CODE.fullmatch(code or "")
            if match:
                used.add(int(match.group(1)))
        number = 1
        while number in used:
            number += 1
        return f"MANUAL-GATE-{number:03d}", maximum + 1

    def create(self, project_id: uuid.UUID, actor: User, payload: ProjectManualGateCreateIn) -> ProjectManualGateCreateOut:
        try:
            project, pm = self._project_and_pm(project_id, actor)
            tasks = list(self.db.scalars(
                select(V2ProjectTask).where(V2ProjectTask.id.in_(payload.affected_project_task_ids))
            )) if payload.affected_project_task_ids else []
            if len(tasks) != len(payload.affected_project_task_ids) or any(task.project_id != project.id for task in tasks):
                raise HTTPException(422, "Every affected task must belong to this project.")
            if payload.blocking and any(not task.included for task in tasks):
                raise HTTPException(422, "A blocking approval can reference only included project tasks.")

            code, sequence = self._next_code_sequence(project.id)
            required_value = payload.required_by_date.isoformat() if payload.required_by_type == "date" else str(payload.required_by_day)
            gate = V2ProjectExternalGate(
                project_id=project.id,
                template_version_id=None,
                template_gate_id=None,
                original_code=code,
                template_sequence=sequence,
                approval_name=payload.title,
                description=None,
                external_party=payload.external_party,
                required_by_type=payload.required_by_type,
                required_by_value=required_value,
                impact=payload.impact,
                mapping_classification="exact" if tasks else "unmapped",
                broad_mapping_text=None,
                requires_configuration=not bool(tasks),
                status="pending_review",
                applicability_state="applicable",
                source_type="project_manual",
                accountable_pm_user_id=pm.id,
                blocking=payload.blocking,
                creation_reason=payload.reason,
            )
            self.db.add(gate)
            self.db.flush()
            for task in tasks:
                self.db.add(V2ProjectExternalGateTask(
                    project_gate_id=gate.id,
                    project_task_id=task.id,
                    template_task_id=task.template_task_id,
                ))
            audit = V2AuditEvent(
                actor_user_id=actor.id,
                action="PROJECT_MANUAL_GATE_CREATED",
                entity_type="project_external_gate",
                entity_id=gate.id,
                project_id=project.id,
                source="portal",
                before_json=None,
                after_json={
                    "code": gate.original_code,
                    "title": gate.approval_name,
                    "source_type": gate.source_type,
                    "blocking": gate.blocking,
                    "affected_project_task_ids": [str(task.id) for task in tasks],
                    "accountable_pm_user_id": str(pm.id),
                },
                reason=payload.reason,
                occurred_at=datetime.now(timezone.utc),
            )
            self.db.add(audit)
            self.db.flush()
            self.db.commit()
        except HTTPException:
            self.db.rollback()
            raise
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(409, "A manual approval with this generated code already exists. Retry the request.") from exc
        except Exception:
            self.db.rollback()
            raise
        return ProjectManualGateCreateOut(
            project_id=project.id,
            gate_id=gate.id,
            code=gate.original_code,
            sequence=gate.template_sequence,
            title=gate.approval_name,
            external_party=gate.external_party,
            required_by_type=gate.required_by_type,
            required_by_value=gate.required_by_value,
            blocking=gate.blocking,
            affected_task_count=len(tasks),
            impact=gate.impact,
            source_type=gate.source_type,
            accountable_pm_user_id=gate.accountable_pm_user_id,
            audit_event_id=audit.id,
        )
