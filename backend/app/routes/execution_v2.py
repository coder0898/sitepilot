from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.auth import current_user, require_roles
from app.config import settings
from app.database import get_db
from app.models import ContractorCategory, ContractorRelationship, ExecutionDay, ExecutionProject, ExecutionProjectContractor, ExecutionTask, ExecutionTaskDelayReport, ExecutionTaskReschedule, ExecutionTaskStatusHistory, ExecutionTemplate, ExecutionTemplateTask, User, UserRole, Vendor, VendorCategory
from app.schemas.requests import ExecutionProjectContractorIn, ExecutionProjectIn, ExecutionProjectUpdateIn, ExecutionTaskDelayReportIn, ExecutionTaskIn, ExecutionTaskRescheduleIn, ExecutionTaskReviewIn, ExecutionTaskStatusIn, ExecutionTemplateIn
from app.services.history import record_new_task, set_task_status

router = APIRouter(prefix="/api/v2/execution", tags=["execution-v2"])
MANAGERS = (UserRole.super_admin, UserRole.admin, UserRole.project_manager)


def visible_projects(user, db):
    stmt = select(ExecutionProject).order_by(ExecutionProject.created_at.desc())
    if user.role == UserRole.project_manager: stmt = stmt.where(ExecutionProject.project_manager_id == user.id)
    if user.role == UserRole.supervisor: stmt = stmt.where(ExecutionProject.supervisor_id == user.id)
    return db.scalars(stmt).all()


def project_access(project_id, user, db):
    project = db.get(ExecutionProject, project_id)
    if not project: raise HTTPException(404, "Execution project not found.")
    if user.role == UserRole.project_manager and project.project_manager_id != user.id: raise HTTPException(403, "Project is not assigned to you.")
    if user.role == UserRole.supervisor and project.supervisor_id != user.id: raise HTTPException(403, "Project is not assigned to you.")
    return project



def validated_task_data(payload: ExecutionTaskIn, db: Session) -> dict:
    data = payload.model_dump()
    main_vendor = db.get(Vendor, payload.assigned_contractor_id) if payload.assigned_contractor_id else None
    sub_vendor = db.get(Vendor, payload.assigned_subcontractor_id) if payload.assigned_subcontractor_id else None
    if payload.assigned_contractor_id:
        if not main_vendor:
            raise HTTPException(404, "Assigned main vendor not found.")
        if main_vendor.engagement_type != "main" or main_vendor.migration_status != "ready":
            raise HTTPException(422, "Select an active main vendor with no pending parent migration.")
        if main_vendor.status != "active":
            raise HTTPException(409, "Inactive or on-hold vendors cannot receive new task assignments.")
    if sub_vendor:
        if not main_vendor:
            raise HTTPException(422, "Main vendor is required for a sub-vendor assignment.")
        if sub_vendor.engagement_type != "sub_vendor" or sub_vendor.migration_status != "ready":
            raise HTTPException(422, "Resolve the sub-vendor parent mapping before task assignment.")
        if sub_vendor.parent_vendor_id != main_vendor.id:
            raise HTTPException(422, "The selected sub-vendor does not belong to the selected main vendor.")
        if sub_vendor.status != "active":
            raise HTTPException(409, "Inactive or on-hold sub-vendors cannot receive new task assignments.")
    category = db.get(VendorCategory, payload.category_id) if payload.category_id else None
    subcategory = db.get(VendorCategory, payload.subcategory_id) if payload.subcategory_id else None
    if payload.category_id and (not category or not category.active or category.parent_id is not None):
        raise HTTPException(422, "Select a valid active main category.")
    if payload.subcategory_id:
        if not subcategory or not subcategory.active or subcategory.parent_id is None:
            raise HTTPException(422, "Select a valid active subcategory.")
        if category and subcategory.parent_id != category.id:
            raise HTTPException(422, "The selected subcategory does not belong to the selected main category.")
        if not category:
            category = db.get(VendorCategory, subcategory.parent_id)
            data["category_id"] = category.id
    if subcategory:
        data["category"] = subcategory.name
    elif category:
        data["category"] = category.name

    required_category_id = subcategory.id if subcategory else category.id if category else None
    if required_category_id and main_vendor:
        main_matches_directly = db.scalar(
            select(ContractorCategory.id).where(
                ContractorCategory.vendor_id == main_vendor.id,
                ContractorCategory.category_id == required_category_id,
            )
        )
        matching_child = db.scalar(
            select(Vendor.id)
            .join(ContractorCategory, ContractorCategory.vendor_id == Vendor.id)
            .where(
                Vendor.parent_vendor_id == main_vendor.id,
                Vendor.engagement_type == "sub_vendor",
                Vendor.migration_status == "ready",
                Vendor.status == "active",
                ContractorCategory.category_id == required_category_id,
            )
            .limit(1)
        )
        if not main_matches_directly and not matching_child:
            raise HTTPException(422, "Neither this main vendor nor its active sub-vendors match the task category.")
        if not main_matches_directly and not sub_vendor:
            raise HTTPException(422, "Select the matching sub-vendor responsible for this category.")
    if required_category_id and sub_vendor:
        sub_matches = db.scalar(
            select(ContractorCategory.id).where(
                ContractorCategory.vendor_id == sub_vendor.id,
                ContractorCategory.category_id == required_category_id,
            )
        )
        if not sub_matches:
            raise HTTPException(422, "The selected sub-vendor does not match this task category.")
    return data
