from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Project, ProjectTask, TaskStatus, User, UserRole, Vendor


def public_user(user: User) -> dict:
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "phone": user.phone,
        "role": user.role.value,
        "active": user.active,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def public_vendor(vendor: Vendor) -> dict:
    return {
        "id": str(vendor.id),
        "name": vendor.name,
        "category": vendor.category,
        "contact_person": vendor.contact_person,
        "phone": vendor.phone,
        "whatsapp": vendor.whatsapp,
        "notes": vendor.notes,
    }


def task_row(task: ProjectTask) -> dict:
    return {
        "id": str(task.id),
        "project_id": str(task.project_id),
        "day_no": task.day_no,
        "scheduled_date": task.scheduled_date.isoformat(),
        "due_date": (task.due_date or task.scheduled_date).isoformat(),
        "title": task.title,
        "category": task.category,
        "vendor_id": str(task.vendor_id) if task.vendor_id else None,
        "vendor": public_vendor(task.vendor) if task.vendor else None,
        "status": task.status.value,
        "description": task.description,
        "supervisor_instruction": task.supervisor_instruction,
        "pm_instruction": task.pm_instruction,
        "proof_required": task.proof_required,
        "dependency_note": task.dependency_note,
        "admin_note": task.admin_note,
        "supervisor_note": task.supervisor_note,
        "delay_reason": task.delay_reason,
        "proof_url": task.proof_url,
        "submitted_at": task.submitted_at.isoformat() if task.submitted_at else None,
        "approved_at": task.approved_at.isoformat() if task.approved_at else None,
        "rejection_reason": task.rejection_reason,
    }


def project_row(project: Project, db: Session) -> dict:
    tasks = db.scalars(select(ProjectTask).where(ProjectTask.project_id == project.id)).all()
    total = len(tasks)
    approved = len([task for task in tasks if task.status == TaskStatus.completed])
    submitted = len([task for task in tasks if task.status == TaskStatus.submitted])
    delayed = len([task for task in tasks if task.status in {TaskStatus.delayed, TaskStatus.blocked, TaskStatus.rejected}])
    pm = db.get(User, project.project_manager_id)
    supervisor = db.get(User, project.supervisor_id)
    return {
        "id": str(project.id),
        "name": project.name,
        "client_name": project.client_name,
        "site_address": project.site_address,
        "start_date": project.start_date.isoformat(),
        "target_handover_date": project.target_handover_date.isoformat(),
        "project_manager_id": str(project.project_manager_id),
        "supervisor_id": str(project.supervisor_id),
        "project_manager_name": pm.name if pm else "Unassigned",
        "supervisor_name": supervisor.name if supervisor else "Unassigned",
        "status": project.status,
        "total_tasks": total,
        "approved_tasks": approved,
        "submitted_tasks": submitted,
        "delayed_tasks": delayed,
        "progress": round((approved / total) * 100) if total else 0,
    }


def visible_projects_query(user: User):
    stmt = select(Project).order_by(Project.created_at.desc())
    if user.role == UserRole.project_manager:
        stmt = stmt.where(Project.project_manager_id == user.id)
    if user.role == UserRole.supervisor:
        stmt = stmt.where(Project.supervisor_id == user.id)
    return stmt


def ensure_project_access(project: Project | None, user: User) -> Project:
    if not project:
        raise HTTPException(404, "Project not found.")
    if user.role == UserRole.project_manager and project.project_manager_id != user.id:
        raise HTTPException(403, "Project not assigned to you.")
    if user.role == UserRole.supervisor and project.supervisor_id != user.id:
        raise HTTPException(403, "Project not assigned to you.")
    return project
