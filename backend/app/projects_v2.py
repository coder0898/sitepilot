import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import current_user, require_roles
from app.database import get_db
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership, V2ProjectTask
from app.template_models import V2Template, V2TemplateTask, V2TemplateVersion
from app.schemas.projects import ProjectCreateIn, ProjectDeleteIn, ProjectMembershipEndIn, ProjectMembershipIn, ProjectStatusIn, ProjectUpdateIn

router = APIRouter(prefix="/api/v2/projects", tags=["v2-projects"])

PROJECT_STATUSES = {"draft", "active", "on_hold", "completed", "archived"}
ACCOUNTABLE_ROLES = {"project_manager", "site_supervisor"}
ROLE_TO_USER_ROLE = {
    "project_manager": UserRole.project_manager,
    "site_supervisor": UserRole.supervisor,
    "internal_employee": UserRole.internal_employee,
}


def clean_required(value: str | None, label: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise HTTPException(422, f"{label} is required.")
    return cleaned


def clean_optional(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def project_snapshot(project: V2Project) -> dict:
    return {
        "code": project.code,
        "name": project.name,
        "client_name": project.client_name,
        "site_address": project.site_address,
        "description": project.description,
        "start_date": project.start_date.isoformat(),
        "target_handover_date": project.target_handover_date.isoformat() if project.target_handover_date else None,
        "template_version_id": str(project.template_version_id) if project.template_version_id else None,
        "status": project.status,
    }


def add_audit(db: Session, actor: User, project: V2Project, action: str, reason: str, before: dict | None = None, after: dict | None = None, entity_type: str = "project", entity_id: uuid.UUID | None = None) -> None:
    db.add(V2AuditEvent(
        actor_user_id=actor.id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id or project.id,
        project_id=project.id,
        before_json=before,
        after_json=after,
        reason=reason,
    ))


def actor_employee(db: Session, actor: User) -> EmployeeProfile | None:
    return db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == actor.id))


def active_memberships(db: Session, project_id: uuid.UUID, role: str | None = None) -> list[V2ProjectMembership]:
    statement = select(V2ProjectMembership).where(V2ProjectMembership.project_id == project_id, V2ProjectMembership.ends_at.is_(None))
    if role:
        statement = statement.where(V2ProjectMembership.project_role == role)
    return list(db.scalars(statement.order_by(V2ProjectMembership.starts_at)).all())


def has_membership(db: Session, project_id: uuid.UUID, actor: User, roles: set[str] | None = None) -> bool:
    employee = actor_employee(db, actor)
    if not employee:
        return False
    statement = select(V2ProjectMembership.id).where(
        V2ProjectMembership.project_id == project_id,
        V2ProjectMembership.employee_id == employee.id,
        V2ProjectMembership.ends_at.is_(None),
    )
    if roles:
        statement = statement.where(V2ProjectMembership.project_role.in_(roles))
    return db.scalar(statement) is not None


def can_view(db: Session, project: V2Project, actor: User) -> bool:
    return actor.role in {UserRole.super_admin, UserRole.admin} or has_membership(db, project.id, actor)


def can_edit(db: Session, project: V2Project, actor: User) -> bool:
    return actor.role in {UserRole.super_admin, UserRole.admin} or (actor.role == UserRole.project_manager and has_membership(db, project.id, actor, {"project_manager"}))