def _group_by_task(items):
    grouped = {}
    for item in items:
        grouped.setdefault(item.task_id, []).append(item)
    return grouped



def build_task_context(tasks, days, users, vendors, db):
    task_ids = [task.id for task in tasks]
    history = db.scalars(
        select(ExecutionTaskReschedule)
        .where(ExecutionTaskReschedule.task_id.in_(task_ids))
        .order_by(ExecutionTaskReschedule.created_at.desc())
    ).all() if task_ids else []
    delay_reports = db.scalars(
        select(ExecutionTaskDelayReport)
        .where(ExecutionTaskDelayReport.task_id.in_(task_ids))
        .order_by(ExecutionTaskDelayReport.created_at.desc())
    ).all() if task_ids else []

    status_history = db.scalars(
        select(ExecutionTaskStatusHistory)
        .where(ExecutionTaskStatusHistory.task_id.in_(task_ids))
        .order_by(ExecutionTaskStatusHistory.created_at.desc())
    ).all() if task_ids else []
    user_by_id = {item.id: item for item in users}
    related_user_ids = {
        user_id
        for task in tasks
        for user_id in (task.assigned_supervisor_id, task.rescheduled_by)
        if user_id
    }
    related_user_ids.update(item.created_by for item in history)
    related_user_ids.update(item.created_by for item in delay_reports)
    related_user_ids.update(item.changed_by for item in status_history if item.changed_by)
    missing_user_ids = related_user_ids - set(user_by_id)
    if missing_user_ids:
        related_users = db.scalars(select(User).where(User.id.in_(missing_user_ids))).all()
        user_by_id.update({item.id: item for item in related_users})

    vendor_by_id = {item.id: item for item in vendors}
    related_vendor_ids = {
        vendor_id
        for task in tasks
        for vendor_id in (task.assigned_contractor_id, task.assigned_subcontractor_id)
        if vendor_id
    }
    missing_vendor_ids = related_vendor_ids - set(vendor_by_id)
    if missing_vendor_ids:
        related_vendors = db.scalars(select(Vendor).where(Vendor.id.in_(missing_vendor_ids))).all()
        vendor_by_id.update({item.id: item for item in related_vendors})

    return {
        "days": {item.id: item for item in days},
        "users": user_by_id,
        "vendors": vendor_by_id,
        "history": _group_by_task(history),
        "delay_reports": _group_by_task(delay_reports),
        "status_history": _group_by_task(status_history),
    }


