"""U2: task lifecycle status transitions for the execution-layer `tasks` table.

This is the real implementation of the write path the read-only
`GET /{project_id}/execution-tasks` placeholder in `projects_v2.py`
anticipates. Later units (U3-U6) extend this router with progress/evidence,
verification/approval, blocker/delay, and support-assignment routes.
"""

import io
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.database import get_db
from app.execution_models import (
    FileObject,
    Task,
    TaskApprovalDecision,
    TaskBlocker,
    TaskDelayEvent,
    TaskDependency,
    TaskEvidence,
    TaskProgressUpdate,
    TaskSupportAssignment,
    TaskVerification,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent
from app.routes.projects_v2 import get_project
from app.schemas.execution_tasks import (
    TaskApprovalIn,
    TaskApprovalOut,
    TaskApprovalSummaryOut,
    TaskAuditEventOut,
    TaskBlockerCreateIn,
    TaskBlockerOut,
    TaskDelayCreateIn,
    TaskDelayOut,
    TaskDependencyRefOut,
    TaskDetailOut,
    TaskEvidenceOut,
    TaskListItemOut,
    TaskOut,
    TaskProgressUpdateOut,
    TaskStatusTransitionIn,
    TaskSupportAssignmentCreateIn,
    TaskSupportAssignmentEndIn,
    TaskSupportAssignmentOut,
    TaskVerificationIn,
    TaskVerificationOut,
    TaskVerificationSummaryOut,
)
from app.services.task_approval import TaskApprovalService
from app.services.task_approval_metadata import build_approval_metadata
from app.services.task_blocker import TaskBlockerService
from app.services.task_delay import TaskDelayService
from app.services.task_lifecycle import TaskLifecycleService
from app.services.task_progress import TaskProgressService
from app.services.task_support_assignment import TaskSupportAssignmentService
from app.services.task_verification import TaskVerificationService

router = APIRouter(prefix="/api/v2/projects", tags=["v2-execution-tasks"])


@router.get("/{project_id}/tasks", response_model=list[TaskListItemOut])
def list_project_tasks(
    project_id: uuid.UUID,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Read-side listing for TaskExecutionBoard - the execution-layer
    counterpart to the planning-time `GET /{project_id}/execution-tasks`
    placeholder. Returns `tasks` rows (not `V2ProjectTask`), with each
    row's live lifecycle_status plus small summary counts a board list
    needs without fetching every task's full detail.

    An Internal Employee only sees tasks they're actively support-assigned
    to on this project - "delegated task support" (their own role
    description) means exactly the tasks delegated to them, not every task
    in a project they happen to be a member of. Every other role (Admin,
    PM, Supervisor) keeps the full unfiltered project view they already had."""
    project = get_project(db, project_id, actor)
    tasks_query = select(Task).where(Task.project_id == project.id).order_by(Task.template_sequence.asc())
    if actor.role == UserRole.internal_employee:
        actor_employee_id = db.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == actor.id))
        assigned_task_ids = select(TaskSupportAssignment.task_id).where(
            TaskSupportAssignment.project_id == project.id,
            TaskSupportAssignment.employee_id == actor_employee_id,
            TaskSupportAssignment.status == "active",
            TaskSupportAssignment.ends_at.is_(None),
        )
        tasks_query = tasks_query.where(Task.id.in_(assigned_task_ids))
    tasks = list(db.scalars(tasks_query).all())

    open_blocker_counts: dict[uuid.UUID, int] = {}
    for task_id, count in db.execute(
        select(TaskBlocker.task_id, func.count(TaskBlocker.id))
        .where(TaskBlocker.project_id == project.id, TaskBlocker.resolved_at.is_(None))
        .group_by(TaskBlocker.task_id)
    ).all():
        open_blocker_counts[task_id] = count

    active_support_counts: dict[uuid.UUID, int] = {}
    for task_id, count in db.execute(
        select(TaskSupportAssignment.task_id, func.count(TaskSupportAssignment.id))
        .where(TaskSupportAssignment.project_id == project.id, TaskSupportAssignment.status == "active")
        .group_by(TaskSupportAssignment.task_id)
    ).all():
        active_support_counts[task_id] = count

    return [
        TaskListItemOut(
            id=task.id,
            project_id=task.project_id,
            baseline_id=task.baseline_id,
            original_code=task.original_code,
            template_sequence=task.template_sequence,
            title=task.title,
            task_kind=task.task_kind,
            task_class=task.task_class,
            lifecycle_status=task.lifecycle_status,
            schedule_classification=task.schedule_classification,
            planned_start_day=task.planned_start_day,
            planned_end_day=task.planned_end_day,
            phase=task.phase,
            category=task.category,
            evidence_required=task.evidence_required,
            open_blocker_count=open_blocker_counts.get(task.id, 0),
            active_support_count=active_support_counts.get(task.id, 0),
            approval=build_approval_metadata(task.task_kind, task.task_class, task.lifecycle_status),
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        for task in tasks
    ]


@router.get("/{project_id}/tasks/{task_id}", response_model=TaskDetailOut)
def get_project_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Read-side detail for one execution-layer task - everything the
    board's task-detail panel (progress form, decision modal, blocker/delay
    panel, support-assignment panel) needs to render and to decide which
    actions are currently valid, in one call."""
    project = get_project(db, project_id, actor)
    task = db.scalar(select(Task).where(Task.id == task_id, Task.project_id == project.id))
    if not task:
        raise HTTPException(404, "Task not found.")

    predecessor_rows = db.execute(
        select(TaskDependency, Task)
        .join(Task, Task.id == TaskDependency.predecessor_task_id)
        .where(TaskDependency.successor_task_id == task.id)
    ).all()
    predecessors = [
        TaskDependencyRefOut(
            id=predecessor.id,
            original_code=predecessor.original_code,
            title=predecessor.title,
            lifecycle_status=predecessor.lifecycle_status,
            task_kind=predecessor.task_kind,
            task_class=predecessor.task_class,
            dependency_type=dependency.dependency_type,
            blocking=dependency.blocking,
        )
        for dependency, predecessor in predecessor_rows
    ]

    progress_updates = list(db.scalars(
        select(TaskProgressUpdate)
        .where(TaskProgressUpdate.task_id == task.id)
        .order_by(TaskProgressUpdate.created_at.desc(), TaskProgressUpdate.id.desc())
    ).all())
    verifications = list(db.scalars(
        select(TaskVerification)
        .where(TaskVerification.task_id == task.id)
        .order_by(TaskVerification.verified_at.desc(), TaskVerification.id.desc())
    ).all())
    approvals = list(db.scalars(
        select(TaskApprovalDecision)
        .where(TaskApprovalDecision.task_id == task.id)
        .order_by(TaskApprovalDecision.decided_at.desc(), TaskApprovalDecision.id.desc())
    ).all())
    blockers = list(db.scalars(
        select(TaskBlocker)
        .where(TaskBlocker.task_id == task.id)
        .order_by(TaskBlocker.started_at.desc(), TaskBlocker.id.desc())
    ).all())
    delays = list(db.scalars(
        select(TaskDelayEvent)
        .where(TaskDelayEvent.task_id == task.id)
        .order_by(TaskDelayEvent.created_at.desc(), TaskDelayEvent.id.desc())
    ).all())
    support_assignments = list(db.scalars(
        select(TaskSupportAssignment)
        .where(TaskSupportAssignment.task_id == task.id)
        .order_by(TaskSupportAssignment.starts_at.desc(), TaskSupportAssignment.id.desc())
    ).all())
    audit_rows = list(db.scalars(
        select(V2AuditEvent)
        .where(V2AuditEvent.entity_type == "task", V2AuditEvent.entity_id == task.id)
        .order_by(V2AuditEvent.occurred_at.desc(), V2AuditEvent.id.desc())
    ).all())

    actor_employee_id = db.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == actor.id))
    actor_is_assigned_support = actor_employee_id is not None and any(
        s.employee_id == actor_employee_id and s.status == "active" and s.ends_at is None
        for s in support_assignments
    )
    # Mirrors list_project_tasks' own filter: an Internal Employee reaching
    # a task ID directly (not through their own filtered list) must not see
    # a task they're not actively assigned to - the list filter alone would
    # only be a UI convenience, not real access control, without this.
    if actor.role == UserRole.internal_employee and not actor_is_assigned_support:
        raise HTTPException(403, "You can only view tasks you are actively assigned to support.")

    actor_names = _resolve_actor_names(
        db,
        [v.verified_by for v in verifications]
        + [a.decided_by for a in approvals]
        + [event.actor_user_id for event in audit_rows if event.actor_user_id],
    )

    return TaskDetailOut(
        id=task.id,
        project_id=task.project_id,
        baseline_id=task.baseline_id,
        original_code=task.original_code,
        template_sequence=task.template_sequence,
        title=task.title,
        description=task.description,
        task_kind=task.task_kind,
        task_class=task.task_class,
        lifecycle_status=task.lifecycle_status,
        schedule_classification=task.schedule_classification,
        planned_start_day=task.planned_start_day,
        planned_end_day=task.planned_end_day,
        phase=task.phase,
        category=task.category,
        evidence_required=task.evidence_required,
        created_at=task.created_at,
        updated_at=task.updated_at,
        approval=build_approval_metadata(task.task_kind, task.task_class, task.lifecycle_status),
        actor_is_assigned_support=actor_is_assigned_support,
        predecessors=predecessors,
        progress_updates=[_progress_update_out(db, update) for update in progress_updates],
        verifications=[
            TaskVerificationSummaryOut(
                id=v.id, submission_update_id=v.submission_update_id, decision=v.decision, remarks=v.remarks,
                verified_by=v.verified_by, verified_by_name=actor_names.get(v.verified_by),
                verified_at=v.verified_at,
            )
            for v in verifications
        ],
        approvals=[
            TaskApprovalSummaryOut(
                id=a.id, verification_id=a.verification_id, decision=a.decision, remarks=a.remarks,
                decided_by=a.decided_by, decided_by_name=actor_names.get(a.decided_by),
                decided_at=a.decided_at,
            )
            for a in approvals
        ],
        blockers=[TaskBlockerOut.model_validate(b) for b in blockers],
        delays=[TaskDelayOut.model_validate(d) for d in delays],
        support_assignments=[TaskSupportAssignmentOut.model_validate(s) for s in support_assignments],
        audit_events=[
            TaskAuditEventOut(
                id=event.id,
                action=event.action,
                source=event.source,
                before_status=(event.before_json or {}).get("lifecycle_status"),
                after_status=(event.after_json or {}).get("lifecycle_status"),
                reason=event.reason,
                actor_user_id=event.actor_user_id,
                actor_name=actor_names.get(event.actor_user_id) if event.actor_user_id else None,
                occurred_at=event.occurred_at,
            )
            for event in audit_rows
        ],
    )