def get_project(db: Session, project_id: uuid.UUID, actor: User) -> V2Project:
    project = db.get(V2Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found.")
    if not can_view(db, project, actor):
        raise HTTPException(403, "You do not have access to this project.")
    return project


def membership_json(db: Session, item: V2ProjectMembership) -> dict:
    employee = db.get(EmployeeProfile, item.employee_id)
    user = db.get(User, employee.user_id) if employee else None
    return {
        "id": str(item.id),
        "employee_id": str(item.employee_id),
        "user_id": str(user.id) if user else None,
        "name": user.name if user else "Unknown employee",
        "email": user.email if user else None,
        "employee_code": employee.employee_code if employee else None,
        "designation": employee.designation if employee else None,
        "project_role": item.project_role,
        "starts_at": item.starts_at.isoformat(),
        "ends_at": item.ends_at.isoformat() if item.ends_at else None,
        "assignment_reason": item.assignment_reason,
    }


def project_json(db: Session, project: V2Project, include_history: bool = False) -> dict:
    memberships = db.scalars(select(V2ProjectMembership).where(V2ProjectMembership.project_id == project.id).order_by(V2ProjectMembership.ends_at.is_(None).desc(), V2ProjectMembership.starts_at.desc())).all()
    active = [membership_json(db, item) for item in memberships if item.ends_at is None]
    roles = {item["project_role"] for item in active}
    result = {
        "id": str(project.id),
        **project_snapshot(project),
        "activated_at": project.activated_at.isoformat() if project.activated_at else None,
        "created_by": str(project.created_by),
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
        "memberships": active,
        "setup": {
            "has_project_manager": "project_manager" in roles,
            "has_site_supervisor": "site_supervisor" in roles,
            "has_template": project.template_version_id is not None,
            "has_target_handover_date": project.target_handover_date is not None,
            "activation_ready": ACCOUNTABLE_ROLES.issubset(roles) and project.template_version_id is not None and project.target_handover_date is not None,
        },
    }
    if include_history:
        result["membership_history"] = [membership_json(db, item) for item in memberships]
    return result


def role_reference(db: Session, role: UserRole) -> list[dict]:
    rows = db.execute(select(EmployeeProfile, User).join(User, User.id == EmployeeProfile.user_id).where(User.active.is_(True), User.role == role).order_by(User.name)).all()
    return [{
        "employee_id": str(profile.id), "user_id": str(user.id), "name": user.name, "email": user.email,
        "employee_code": profile.employee_code, "designation": profile.designation, "availability": profile.availability,
    } for profile, user in rows]


@router.get("/reference-data")
def reference_data(actor: User = Depends(current_user), db: Session = Depends(get_db)):
    can_assign_pm = actor.role in {UserRole.super_admin, UserRole.admin}
    can_assign_supervisor = actor.role in {UserRole.super_admin, UserRole.admin, UserRole.project_manager}
    can_assign_support = actor.role in {UserRole.super_admin, UserRole.admin, UserRole.project_manager, UserRole.supervisor}
    return {
        "project_managers": role_reference(db, UserRole.project_manager) if can_assign_pm else [],
        "supervisors": role_reference(db, UserRole.supervisor) if can_assign_supervisor else [],
        "internal_employees": role_reference(db, UserRole.internal_employee) if can_assign_support else [],
        "statuses": sorted(PROJECT_STATUSES),
    }


@router.get("/published-template-versions")
def published_template_versions(
    actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)),
    db: Session = Depends(get_db),
):
    """Return the stable project-form reference list of eligible templates."""
    rows = db.execute(
        select(V2Template, V2TemplateVersion)
        .join(V2TemplateVersion, V2TemplateVersion.template_id == V2Template.id)
        .where(V2TemplateVersion.status == "published")
        .order_by(
            V2TemplateVersion.is_current_published.desc(),
            V2Template.name.asc(),
            V2TemplateVersion.version_no.desc(),
        )
    ).all()
    return [
        {
            "template_id": str(template.id),
            "template_code": template.code,
            "template_name": template.name,
            "version_id": str(version.id),
            "version_no": version.version_no,
            "duration_days": version.duration_days,
            "status": version.status,
            "is_current_published": version.is_current_published,
        }
        for template, version in rows
    ]


