"""U2: task lifecycle status transitions for the execution-layer `tasks` table.

This is the real implementation of the write path the read-only
`GET /{project_id}/execution-tasks` placeholder in `projects_v2.py`
anticipates. Later units (U3-U6) extend this router with progress/evidence,
verification/approval, blocker/delay, and support-assignment routes.
"""

import io
import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.database import get_db
from app.execution_models import FileObject, TaskApprovalDecision, TaskEvidence, TaskVerification
from app.models import User
from app.schemas.execution_tasks import (
    TaskApprovalIn,
    TaskApprovalOut,
    TaskBlockerCreateIn,
    TaskBlockerOut,
    TaskDelayCreateIn,
    TaskDelayOut,
    TaskEvidenceOut,
    TaskOut,
    TaskProgressUpdateOut,
    TaskStatusTransitionIn,
    TaskSupportAssignmentCreateIn,
    TaskSupportAssignmentEndIn,
    TaskSupportAssignmentOut,
    TaskVerificationIn,
    TaskVerificationOut,
)
from app.services.task_approval import TaskApprovalService
from app.services.task_blocker import TaskBlockerService
from app.services.task_delay import TaskDelayService
from app.services.task_lifecycle import TaskLifecycleService
from app.services.task_progress import TaskProgressService
from app.services.task_support_assignment import TaskSupportAssignmentService
from app.services.task_verification import TaskVerificationService

router = APIRouter(prefix="/api/v2/projects", tags=["v2-execution-tasks"])


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
