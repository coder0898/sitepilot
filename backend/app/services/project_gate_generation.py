from __future__ import annotations

import uuid
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import EmployeeProfile, User, UserRole
from app.project_models import (
    V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectExternalGateTask,
    V2ProjectMembership, V2ProjectTask,
)
from app.template_models import V2TemplateExternalGate, V2TemplateExternalGateTask, V2TemplateVersion

class ProjectGateGenerationService:
    def __init__(self, db: Session): self.db = db

    def _project(self, project_id: uuid.UUID) -> V2Project:
        project = self.db.scalar(select(V2Project).where(V2Project.id == project_id).with_for_update())
        if not project: raise HTTPException(404, "Project not found.")
        if project.status != "draft": raise HTTPException(409, "External gates can only be generated while the project is draft.")
        if not project.template_version_id: raise HTTPException(422, "Select a published template version first.")
        version = self.db.get(V2TemplateVersion, project.template_version_id)
        if not version or version.status != "published": raise HTTPException(409, "The selected template version is no longer published.")
        return project

    def _pm(self, project_id: uuid.UUID) -> User:
        row = self.db.execute(
            select(User)
            .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
            .join(V2ProjectMembership, V2ProjectMembership.employee_id == EmployeeProfile.id)
            .where(V2ProjectMembership.project_id == project_id,
                   V2ProjectMembership.project_role == "project_manager",
                   V2ProjectMembership.ends_at.is_(None), User.active.is_(True),
                   User.role == UserRole.project_manager)
            .order_by(V2ProjectMembership.starts_at.desc())
        ).scalar_one_or_none()
        if not row: raise HTTPException(422, "Assign an active Project Manager before generating external gates.")
        return row

    def generate(self, project_id: uuid.UUID, actor: User, *, commit: bool = True) -> dict:
        """`commit=False` lets project creation fold this into its own
        transaction. Callers that pass False own the rollback."""
        project = self._project(project_id)
        pm = self._pm(project.id)
        template_gates = list(self.db.scalars(
            select(V2TemplateExternalGate).where(V2TemplateExternalGate.template_version_id == project.template_version_id)
            .order_by(V2TemplateExternalGate.sequence_no, V2TemplateExternalGate.code, V2TemplateExternalGate.id)
        ))
        existing = list(self.db.scalars(
            select(V2ProjectExternalGate).where(V2ProjectExternalGate.project_id == project.id)
            .order_by(V2ProjectExternalGate.template_sequence, V2ProjectExternalGate.original_code)
        ))
        task_rows = list(self.db.scalars(select(V2ProjectTask).where(V2ProjectTask.project_id == project.id)))
        task_by_template = {row.template_task_id: row for row in task_rows if row.template_task_id}
        template_links = list(self.db.scalars(
            select(V2TemplateExternalGateTask).join(V2TemplateExternalGate, V2TemplateExternalGateTask.gate_id == V2TemplateExternalGate.id)
            .where(V2TemplateExternalGate.template_version_id == project.template_version_id)
        ))
        links_by_gate: dict[uuid.UUID, list[V2TemplateExternalGateTask]] = {}
        for link in template_links: links_by_gate.setdefault(link.gate_id, []).append(link)
        if existing:
            if [g.template_gate_id for g in existing] != [g.id for g in template_gates]:
                raise HTTPException(409, "Project gate generation is incomplete or does not match the selected template.")
            project_gate_by_template = {g.template_gate_id: g for g in existing}
            expected_pairs = {
                (project_gate_by_template[gate.id].id, link.template_task_id)
                for gate in template_gates if gate.mapping_classification == "exact"
                for link in links_by_gate.get(gate.id, [])
            }
            actual_pairs = set(self.db.execute(
                select(V2ProjectExternalGateTask.project_gate_id, V2ProjectExternalGateTask.template_task_id)
                .where(V2ProjectExternalGateTask.project_gate_id.in_([g.id for g in existing]))
            ).all())
            if actual_pairs != expected_pairs:
                raise HTTPException(409, "Project gate generation is incomplete or has invalid exact task mappings.")
            return {"project_id": project.id, "status": project.status, "generated_gate_count": len(existing), "created_gate_count": 0, "exact_mapping_count": len(actual_pairs), "no_op": True}
        for gate in template_gates:
            if gate.mapping_classification == "exact":
                missing = [link.template_task_id for link in links_by_gate.get(gate.id, []) if link.template_task_id not in task_by_template]
                if missing: raise HTTPException(409, "Generate project tasks before generating exact gate mappings.")

        created: list[V2ProjectExternalGate] = []
        try:
            for gate in template_gates:
                row = V2ProjectExternalGate(
                    project_id=project.id, template_version_id=project.template_version_id,
                    template_gate_id=gate.id, original_code=gate.code, template_sequence=gate.sequence_no,
                    approval_name=gate.approval_name, description=gate.description, external_party=gate.external_party,
                    required_by_type=gate.required_by_type, required_by_value=gate.required_by_value,
                    impact=gate.impact, mapping_classification=gate.mapping_classification,
                    broad_mapping_text=gate.broad_mapping_text, requires_configuration=gate.requires_configuration,
                    status="pending_review", source_type="template", accountable_pm_user_id=pm.id,
                )
                self.db.add(row); self.db.flush(); created.append(row)
                if gate.mapping_classification == "exact":
                    self.db.add_all([
                        V2ProjectExternalGateTask(project_gate_id=row.id, project_task_id=task_by_template[link.template_task_id].id, template_task_id=link.template_task_id)
                        for link in links_by_gate.get(gate.id, [])
                    ])
            self.db.flush()
            exact_count = sum(len(links_by_gate.get(g.template_gate_id, [])) for g in created if g.mapping_classification == "exact")
            self.db.add(V2AuditEvent(actor_user_id=actor.id, action="PROJECT_GATES_GENERATED", entity_type="project_external_gate_set",
                entity_id=project.id, project_id=project.id, source="portal", reason="Generated draft project external gates from the selected published template.",
                before_json={"generated_gate_count": 0}, after_json={"generated_gate_count": len(created), "exact_mapping_count": exact_count, "accountable_pm_user_id": str(pm.id)}))
            if commit:
                self.db.commit()
        except Exception:
            if commit:
                self.db.rollback()
            raise
        return {"project_id": project.id, "status": project.status, "generated_gate_count": len(created), "created_gate_count": len(created), "exact_mapping_count": exact_count, "no_op": False}

    def list(self, project_id: uuid.UUID, actor: User) -> dict:
        project = self.db.get(V2Project, project_id)
        if not project: raise HTTPException(404, "Project not found.")
        # Route-level project visibility is intentionally mirrored without importing route helpers.
        if actor.role not in {UserRole.super_admin, UserRole.admin}:
            employee = self.db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == actor.id))
            allowed = employee and self.db.scalar(select(V2ProjectMembership.id).where(V2ProjectMembership.project_id == project.id, V2ProjectMembership.employee_id == employee.id, V2ProjectMembership.ends_at.is_(None)))
            if not allowed: raise HTTPException(403, "You do not have access to this project.")
        gates = list(self.db.scalars(select(V2ProjectExternalGate).where(V2ProjectExternalGate.project_id == project.id).order_by(V2ProjectExternalGate.template_sequence, V2ProjectExternalGate.original_code)))
        counts = dict(self.db.execute(select(V2ProjectExternalGateTask.project_gate_id, func.count()).where(V2ProjectExternalGateTask.project_gate_id.in_([g.id for g in gates] or [uuid.uuid4()])).group_by(V2ProjectExternalGateTask.project_gate_id)).all())
        users = {u.id: u for u in self.db.scalars(select(User).where(User.id.in_([g.accountable_pm_user_id for g in gates] or [uuid.uuid4()]))) }
        return {"project_id": project.id, "total": len(gates), "items": [{
            "id": g.id, "code": g.original_code, "sequence": g.template_sequence, "approval_name": g.approval_name,
            "description": g.description, "external_party": g.external_party, "required_by_type": g.required_by_type,
            "required_by_value": g.required_by_value, "impact": g.impact, "mapping_classification": g.mapping_classification,
            "broad_mapping_text": g.broad_mapping_text, "requires_configuration": g.requires_configuration, "status": g.status,
            "applicability_state": g.applicability_state, "source": g.source_type, "accountable_pm_user_id": g.accountable_pm_user_id,
            "accountable_pm_name": users.get(g.accountable_pm_user_id).name if users.get(g.accountable_pm_user_id) else "Project Manager",
            "exact_task_count": counts.get(g.id, 0), "blocking": g.blocking, "creation_reason": g.creation_reason,
        } for g in gates]}