def task_json(task, db, context=None):
    day = context["days"].get(task.day_id) if context else db.get(ExecutionDay, task.day_id)
    supervisor = context["users"].get(task.assigned_supervisor_id) if context else db.get(User, task.assigned_supervisor_id)
    contractor = (context["vendors"].get(task.assigned_contractor_id) if context else db.get(Vendor, task.assigned_contractor_id)) if task.assigned_contractor_id else None
    sub = (context["vendors"].get(task.assigned_subcontractor_id) if context else db.get(Vendor, task.assigned_subcontractor_id)) if task.assigned_subcontractor_id else None
    history = context["history"].get(task.id, []) if context else db.scalars(
        select(ExecutionTaskReschedule).where(ExecutionTaskReschedule.task_id == task.id).order_by(ExecutionTaskReschedule.created_at.desc())
    ).all()
    delay_reports = context["delay_reports"].get(task.id, []) if context else db.scalars(
        select(ExecutionTaskDelayReport).where(ExecutionTaskDelayReport.task_id == task.id).order_by(ExecutionTaskDelayReport.created_at.desc())
    ).all()
    status_history = context["status_history"].get(task.id, []) if context else db.scalars(
        select(ExecutionTaskStatusHistory).where(ExecutionTaskStatusHistory.task_id == task.id).order_by(ExecutionTaskStatusHistory.created_at.desc())
    ).all()
    active_delay_report = next((item for item in delay_reports if item.status == "pending"), None)
    original_date = day.scheduled_date
    effective_date = task.rescheduled_date or original_date
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    is_overdue = effective_date < today and task.status not in {"submitted", "approved", "completed"}
    overdue_days = (today - effective_date).days if is_overdue else 0
    rescheduled_by = (context["users"].get(task.rescheduled_by) if context else db.get(User, task.rescheduled_by)) if task.rescheduled_by else None

    def user_name(user_id, fallback):
        item = context["users"].get(user_id) if context else db.get(User, user_id)
        return item.name if item else fallback
    return {
        "id": str(task.id),
        "project_id": str(task.project_id),
        "day_id": str(task.day_id),
        "day_no": day.day_no,
        "title": task.title,
        "category": task.category,
        "category_id": str(task.category_id) if task.category_id else None,
        "subcategory_id": str(task.subcategory_id) if task.subcategory_id else None,
        "instructions": task.instructions,
        "materials_required": task.materials_required,
        "material_reminder": task.material_reminder,
        "reminder_lead_days": task.reminder_lead_days,
        "template_task_id": str(task.template_task_id) if task.template_task_id else None,
        "assigned_supervisor_id": str(task.assigned_supervisor_id),
        "supervisor_name": supervisor.name if supervisor else "Unassigned",
        "assigned_contractor_id": str(task.assigned_contractor_id) if task.assigned_contractor_id else None,
        "contractor_name": contractor.name if contractor else None,
        "assigned_subcontractor_id": str(task.assigned_subcontractor_id) if task.assigned_subcontractor_id else None,
        "subcontractor_name": sub.name if sub else None,
        "priority": task.priority,
        "status": task.status,
        "proof_url": task.proof_url,
        "proof_required": task.proof_required,
        "remarks": task.remarks,
        "submitted_at": task.submitted_at.isoformat() if task.submitted_at else None,
        "reviewed_at": task.reviewed_at.isoformat() if task.reviewed_at else None,
        "rejection_reason": task.rejection_reason,
        "scheduled_date": original_date.isoformat(),
        "effective_date": effective_date.isoformat(),
        "rescheduled_date": task.rescheduled_date.isoformat() if task.rescheduled_date else None,
        "delay_reason": task.delay_reason,
        "rescheduled_at": task.rescheduled_at.isoformat() if task.rescheduled_at else None,
        "rescheduled_by_name": rescheduled_by.name if rescheduled_by else None,
        "reschedule_count": task.reschedule_count,
        "is_overdue": is_overdue,
        "overdue_days": overdue_days,
        "active_delay_report": {
            "id": str(active_delay_report.id),
            "category": active_delay_report.category,
            "reason": active_delay_report.reason,
            "proposed_date": active_delay_report.proposed_date.isoformat(),
            "status": active_delay_report.status,
            "created_by_name": user_name(active_delay_report.created_by, "Site supervisor"),
            "created_at": active_delay_report.created_at.isoformat(),
        } if active_delay_report else None,
        "delay_reports": [{
            "id": str(item.id),
            "category": item.category,
            "reason": item.reason,
            "proposed_date": item.proposed_date.isoformat(),
            "status": item.status,
            "created_by_name": user_name(item.created_by, "Site supervisor"),
            "created_at": item.created_at.isoformat(),
            "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
        } for item in delay_reports],
        "reschedule_history": [{
            "id": str(item.id),
            "previous_date": item.previous_date.isoformat(),
            "new_date": item.new_date.isoformat(),
            "reason": item.reason,
            "created_by_name": user_name(item.created_by, "SiteOps manager"),
            "created_at": item.created_at.isoformat(),
        } for item in history],
        "status_history": [{
            "id": str(item.id),
            "from_status": item.from_status,
            "to_status": item.to_status,
            "reason": item.reason,
            "changed_by": str(item.changed_by) if item.changed_by else None,
            "changed_by_name": user_name(item.changed_by, "System") if item.changed_by else "System",
            "created_at": item.created_at.isoformat(),
        } for item in status_history],
    }


