from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Project, ProjectTask, TaskTemplate, User, UserRole
from app.schemas.requests import ProjectIn, ProjectUpdateIn
from app.services.serializers import ensure_project_access, project_row


def create_project_with_tasks(payload: ProjectIn, actor: User, db: Session) -> dict:
    pm_id = actor.id if actor.role == UserRole.project_manager else payload.project_manager_id
    target = payload.start_date + timedelta(days=44)
    project = Project(
        name=payload.name,
        client_name=payload.client_name,
        site_address=payload.site_address,
        start_date=payload.start_date,
        target_handover_date=target,
        project_manager_id=pm_id,
        supervisor_id=payload.supervisor_id,
    )
    db.add(project)
    db.flush()
    templates = db.scalars(select(TaskTemplate).order_by(TaskTemplate.day_no, TaskTemplate.sort_order)).all()
    for template in templates:
        scheduled = payload.start_date + timedelta(days=template.day_no - 1)
        db.add(ProjectTask(
            project_id=project.id,
            template_task_id=template.id,
            day_no=template.day_no,
            scheduled_date=scheduled,
            due_date=scheduled,
            title=template.title,
            category=template.category,
            description=template.description or template.default_notes or f"Complete: {template.title}",
            supervisor_instruction=template.supervisor_instruction or "Check the site work, coordinate vendor, add note, upload proof.",
            pm_instruction=template.pm_instruction or "Review supervisor note and proof before approval.",
            proof_required=template.proof_required or "One clear site photo or proof reference.",
            dependency_note=template.dependency_note,
        ))
    db.commit()
    return project_row(project, db)


def update_project_record(project_id, payload: ProjectUpdateIn, actor: User, db: Session) -> dict:
    project = ensure_project_access(db.get(Project, project_id), actor)
    project.name = payload.name
    project.client_name = payload.client_name
    project.site_address = payload.site_address
    project.status = payload.status
    project.supervisor_id = payload.supervisor_id
    if actor.role != UserRole.project_manager and payload.project_manager_id:
        project.project_manager_id = payload.project_manager_id
    db.commit()
    return project_row(project, db)