@router.get("")
def list_projects(status_filter: str | None = Query(None, alias="status"), search: str | None = None, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    statement = select(V2Project).order_by(V2Project.updated_at.desc())
    if actor.role not in {UserRole.super_admin, UserRole.admin}:
        employee = actor_employee(db, actor)
        if not employee:
            return []
        visible_ids = select(V2ProjectMembership.project_id).where(V2ProjectMembership.employee_id == employee.id, V2ProjectMembership.ends_at.is_(None))
        statement = statement.where(V2Project.id.in_(visible_ids))
    if status_filter:
        if status_filter not in PROJECT_STATUSES:
            raise HTTPException(422, "Unknown project status.")
        statement = statement.where(V2Project.status == status_filter)
    if search and search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(or_(V2Project.code.ilike(term), V2Project.name.ilike(term), V2Project.client_name.ilike(term), V2Project.site_address.ilike(term)))
    return [project_json(db, project) for project in db.scalars(statement).all()]


def assign_membership(db: Session, project: V2Project, employee_id: uuid.UUID, project_role: str, reason: str, actor: User) -> V2ProjectMembership:
    expected_role = ROLE_TO_USER_ROLE.get(project_role)
    if not expected_role:
        raise HTTPException(422, "Unknown project role.")
    employee = db.get(EmployeeProfile, employee_id)
    user = db.get(User, employee.user_id) if employee else None
    if not employee or not user or not user.active or user.role != expected_role:
        raise HTTPException(422, f"Select an active {project_role.replace('_', ' ')} employee.")
    if employee.availability == "unavailable":
        raise HTTPException(409, f"{user.name} is currently unavailable and cannot receive a new project assignment.")
    current = active_memberships(db, project.id, project_role)
    if any(item.employee_id == employee_id for item in current):
        return next(item for item in current if item.employee_id == employee_id)
    now = datetime.now(timezone.utc)
    before = [membership_json(db, item) for item in current]
    if project_role in ACCOUNTABLE_ROLES:
        for item in current:
            item.ends_at = now
    membership = V2ProjectMembership(project_id=project.id, employee_id=employee_id, project_role=project_role, assigned_by=actor.id, assignment_reason=clean_required(reason, "Assignment reason"))
    db.add(membership)
    db.flush()
    add_audit(db, actor, project, "PROJECT_ROLE_REASSIGNED" if current else "PROJECT_ROLE_ASSIGNED", reason.strip(), {"memberships": before}, {"membership": membership_json(db, membership)}, "project_membership", membership.id)
    return membership


@router.post("", status_code=201)
def create_project(payload: ProjectCreateIn, actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)), db: Session = Depends(get_db)):
    """Create only the draft project shell and accountable memberships.

    Template task generation is deliberately deferred to the next Phase 3
    capability. All eligibility checks occur before the first write.
    """
    name = clean_required(payload.name, "Project name")
    client_name = clean_required(payload.client_name, "Client")
    site_address = clean_required(payload.site_address, "Location")
    if payload.target_handover_date and payload.target_handover_date < payload.start_date:
        raise HTTPException(422, "Target handover date cannot be before the proposed start date.")

    template_version = db.get(V2TemplateVersion, payload.template_version_id)
    if not template_version or template_version.status != "published":
        raise HTTPException(422, "Select a published template version.")

    def resolve_accountable_user(user_or_employee_id: uuid.UUID, expected_role: UserRole, label: str) -> tuple[User, EmployeeProfile]:
        # The accepted Phase 3 contract uses user IDs. Retain compatibility with
        # existing Phase 2 selectors that may still submit employee-profile IDs.
        user = db.get(User, user_or_employee_id)
        profile = db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == user_or_employee_id)) if user else None
        if not user:
            profile = db.get(EmployeeProfile, user_or_employee_id)
            user = db.get(User, profile.user_id) if profile else None
        if not user or not user.active or user.role != expected_role or not profile:
            raise HTTPException(422, f"Select an active {label} with the correct role.")
        if profile.availability == "unavailable":
            raise HTTPException(409, f"{user.name} is currently unavailable and cannot receive a new project assignment.")
        return user, profile

    _pm_user, pm_profile = resolve_accountable_user(
        payload.project_manager_user_id, UserRole.project_manager, "Project Manager"
    )
    _supervisor_user, supervisor_profile = resolve_accountable_user(
        payload.supervisor_user_id, UserRole.supervisor, "Supervisor"
    )

    code = clean_optional(payload.code)
    if code:
        code = code.upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{2,29}", code):
            raise HTTPException(422, "Use 3-30 uppercase letters, numbers or hyphens for the project code.")
    else:
        code = f"PRJ-{payload.start_date:%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"

    assignment_reason = clean_optional(payload.assignment_reason) or "Initial draft project assignment."
    project = V2Project(
        code=code,
        name=name,
        client_name=client_name,
        site_address=site_address,
        description=clean_optional(payload.description),
        start_date=payload.start_date,
        target_handover_date=payload.target_handover_date,
        template_version_id=template_version.id,
        status="draft",
        created_by=actor.id,
    )

    try:
        db.add(project)
        db.flush()
        db.add_all([
            V2ProjectMembership(
                project_id=project.id,
                employee_id=pm_profile.id,
                project_role="project_manager",
                assigned_by=actor.id,
                assignment_reason=assignment_reason,
            ),
            V2ProjectMembership(
                project_id=project.id,
                employee_id=supervisor_profile.id,
                project_role="site_supervisor",
                assigned_by=actor.id,
                assignment_reason=assignment_reason,
            ),
        ])
        db.flush()
        add_audit(
            db,
            actor,
            project,
            "PROJECT_CREATED",
            "Draft project created from published template reference; tasks not generated.",
            after={
                **project_snapshot(project),
                "project_manager_user_id": str(_pm_user.id),
                "supervisor_user_id": str(_supervisor_user.id),
                "generated_task_count": 0,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Project code or initial team assignment conflicts with an existing record.") from exc
    except Exception:
        db.rollback()
        raise

    db.refresh(project)
    return project_json(db, project, True)


@router.post("/{project_id}/generate-tasks")
def generate_project_tasks(
    project_id: uuid.UUID,
    actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)),
    db: Session = Depends(get_db),
):
    """Generate the immutable template-derived task snapshot for a draft project.

    This chunk intentionally creates task rows only. It does not calculate
    baseline dates, dependencies, gates, assignments, or activation state.
    """
    project = db.get(V2Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found.")
    if project.status != "draft":
        raise HTTPException(409, "Tasks can only be generated while the project is draft.")
    if not project.template_version_id:
        raise HTTPException(422, "Select a published template version before generating tasks.")

    template_version = db.get(V2TemplateVersion, project.template_version_id)
    if not template_version or template_version.status != "published":
        raise HTTPException(409, "The selected template version is no longer published.")

    template_tasks = list(db.scalars(
        select(V2TemplateTask)
        .where(V2TemplateTask.template_version_id == template_version.id)
        .order_by(V2TemplateTask.sequence_no.asc(), V2TemplateTask.code.asc(), V2TemplateTask.id.asc())
    ).all())
    if not template_tasks:
        raise HTTPException(422, "The selected published template contains no tasks.")

    existing = list(db.scalars(
        select(V2ProjectTask)
        .where(V2ProjectTask.project_id == project.id)
        .order_by(V2ProjectTask.template_sequence.asc(), V2ProjectTask.original_code.asc())
    ).all())
    if existing:
        expected_ids = [task.id for task in template_tasks]
        existing_ids = [task.template_task_id for task in existing]
        if existing_ids != expected_ids:
            raise HTTPException(409, "Project task generation is incomplete or does not match the selected template.")
        return {
            "project_id": str(project.id),
            "status": project.status,
            "template_version_id": str(template_version.id),
            "generated_task_count": len(existing),
            "created_task_count": 0,
            "no_op": True,
        }

    generated = [
        V2ProjectTask(
            project_id=project.id,
            template_version_id=template_version.id,
            template_task_id=task.id,
            original_code=task.code,
            template_sequence=task.sequence_no,
            title=task.title,
            description=task.description,
            schedule_classification=task.schedule_classification,
            planned_start_day=task.planned_start_day,
            planned_end_day=task.planned_end_day,
            phase=task.phase,
            category=task.category,
            applicability=task.applicability,
            task_class=task.task_class,
            task_kind=task.task_kind,
            evidence_required=task.evidence_required,
            duration_days=task.duration_days,
            source_type="template",
            lifecycle_status="draft",
        )
        for task in template_tasks
    ]

    try:
        db.add_all(generated)
        db.flush()
        add_audit(
            db,
            actor,
            project,
            "PROJECT_TASKS_GENERATED",
            "Generated draft project tasks from the selected published template.",
            before={"generated_task_count": 0},
            after={
                "template_version_id": str(template_version.id),
                "generated_task_count": len(generated),
                "first_task_code": generated[0].original_code,
                "last_task_code": generated[-1].original_code,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "project_id": str(project.id),
        "status": project.status,
        "template_version_id": str(template_version.id),
        "generated_task_count": len(generated),
        "created_task_count": len(generated),
        "no_op": False,
    }


@router.get("/{project_id}")
def project_detail(project_id: uuid.UUID, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    return project_json(db, get_project(db, project_id, actor), True)


@router.patch("/{project_id}")
def update_project(project_id: uuid.UUID, payload: ProjectUpdateIn, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, actor)
    if not can_edit(db, project, actor):
        raise HTTPException(403, "Only Admin or the assigned Project Manager can edit project details.")
    if project.status in {"completed", "archived"}:
        raise HTTPException(409, "Completed or archived projects cannot be edited.")
    before = project_snapshot(project)
    if payload.name is not None: project.name = clean_required(payload.name, "Project name")
    if payload.client_name is not None: project.client_name = clean_required(payload.client_name, "Client name")
    if payload.site_address is not None: project.site_address = clean_required(payload.site_address, "Site address")
    if payload.description is not None: project.description = clean_optional(payload.description)
    if payload.template_version_id is not None:
        if actor.role not in {UserRole.super_admin, UserRole.admin}:
            raise HTTPException(403, "Only Admin or Super Admin can attach the published template version.")
        if project.status != "draft":
            raise HTTPException(409, "A template can only be attached while the project is draft.")
        if project.template_version_id and project.template_version_id != payload.template_version_id:
            raise HTTPException(409, "The attached template version cannot be replaced through project details.")
        template_version = db.get(V2TemplateVersion, payload.template_version_id)
        if not template_version or template_version.status != "published":
            raise HTTPException(422, "Select a published template version.")
        project.template_version_id = template_version.id
    if payload.start_date is not None:
        if project.template_version_id and payload.start_date != project.start_date:
            raise HTTPException(409, "Start date cannot change after a template is applied. Use schedule revision later.")
        project.start_date = payload.start_date
    if payload.clear_target_handover_date:
        if project.status != "draft":
            raise HTTPException(409, "Target handover can only be cleared while the project is draft.")
        project.target_handover_date = None
    elif payload.target_handover_date is not None:
        project.target_handover_date = payload.target_handover_date
    if project.target_handover_date and project.target_handover_date < project.start_date:
        raise HTTPException(422, "Target handover date cannot be before the start date.")
    add_audit(db, actor, project, "PROJECT_DETAILS_UPDATED", payload.reason.strip(), before, project_snapshot(project))
    db.commit()
    db.refresh(project)
    return project_json(db, project, True)


@router.post("/{project_id}/memberships")
def set_membership(project_id: uuid.UUID, payload: ProjectMembershipIn, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, actor)
    if project.status in {"completed", "archived"}:
        raise HTTPException(409, "The team cannot change on a completed or archived project.")
    is_pm = has_membership(db, project.id, actor, {"project_manager"})
    is_supervisor = has_membership(db, project.id, actor, {"site_supervisor"})
    allowed = (payload.project_role == "project_manager" and actor.role == UserRole.admin) or (payload.project_role == "site_supervisor" and (actor.role == UserRole.admin or is_pm)) or (payload.project_role == "internal_employee" and (actor.role == UserRole.admin or is_pm or is_supervisor))
    if not allowed:
        raise HTTPException(403, "You do not have permission to assign this project role.")
    membership = assign_membership(db, project, payload.employee_id, payload.project_role, payload.reason, actor)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This project role already has an active assignment.") from exc
    return membership_json(db, membership)


@router.post("/{project_id}/memberships/{membership_id}/end")
def end_membership(project_id: uuid.UUID, membership_id: uuid.UUID, payload: ProjectMembershipEndIn, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, actor)
    membership = db.get(V2ProjectMembership, membership_id)
    if not membership or membership.project_id != project.id or membership.ends_at is not None:
        raise HTTPException(404, "Active project membership not found.")
    is_pm = has_membership(db, project.id, actor, {"project_manager"})
    is_supervisor = has_membership(db, project.id, actor, {"site_supervisor"})
    allowed = (membership.project_role == "project_manager" and actor.role == UserRole.admin) or (membership.project_role == "site_supervisor" and (actor.role == UserRole.admin or is_pm)) or (membership.project_role == "internal_employee" and (actor.role == UserRole.admin or is_pm or is_supervisor))
    if not allowed:
        raise HTTPException(403, "You do not have permission to end this project assignment.")
    if project.status == "active" and membership.project_role in ACCOUNTABLE_ROLES:
        raise HTTPException(409, "Replace this accountable role before ending it on an active project.")
    before = membership_json(db, membership)
    membership.ends_at = datetime.now(timezone.utc)
    add_audit(db, actor, project, "PROJECT_ROLE_ENDED", payload.reason.strip(), before, membership_json(db, membership), "project_membership", membership.id)
    db.commit()
    return membership_json(db, membership)


@router.post("/{project_id}/status")
def change_status(project_id: uuid.UUID, payload: ProjectStatusIn, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, actor)
    target = payload.status.strip().lower()
    allowed_transitions = {"draft": {"active", "archived"}, "active": {"on_hold", "completed", "archived"}, "on_hold": {"active", "completed", "archived"}, "completed": {"archived"}, "archived": set()}
    if target not in PROJECT_STATUSES:
        raise HTTPException(422, "Unknown project status.")
    if target == project.status:
        return project_json(db, project, True)
    if target not in allowed_transitions[project.status]:
        raise HTTPException(409, f"A {project.status.replace('_', ' ')} project cannot move to {target.replace('_', ' ')}.")
    is_pm = has_membership(db, project.id, actor, {"project_manager"})
    if target in {"active", "archived"} and actor.role != UserRole.admin:
        raise HTTPException(403, "Only Admin can activate or archive a project.")
    if target in {"on_hold", "completed"} and not (actor.role == UserRole.admin or is_pm):
        raise HTTPException(403, "Only Admin or the assigned Project Manager can make this status change.")
    if target == "active" and project.status == "draft":
        roles = {item.project_role for item in active_memberships(db, project.id)}
        missing = []
        if "project_manager" not in roles: missing.append("Project Manager")
        if "site_supervisor" not in roles: missing.append("Site Supervisor")
        if not project.template_version_id: missing.append("approved 45-day template")
        if not project.target_handover_date: missing.append("target handover date")
        if missing:
            raise HTTPException(409, "Project activation requires: " + ", ".join(missing) + ".")
        project.activated_at = datetime.now(timezone.utc)
        project.activated_by = actor.id
    before = project_snapshot(project)
    project.status = target
    add_audit(db, actor, project, "PROJECT_STATUS_CHANGED", payload.reason.strip(), before, project_snapshot(project))
    db.commit()
    db.refresh(project)
    return project_json(db, project, True)


@router.get("/{project_id}/activity")
def project_activity(project_id: uuid.UUID, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, actor)
    rows = db.execute(select(V2AuditEvent, User).outerjoin(User, User.id == V2AuditEvent.actor_user_id).where(V2AuditEvent.project_id == project.id).order_by(V2AuditEvent.occurred_at.desc()).limit(100)).all()
    return [{"id": str(event.id), "action": event.action, "entity_type": event.entity_type, "entity_id": str(event.entity_id), "actor_name": user.name if user else "System", "reason": event.reason, "before": event.before_json, "after": event.after_json, "occurred_at": event.occurred_at.isoformat()} for event, user in rows]


@router.delete("/{project_id}")
def delete_draft_project(project_id: uuid.UUID, payload: ProjectDeleteIn, actor: User = Depends(require_roles(UserRole.admin)), db: Session = Depends(get_db)):
    project = get_project(db, project_id, actor)
    if project.status != "draft" or project.template_version_id or active_memberships(db, project.id):
        raise HTTPException(409, "Only an unreferenced draft with no team or template can be permanently deleted. Archive this project instead.")
    if payload.confirmation.strip().upper() != project.code:
        raise HTTPException(422, f"Type {project.code} to confirm permanent deletion.")
    add_audit(db, actor, project, "PROJECT_DRAFT_DELETED", payload.reason.strip(), before=project_snapshot(project))
    db.flush()
    db.delete(project)
    db.commit()
    return {"deleted": True, "project_id": str(project_id)}