def sync_project_contractor_mapping(task, actor_id, db):
    """Ensure task assignment maps the responsible main vendor to the project once."""
    vendor_ids = {task.assigned_contractor_id, task.assigned_subcontractor_id} - {None}
    mapped_ids = set()
    for vendor_id in vendor_ids:
        vendor = db.get(Vendor, vendor_id)
        if not vendor:
            continue
        if vendor.engagement_type == "main":
            mapped_ids.add(vendor.id)
        elif vendor.engagement_type == "sub_vendor" and vendor.parent_vendor_id:
            mapped_ids.add(vendor.parent_vendor_id)

    if not mapped_ids:
        return

    existing_ids = set(db.scalars(
        select(ExecutionProjectContractor.contractor_id).where(
            ExecutionProjectContractor.project_id == task.project_id,
            ExecutionProjectContractor.contractor_id.in_(mapped_ids),
        )
    ).all())
    pending_ids = {
        item.contractor_id
        for item in db.new
        if isinstance(item, ExecutionProjectContractor) and item.project_id == task.project_id
    }
    for mapped_id in mapped_ids - existing_ids - pending_ids:
        db.add(ExecutionProjectContractor(
            project_id=task.project_id,
            contractor_id=mapped_id,
            scope="Task assignment",
            created_by=actor_id,
        ))

