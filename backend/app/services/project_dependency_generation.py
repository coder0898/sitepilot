from __future__ import annotations
import uuid
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import User
from app.project_models import V2AuditEvent, V2Project, V2ProjectTask, V2ProjectTaskDependency
from app.template_models import V2TemplateTaskDependency, V2TemplateVersion

class ProjectDependencyGenerationService:
    def __init__(self, db: Session): self.db = db

    def generate(self, project: V2Project, actor: User) -> dict:
        if project.status != "draft": raise HTTPException(409, "Dependencies can only be generated while the project is draft.")
        if not project.template_version_id: raise HTTPException(422, "Attach a published template before generating dependencies.")
        version = self.db.get(V2TemplateVersion, project.template_version_id)
        if not version or version.status != "published": raise HTTPException(409, "The selected template version is no longer published.")
        template_rows = list(self.db.scalars(select(V2TemplateTaskDependency).where(V2TemplateTaskDependency.template_version_id == version.id).order_by(V2TemplateTaskDependency.sequence_no, V2TemplateTaskDependency.id)))
        project_tasks = list(self.db.scalars(select(V2ProjectTask).where(V2ProjectTask.project_id == project.id)))
        task_by_template = {row.template_task_id: row for row in project_tasks if row.template_task_id}
        missing = [row for dep in template_rows for row in (dep.predecessor_task_id, dep.successor_task_id) if row not in task_by_template]
        if missing: raise HTTPException(409, "Generate the complete project task snapshot before dependencies.")
        expected = [
            (dep.id, task_by_template[dep.predecessor_task_id].id, task_by_template[dep.successor_task_id].id, dep.dependency_type)
            for dep in template_rows
        ]
        existing = list(self.db.scalars(select(V2ProjectTaskDependency).where(V2ProjectTaskDependency.project_id == project.id).order_by(V2ProjectTaskDependency.template_sequence, V2ProjectTaskDependency.id)))
        if existing:
            actual = [(row.template_dependency_id, row.predecessor_project_task_id, row.successor_project_task_id, row.dependency_type) for row in existing]
            if actual != expected: raise HTTPException(409, "Project dependency generation is incomplete or does not match the selected template.")
            return {"project_id": project.id, "status": project.status, "generated_dependency_count": len(existing), "created_dependency_count": 0, "excluded_warning_count": sum(1 for row in existing if row.excluded_task_warning), "no_op": True}
        generated=[]
        for dep in template_rows:
            predecessor=task_by_template[dep.predecessor_task_id]; successor=task_by_template[dep.successor_task_id]
            generated.append(V2ProjectTaskDependency(project_id=project.id, template_version_id=version.id, template_dependency_id=dep.id, predecessor_project_task_id=predecessor.id, successor_project_task_id=successor.id, dependency_type=dep.dependency_type, blocking=dep.blocking, rule_text=dep.rule_text, template_sequence=dep.sequence_no, excluded_task_warning=(not predecessor.included or not successor.included), source_type="template", lifecycle_status="draft"))
        try:
            self.db.add_all(generated); self.db.flush()
            self.db.add(V2AuditEvent(actor_user_id=actor.id, action="PROJECT_DEPENDENCIES_GENERATED", entity_type="project", entity_id=project.id, project_id=project.id, source="portal", reason="Generated draft project dependencies from the selected published template.", before_json={"generated_dependency_count":0}, after_json={"generated_dependency_count":len(generated),"excluded_warning_count":sum(1 for row in generated if row.excluded_task_warning)}))
            self.db.commit()
        except Exception:
            self.db.rollback(); raise
        return {"project_id": project.id, "status": project.status, "generated_dependency_count": len(generated), "created_dependency_count": len(generated), "excluded_warning_count": sum(1 for row in generated if row.excluded_task_warning), "no_op": False}

    def list(self, project: V2Project) -> dict:
        rows=list(self.db.scalars(select(V2ProjectTaskDependency).where(V2ProjectTaskDependency.project_id==project.id).order_by(V2ProjectTaskDependency.template_sequence,V2ProjectTaskDependency.id)))
        task_ids={x for row in rows for x in (row.predecessor_project_task_id,row.successor_project_task_id)}
        tasks={t.id:t for t in self.db.scalars(select(V2ProjectTask).where(V2ProjectTask.id.in_(task_ids or [uuid.uuid4()]))) }
        items=[]
        for row in rows:
            p=tasks.get(row.predecessor_project_task_id)
            s=tasks.get(row.successor_project_task_id)
            if not p or not s:
                # Keep review endpoint stable if a historical dependency references a missing task.
                # Do not fail the complete dependency page.
                items.append({
                    "id":row.id,"sequence":row.template_sequence,"dependency_type":row.dependency_type,
                    "blocking":row.blocking,"rule_text":row.rule_text,
                    "predecessor_project_task_id":row.predecessor_project_task_id,
                    "successor_project_task_id":row.successor_project_task_id,
                    "predecessor_code":None,"predecessor_title":"Missing task reference",
                    "predecessor_included":False,"successor_code":None,
                    "successor_title":"Missing task reference","successor_included":False,
                    "excluded_task_warning":True,"source":row.source_type
                })
                continue
            items.append({"id":row.id,"sequence":row.template_sequence,"dependency_type":row.dependency_type,"blocking":row.blocking,"rule_text":row.rule_text,"predecessor_project_task_id":p.id,"predecessor_code":p.original_code,"predecessor_title":p.title,"predecessor_included":p.included,"successor_project_task_id":s.id,"successor_code":s.original_code,"successor_title":s.title,"successor_included":s.included,"excluded_task_warning":(not p.included or not s.included),"source":row.source_type})
        return {"project_id":project.id,"total":len(items),"excluded_warning_count":sum(1 for x in items if x["excluded_task_warning"]),"items":items}