@router.post("/{project_id}/tasks/{task_id}/status", response_model=TaskOut)
def transition_task_status(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: TaskStatusTransitionIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return TaskLifecycleService(db).transition(
        project_id, task_id, payload.target_status, actor, reason=payload.reason,
    )


def _resolve_actor_names(db: Session, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Batch-resolves user ids to display names for the task detail view
    (audit trail actor, verifier, approver) - one query per request rather
    than N, and never a hard failure if a user id is stale/missing."""
    unique_ids = {uid for uid in user_ids if uid}
    if not unique_ids:
        return {}
    rows = db.execute(select(User.id, User.name).where(User.id.in_(unique_ids))).all()
    return {row[0]: row[1] for row in rows}


def _progress_update_out(db: Session, progress_update) -> TaskProgressUpdateOut:
    evidence_rows = db.scalars(
        select(TaskEvidence).where(TaskEvidence.task_progress_update_id == progress_update.id)
    ).all()
    evidence_out = []
    for evidence in evidence_rows:
        file_object = db.get(FileObject, evidence.file_id)
        if not file_object:
            continue
        evidence_out.append(TaskEvidenceOut(
            id=evidence.id,
            file_id=file_object.id,
            evidence_type=evidence.evidence_type,
            caption=evidence.caption,
            original_filename=file_object.original_filename,
            mime_type=file_object.mime_type,
            size_bytes=file_object.size_bytes,
        ))
    return TaskProgressUpdateOut(
        id=progress_update.id,
        task_id=progress_update.task_id,
        project_id=progress_update.project_id,
        update_type=progress_update.update_type,
        status_claim=progress_update.status_claim,
        note=progress_update.note,
        submitted_by=progress_update.submitted_by,
        source=progress_update.source,
        created_at=progress_update.created_at,
        evidence=evidence_out,
    )


@router.post("/{project_id}/tasks/{task_id}/progress", response_model=TaskProgressUpdateOut)
async def submit_task_progress(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    note: str | None = Form(default=None),
    status_claim: str | None = Form(default=None),
    evidence: UploadFile | None = File(default=None),
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    evidence_bytes = await evidence.read() if evidence is not None else None
    progress_update = TaskProgressService(db).submit_progress(
        project_id,
        task_id,
        actor,
        note=note,
        status_claim=status_claim,
        evidence_bytes=evidence_bytes,
        evidence_filename=evidence.filename if evidence is not None else None,
        evidence_content_type=evidence.content_type if evidence is not None else None,
    )
    return _progress_update_out(db, progress_update)


@router.post("/{project_id}/tasks/{task_id}/verify", response_model=TaskVerificationOut)
def verify_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: TaskVerificationIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    task = TaskVerificationService(db).verify(
        project_id, task_id, payload.decision, actor, remarks=payload.remarks,
    )
    verification = db.scalar(
        select(TaskVerification)
        .where(TaskVerification.task_id == task.id)
        .order_by(TaskVerification.verified_at.desc(), TaskVerification.id.desc())
        .limit(1)
    )
    return TaskVerificationOut(
        id=verification.id,
        task_id=verification.task_id,
        submission_update_id=verification.submission_update_id,
        decision=verification.decision,
        remarks=verification.remarks,
        verified_by=verification.verified_by,
        verified_at=verification.verified_at,
        task=TaskOut.model_validate(task),
    )


@router.post("/{project_id}/tasks/{task_id}/approve", response_model=TaskApprovalOut)
def approve_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: TaskApprovalIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    task = TaskApprovalService(db).approve(
        project_id, task_id, payload.decision, actor, remarks=payload.remarks,
    )
    approval = db.scalar(
        select(TaskApprovalDecision)
        .where(TaskApprovalDecision.task_id == task.id)
        .order_by(TaskApprovalDecision.decided_at.desc(), TaskApprovalDecision.id.desc())
        .limit(1)
    )
    return TaskApprovalOut(
        id=approval.id,
        task_id=approval.task_id,
        verification_id=approval.verification_id,
        decision=approval.decision,
        remarks=approval.remarks,
        decided_by=approval.decided_by,
        decided_at=approval.decided_at,
        task=TaskOut.model_validate(task),
    )


@router.post("/{project_id}/tasks/{task_id}/blockers", response_model=TaskBlockerOut)
def create_task_blocker(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: TaskBlockerCreateIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return TaskBlockerService(db).create_blocker(
        project_id, task_id, actor,
        type_=payload.type,
        description=payload.description,
        owner_employee_id=payload.owner_employee_id,
    )


@router.post("/{project_id}/tasks/{task_id}/blockers/{blocker_id}/resolve", response_model=TaskBlockerOut)
def resolve_task_blocker(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    blocker_id: uuid.UUID,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return TaskBlockerService(db).resolve_blocker(project_id, task_id, blocker_id, actor)


@router.post("/{project_id}/tasks/{task_id}/delays", response_model=TaskDelayOut)
def create_task_delay(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: TaskDelayCreateIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return TaskDelayService(db).create_delay(
        project_id, task_id, actor,
        responsibility_type=payload.responsibility_type,
        reason=payload.reason,
        impact_days=payload.impact_days,
        responsible_vendor_id=payload.responsible_vendor_id,
    )


@router.post("/{project_id}/tasks/{task_id}/support-assignments", response_model=TaskSupportAssignmentOut)
def assign_task_support(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: TaskSupportAssignmentCreateIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return TaskSupportAssignmentService(db).assign_support(
        project_id, task_id, payload.employee_id, payload.responsibility, actor,
    )


@router.post("/{project_id}/tasks/{task_id}/support-assignments/{assignment_id}/end", response_model=TaskSupportAssignmentOut)
def end_task_support(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    assignment_id: uuid.UUID,
    payload: TaskSupportAssignmentEndIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return TaskSupportAssignmentService(db).end_support(
        project_id, task_id, assignment_id, actor,
        reason_code=payload.reason_code, reason_detail=payload.reason_detail,
    )


@router.get("/{project_id}/tasks/{task_id}/evidence/{file_id}")
def download_task_evidence(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    file_id: uuid.UUID,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    file_object, content = TaskProgressService(db).get_evidence_file(project_id, task_id, file_id, actor)
    safe_filename = file_object.original_filename.replace('"', "").replace("\\", "").replace("\n", "").replace("\r", "")
    return StreamingResponse(
        io.BytesIO(content),
        media_type=file_object.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