@router.get("")
def workspace(user: User = Depends(current_user), db: Session = Depends(get_db)):
    projects = visible_projects(user, db)
    project_ids = {project.id for project in projects}
    days = db.scalars(
        select(ExecutionDay)
        .where(ExecutionDay.project_id.in_(project_ids))
        .order_by(ExecutionDay.day_no)
    ).all() if project_ids else []
    tasks = db.scalars(
        select(ExecutionTask)
        .where(ExecutionTask.project_id.in_(project_ids))
        .order_by(ExecutionTask.created_at)
    ).all() if project_ids else []
    users = db.scalars(
        select(User)
        .where(User.active.is_(True), User.role.in_([UserRole.project_manager, UserRole.supervisor]))
        .order_by(User.name)
    ).all()
    active_vendors = db.scalars(select(Vendor).where(Vendor.status == "active").order_by(Vendor.name)).all()
    main_status_by_id = {item.id: item.status for item in db.scalars(select(Vendor).where(Vendor.engagement_type == "main")).all()}
    vendors = [
        item for item in active_vendors
        if item.engagement_type == "main"
        or (item.parent_vendor_id and main_status_by_id.get(item.parent_vendor_id) == "active")
    ]
    relations = db.scalars(select(ContractorRelationship)).all()
    templates = db.scalars(
        select(ExecutionTemplate).where(ExecutionTemplate.active.is_(True)).order_by(ExecutionTemplate.name)
    ).all()
    template_tasks = db.scalars(
        select(ExecutionTemplateTask).order_by(ExecutionTemplateTask.day_no, ExecutionTemplateTask.sort_order)
    ).all()
    categories = db.scalars(
        select(VendorCategory)
        .where(VendorCategory.active.is_(True))
        .order_by(VendorCategory.category_type, VendorCategory.parent_id.nullsfirst(), VendorCategory.name)
    ).all()
    vendor_category_ids = {}
    eligible_vendor_ids = {item.id for item in vendors}
    category_links = db.scalars(
        select(ContractorCategory).where(ContractorCategory.vendor_id.in_(eligible_vendor_ids))
    ).all() if eligible_vendor_ids else []
    for link in category_links:
        vendor_category_ids.setdefault(link.vendor_id, []).append(str(link.category_id))
    context = build_task_context(tasks, days, users, vendors, db)
    template_by_id = {template.id: template for template in templates}
    template_tasks_by_id = {}
    for template_task in template_tasks:
        template_tasks_by_id.setdefault(template_task.template_id, []).append(template_task)

    return {
        "projects": [{
            "id": str(project.id),
            "name": project.name,
            "client_name": project.client_name,
            "location": project.location,
            "project_type": project.project_type,
            "area": project.area,
            "start_date": project.start_date.isoformat(),
            "duration_days": project.duration_days,
            "project_manager_id": str(project.project_manager_id),
            "supervisor_id": str(project.supervisor_id),
            "status": project.status,
            "template_id": str(project.template_id) if project.template_id else None,
            "template_name": template_by_id[project.template_id].name if project.template_id in template_by_id else None,
        } for project in projects],
        "days": [{
            "id": str(day.id),
            "project_id": str(day.project_id),
            "day_no": day.day_no,
            "scheduled_date": day.scheduled_date.isoformat(),
        } for day in days],
        "tasks": [task_json(task, db, context) for task in tasks],
        "users": [{"id": str(item.id), "name": item.name, "role": item.role.value, "phone": item.phone} for item in users],
        "contractors": [{
            "id": str(item.id),
            "name": item.name,
            "status": item.status,
            "engagement_type": item.engagement_type,
            "parent_vendor_id": str(item.parent_vendor_id) if item.parent_vendor_id else None,
            "migration_status": item.migration_status,
            "category_ids": vendor_category_ids.get(item.id, []),
        } for item in vendors],
        "categories": [{
            "id": str(item.id),
            "name": item.name,
            "category_type": item.category_type,
            "parent_id": str(item.parent_id) if item.parent_id else None,
            "description": item.description,
            "active": item.active,
        } for item in categories],
        "relationships": [{
            "main_contractor_id": str(item.main_contractor_id),
            "subcontractor_id": str(item.subcontractor_id),
        } for item in relations],
        "templates": [{
            "id": str(template.id),
            "name": template.name,
            "project_type": template.project_type,
            "duration_days": template.duration_days,
            "tasks": [{
                "day_no": item.day_no,
                "title": item.title,
                "category": item.category,
                "category_id": str(item.category_id) if item.category_id else None,
                "subcategory_id": str(item.subcategory_id) if item.subcategory_id else None,
                "priority": item.priority,
                "instructions": item.instructions,
                "materials_required": item.materials_required,
                "material_reminder": item.material_reminder,
                "reminder_lead_days": item.reminder_lead_days,
            } for item in template_tasks_by_id.get(template.id, [])],
        } for template in templates],
    }

@router.post("/templates")
def create_template(payload: ExecutionTemplateIn, actor: User=Depends(require_roles(UserRole.super_admin)), db: Session=Depends(get_db)):
    if payload.duration_days < 1 or payload.duration_days > 45: raise HTTPException(422,"Duration must be between 1 and 45 days.")
    if any(t.day_no<1 or t.day_no>payload.duration_days for t in payload.tasks): raise HTTPException(422,"Template task day is outside the duration.")
    item=ExecutionTemplate(name=payload.name,project_type=payload.project_type,duration_days=payload.duration_days,created_by=actor.id); db.add(item); db.flush()
    for i, t in enumerate(payload.tasks):
        task_data = t.model_dump()
        category = db.get(VendorCategory, t.category_id) if t.category_id else None
        subcategory = db.get(VendorCategory, t.subcategory_id) if t.subcategory_id else None
        if t.category_id and (not category or not category.active or category.parent_id is not None):
            raise HTTPException(422, "Select a valid active main category for every classified template task.")
        if t.subcategory_id:
            if not subcategory or not subcategory.active or subcategory.parent_id is None:
                raise HTTPException(422, "Select a valid active subcategory for every classified template task.")
            if category and subcategory.parent_id != category.id:
                raise HTTPException(422, "Template task subcategory does not belong to its main category.")
            if not category:
                category = db.get(VendorCategory, subcategory.parent_id)
                task_data["category_id"] = category.id
        if subcategory:
            task_data["category"] = subcategory.name
        elif category:
            task_data["category"] = category.name
        db.add(ExecutionTemplateTask(template_id=item.id, sort_order=i + 1, **task_data))
    db.commit(); return {"id":str(item.id)}


@router.post("/projects")
def create_project(payload: ExecutionProjectIn, actor: User=Depends(require_roles(*MANAGERS)), db: Session=Depends(get_db)):
    duration=payload.duration_days
    template=db.get(ExecutionTemplate,payload.template_id) if payload.template_id else None
    if not template: raise HTTPException(422,"Select an execution template. Blank projects are not available in the standard workflow.")
    duration=template.duration_days
    if duration<1 or duration>45: raise HTTPException(422,"Duration must be between 1 and 45 days.")
    pm_id=actor.id if actor.role==UserRole.project_manager else payload.project_manager_id
    if not pm_id: raise HTTPException(422,"Project Manager is required.")
    project=ExecutionProject(**payload.model_dump(exclude={"duration_days","project_manager_id"}),duration_days=duration,project_manager_id=pm_id,created_by=actor.id); db.add(project); db.flush(); day_by_no={}
    for n in range(1,duration+1):
        day=ExecutionDay(project_id=project.id,day_no=n,scheduled_date=payload.start_date+timedelta(days=n-1)); db.add(day); db.flush(); day_by_no[n]=day
    if template:
        for tt in db.scalars(select(ExecutionTemplateTask).where(ExecutionTemplateTask.template_id==template.id)).all():
            task=ExecutionTask(project_id=project.id,day_id=day_by_no[tt.day_no].id,title=tt.title,category=tt.category,category_id=tt.category_id,subcategory_id=tt.subcategory_id,instructions=tt.instructions,materials_required=tt.materials_required,material_reminder=tt.material_reminder,reminder_lead_days=tt.reminder_lead_days,template_task_id=tt.id,assigned_supervisor_id=payload.supervisor_id,priority=tt.priority,status="assigned",created_by=actor.id); db.add(task); db.flush(); record_new_task(db, task, actor.id, "Created from project template")
    db.commit(); return {"id":str(project.id)}


@router.post("/tasks")
def create_task(payload: ExecutionTaskIn, actor: User=Depends(require_roles(*MANAGERS)), db: Session=Depends(get_db)):
    project_access(payload.project_id,actor,db); day=db.get(ExecutionDay,payload.day_id)
    if not day or day.project_id!=payload.project_id: raise HTTPException(422,"Selected day does not belong to project.")
    task_data = validated_task_data(payload, db)
    task=ExecutionTask(**task_data,status="assigned",created_by=actor.id); db.add(task); db.flush(); record_new_task(db, task, actor.id); sync_project_contractor_mapping(task, actor.id, db); db.commit(); return task_json(task,db)


@router.put("/tasks/{task_id}")
def update_task(task_id:uuid.UUID,payload:ExecutionTaskIn,actor:User=Depends(require_roles(*MANAGERS)),db:Session=Depends(get_db)):
    task=db.get(ExecutionTask,task_id)
    if not task: raise HTTPException(404,"Task not found.")
    project_access(task.project_id,actor,db)
    task_data = validated_task_data(payload, db)
    for k,v in task_data.items(): setattr(task,k,v)
    sync_project_contractor_mapping(task, actor.id, db)
    db.commit(); return task_json(task,db)


@router.delete("/tasks/{task_id}")
def delete_task(task_id:uuid.UUID,actor:User=Depends(require_roles(*MANAGERS)),db:Session=Depends(get_db)):
    task=db.get(ExecutionTask,task_id)
    if not task: raise HTTPException(404,"Task not found.")
    project_access(task.project_id,actor,db); db.delete(task); db.commit(); return {"message":"Task deleted."}


@router.post("/project-contractors")
def map_contractor(payload:ExecutionProjectContractorIn,actor:User=Depends(require_roles(*MANAGERS)),db:Session=Depends(get_db)):
    project_access(payload.project_id,actor,db); vendor=db.get(Vendor,payload.contractor_id)
    if not vendor or vendor.engagement_type != "main" or vendor.migration_status != "ready": raise HTTPException(422,"Select a main vendor with no pending migration.")
    if vendor.status != "active": raise HTTPException(409,"Only active vendors can be assigned to projects.")
    item=ExecutionProjectContractor(**payload.model_dump(),created_by=actor.id); db.add(item); db.commit(); return {"id":str(item.id)}




@router.put("/projects/{project_id}")
def update_project(project_id: uuid.UUID, payload: ExecutionProjectUpdateIn, actor: User = Depends(require_roles(*MANAGERS)), db: Session = Depends(get_db)):
    project = project_access(project_id, actor, db)
    if payload.status not in {"active", "on_hold", "completed", "cancelled"}:
        raise HTTPException(422, "Invalid project status.")
    for key, value in payload.model_dump().items():
        setattr(project, key, value)
    db.commit()
    return {"id": str(project.id), "message": "Project updated."}


@router.delete("/projects/{project_id}")
def delete_project(project_id: uuid.UUID, actor: User = Depends(require_roles(*MANAGERS)), db: Session = Depends(get_db)):
    project = project_access(project_id, actor, db)
    db.delete(project)
    db.commit()
    return {"message": "Project and its execution schedule were deleted."}


@router.post("/tasks/{task_id}/delay-report")
def report_task_delay(task_id: uuid.UUID, payload: ExecutionTaskDelayReportIn, actor: User = Depends(require_roles(UserRole.supervisor)), db: Session = Depends(get_db)):
    task = db.get(ExecutionTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found. Refresh the Execution page and try again.")
    project_access(task.project_id, actor, db)
    if task.assigned_supervisor_id != actor.id:
        raise HTTPException(403, "This task is not assigned to you.")
    if task.status in {"submitted", "approved", "completed"}:
        raise HTTPException(409, "Submitted or approved work cannot be marked delayed.")
    categories = {"material", "labour", "dependency", "client", "weather", "site_condition", "other"}
    if payload.category not in categories:
        raise HTTPException(422, "Select a valid delay category.")
    reason = (payload.reason or "").strip()
    if len(reason) < 5:
        raise HTTPException(422, "A clear delay reason of at least 5 characters is required.")
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    if payload.proposed_date < today:
        raise HTTPException(422, "Proposed revised date must be today or a future date.")
    existing = db.scalar(select(ExecutionTaskDelayReport).where(
        ExecutionTaskDelayReport.task_id == task.id,
        ExecutionTaskDelayReport.status == "pending",
    ))
    if existing:
        raise HTTPException(409, "A delay report is already waiting for PM confirmation.")
    db.add(ExecutionTaskDelayReport(
        task_id=task.id,
        category=payload.category,
        reason=reason,
        proposed_date=payload.proposed_date,
        created_by=actor.id,
    ))
    set_task_status(db, task, "delayed", actor.id, reason)
    db.flush()
    db.commit()
    return task_json(task, db)

@router.post("/tasks/{task_id}/reschedule")
def reschedule_task(task_id: uuid.UUID, payload: ExecutionTaskRescheduleIn, actor: User = Depends(require_roles(*MANAGERS)), db: Session = Depends(get_db)):
    task = db.get(ExecutionTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found.")
    project_access(task.project_id, actor, db)
    if task.status in {"submitted", "approved", "completed"}:
        raise HTTPException(409, "Submitted or approved work cannot be rescheduled.")
    reason = (payload.reason or "").strip()
    if len(reason) < 5:
        raise HTTPException(422, "A clear delay reason of at least 5 characters is required.")
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    if payload.scheduled_date < today:
        raise HTTPException(422, "Revised date must be today or a future date.")
    day = db.get(ExecutionDay, task.day_id)
    previous_date = task.rescheduled_date or day.scheduled_date
    if payload.scheduled_date == previous_date:
        raise HTTPException(409, "Choose a different revised date.")
    db.add(ExecutionTaskReschedule(
        task_id=task.id,
        previous_date=previous_date,
        new_date=payload.scheduled_date,
        reason=reason,
        created_by=actor.id,
    ))
    task.rescheduled_date = payload.scheduled_date
    task.delay_reason = reason
    task.rescheduled_at = datetime.now(timezone.utc)
    task.rescheduled_by = actor.id
    task.reschedule_count = (task.reschedule_count or 0) + 1
    if task.status != "rejected":
        set_task_status(db, task, "delayed", actor.id, reason)
    pending_reports = db.scalars(select(ExecutionTaskDelayReport).where(
        ExecutionTaskDelayReport.task_id == task.id,
        ExecutionTaskDelayReport.status == "pending",
    )).all()
    for report in pending_reports:
        report.status = "accepted"
        report.reviewed_by = actor.id
        report.reviewed_at = datetime.now(timezone.utc)
    db.flush()
    db.commit()
    return task_json(task, db)

@router.patch("/tasks/{task_id}/status")
def update_task_status(task_id: uuid.UUID, payload: ExecutionTaskStatusIn, actor: User = Depends(require_roles(UserRole.supervisor)), db: Session = Depends(get_db)):
    task = db.get(ExecutionTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found.")
    project_access(task.project_id, actor, db)
    if task.assigned_supervisor_id != actor.id:
        raise HTTPException(403, "This task is not assigned to you.")
    if payload.status != "in_progress":
        raise HTTPException(422, "Use the delay report form when work is delayed.")
    if task.status in {"submitted", "approved"}:
        raise HTTPException(409, "Submitted or approved work cannot be changed by the supervisor.")
    set_task_status(db, task, payload.status, actor.id, "Supervisor started or restarted work")
    pending_reports = db.scalars(select(ExecutionTaskDelayReport).where(
        ExecutionTaskDelayReport.task_id == task.id,
        ExecutionTaskDelayReport.status == "pending",
    )).all()
    for report in pending_reports:
        report.status = "withdrawn"
        report.reviewed_by = actor.id
        report.reviewed_at = datetime.now(timezone.utc)
    db.flush()
    db.commit()
    return task_json(task, db)


@router.post("/tasks/{task_id}/submit")
async def submit_task(task_id: uuid.UUID, remarks: str = Form(...), proof: UploadFile | None = File(None), actor: User = Depends(require_roles(UserRole.supervisor)), db: Session = Depends(get_db)):
    task = db.get(ExecutionTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found.")
    project_access(task.project_id, actor, db)
    if task.assigned_supervisor_id != actor.id:
        raise HTTPException(403, "This task is not assigned to you.")
    if task.status == "approved":
        raise HTTPException(409, "Approved work cannot be resubmitted.")
    if task.proof_required and not proof and not task.proof_url:
        raise HTTPException(422, "Proof is required for this task.")
    if proof:
        allowed = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf"}
        if proof.content_type not in allowed:
            raise HTTPException(422, "Proof must be JPG, PNG, WebP, or PDF.")
        content = await proof.read()
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(422, "Proof must be 10 MB or smaller.")
        filename = f"{task.id}-{uuid.uuid4().hex}{allowed[proof.content_type]}"
        upload_path = Path(settings.upload_dir)
        upload_path.mkdir(parents=True, exist_ok=True)
        (upload_path / filename).write_bytes(content)
        task.proof_url = f"/uploads/task-proofs/{filename}"
    task.remarks = remarks.strip()
    set_task_status(db, task, "submitted", actor.id, "Supervisor submitted work for PM review")
    task.submitted_at = datetime.now(timezone.utc)
    task.rejection_reason = None
    task.reviewed_at = None
    task.reviewed_by = None
    db.commit()
    return task_json(task, db)


@router.post("/tasks/{task_id}/review")
def review_task(task_id: uuid.UUID, payload: ExecutionTaskReviewIn, actor: User = Depends(require_roles(*MANAGERS)), db: Session = Depends(get_db)):
    task = db.get(ExecutionTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found.")
    project_access(task.project_id, actor, db)
    if task.status != "submitted":
        raise HTTPException(409, "Only submitted work can be reviewed.")
    if payload.action not in {"approve", "reject"}:
        raise HTTPException(422, "Review action must be approve or reject.")
    if payload.action == "reject" and not (payload.rejection_reason or "").strip():
        raise HTTPException(422, "Rejection reason is required.")
    set_task_status(db, task, "approved" if payload.action == "approve" else "rejected", actor.id, "PM approved work" if payload.action == "approve" else payload.rejection_reason.strip())
    task.rejection_reason = None if payload.action == "approve" else payload.rejection_reason.strip()
    task.reviewed_at = datetime.now(timezone.utc)
    task.reviewed_by = actor.id
    db.commit()
    return task_json(task, db)




