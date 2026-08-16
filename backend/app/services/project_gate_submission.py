"""Plan: External Approval Gate Assignment & Evidence Lifecycle (U4).

`ProjectGateSubmissionService.submit` lets the employee an external approval
gate is assigned to attach doc/photo evidence and move it from `assigned` to
`submitted` - including a resubmission after rejection, since `decide()`'s
reject path (U5) loops the gate back to `assigned` rather than ending it.

Evidence handling mirrors `task_progress.py`'s `TaskProgressService` in full:
same MIME allowlist and size cap, same `settings.evidence_upload_dir` disk
location (never passed to FastAPI's `StaticFiles`), same sha256 checksum on
`FileObject`, and the same authenticated re-check-then-read-bytes shape for
`get_evidence_file` - except scoped through this gate's own submission/
evidence tables rather than task_progress_updates/task_evidence, and joined
all the way to `project_id` before returning bytes (R7; see also the doc
review finding this closes: a project-level access check alone would let any
project member substitute a different file_id and read another approval's
evidence).

Submission is assignee-exclusive - unlike `TaskProgressService`, there is no
Supervisor/PM/Admin fallback path, since there is no support-assignment
concept for gates (only one assignee at a time, per R8's reassign/unassign
being the only way to change who that is).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.execution_models import (
    FileObject,
    ProjectExternalApproval,
    ProjectExternalApprovalEvidence,
    ProjectExternalApprovalSubmission,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership
from app.services.outbox import OutboxService

ALLOWED_EVIDENCE_MIME_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}
MAX_EVIDENCE_SIZE_BYTES = 10 * 1024 * 1024


class ProjectGateSubmissionService:
    def __init__(self, db: Session):
        self.db = db

    # ---- access ---------------------------------------------------------

    def _actor_project_roles(self, project_id: uuid.UUID, actor: User) -> set[str]:
        employee = self.db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == actor.id))
        if not employee:
            return set()
        rows = self.db.scalars(
            select(V2ProjectMembership.project_role).where(
                V2ProjectMembership.project_id == project_id,
                V2ProjectMembership.employee_id == employee.id,
                V2ProjectMembership.ends_at.is_(None),
            )
        )
        return set(rows)

    def _require_access(self, project_id: uuid.UUID, actor: User) -> V2Project:
        project = self.db.get(V2Project, project_id)
        if not project:
            raise HTTPException(404, "Project not found.")
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return project
        if self._actor_project_roles(project_id, actor):
            return project
        raise HTTPException(403, "You do not have access to this project.")

    def _get_approval(self, project_id: uuid.UUID, approval_id: uuid.UUID) -> ProjectExternalApproval:
        approval = self.db.scalar(
            select(ProjectExternalApproval).where(
                ProjectExternalApproval.id == approval_id,
                ProjectExternalApproval.project_id == project_id,
            )
        )
        if not approval:
            raise HTTPException(404, "External approval not found for this project.")
        return approval

    def _require_submitter(self, approval: ProjectExternalApproval, actor: User) -> None:
        """Assignee-exclusive - not even Admin/PM may submit on the
        assignee's behalf, matching R2's "the assigned employee submits"
        framing literally rather than treating Admin as a universal
        fallback the way decision authority does."""
        if approval.assigned_to_user_id != actor.id:
            raise HTTPException(
                403,
                "Only the employee this external approval is assigned to can submit evidence for it.",
            )

    # ---- submit -----------------------------------------------------------

    def submit(
        self,
        project_id: uuid.UUID,
        approval_id: uuid.UUID,
        actor: User,
        note: str | None,
        files: list[tuple[bytes, str | None, str | None]],
    ) -> ProjectExternalApprovalSubmission:
        """`files` is a list of (bytes, filename, content_type) tuples -
        the router reads uploads before calling in, same shape
        `submit_task_progress` uses for its single evidence file."""
        project = self._require_access(project_id, actor)
        approval = self._get_approval(project.id, approval_id)
        self._require_submitter(approval, actor)

        if approval.status != "assigned":
            raise HTTPException(
                409,
                f"This external approval is {approval.status}; only an assigned gate can receive a submission.",
            )

        clean_note = (note or "").strip() or None
        if not clean_note and not files:
            raise HTTPException(422, "A submission requires a note, evidence, or both.")

        file_objects: list[tuple[FileObject, str | None]] = []
        for evidence_bytes, evidence_filename, evidence_content_type in files:
            if evidence_content_type not in ALLOWED_EVIDENCE_MIME_TYPES:
                raise HTTPException(422, "Evidence must be JPG, PNG, WebP, or PDF.")
            if len(evidence_bytes) == 0:
                raise HTTPException(422, "Evidence file is empty.")
            if len(evidence_bytes) > MAX_EVIDENCE_SIZE_BYTES:
                raise HTTPException(422, "Evidence must be 10 MB or smaller.")

            extension = ALLOWED_EVIDENCE_MIME_TYPES[evidence_content_type]
            storage_key = f"{approval.id}-{uuid.uuid4().hex}{extension}"
            storage_dir = Path(settings.evidence_upload_dir)
            storage_dir.mkdir(parents=True, exist_ok=True)
            (storage_dir / storage_key).write_bytes(evidence_bytes)

            checksum = hashlib.sha256(evidence_bytes).hexdigest()
            file_object = FileObject(
                storage_key=storage_key,
                original_filename=(evidence_filename or storage_key),
                mime_type=evidence_content_type,
                size_bytes=len(evidence_bytes),
                checksum=checksum,
                uploaded_by=actor.id,
            )
            self.db.add(file_object)
            file_objects.append((file_object, evidence_content_type))

        if file_objects:
            self.db.flush()

        submission = ProjectExternalApprovalSubmission(
            approval_id=approval.id,
            submitted_by=actor.id,
            note=clean_note,
        )
        self.db.add(submission)
        self.db.flush()

        for file_object, evidence_content_type in file_objects:
            self.db.add(ProjectExternalApprovalEvidence(
                submission_id=submission.id,
                file_id=file_object.id,
                evidence_type="photo" if evidence_content_type != "application/pdf" else "document",
                caption=None,
            ))
        if file_objects:
            self.db.flush()

        previous_status = approval.status
        approval.status = "submitted"
        self.db.add(approval)
        self.db.flush()

        now = datetime.now(timezone.utc)
        self.db.add(V2AuditEvent(
            actor_user_id=actor.id,
            action="PROJECT_EXTERNAL_APPROVAL_SUBMITTED",
            entity_type="project_external_approval",
            entity_id=approval.id,
            project_id=project.id,
            source="portal",
            before_json={"status": previous_status},
            after_json={"status": "submitted", "submission_id": str(submission.id)},
            reason=clean_note or "External approval evidence submitted.",
            occurred_at=now,
        ))
        self.db.flush()

        # Same transaction-boundary rule as task_progress.py's evidence
        # emit: added beyond the row it describes but inside the same
        # still-open transaction, so the event and the submission commit
        # together or not at all.
        OutboxService(self.db).emit(
            event_type="project_external_approval.submitted",
            aggregate_type="project_external_approval",
            aggregate_id=approval.id,
            payload={
                "approval_id": str(approval.id),
                "project_id": str(project.id),
                "submission_id": str(submission.id),
                "submitted_by": str(actor.id),
            },
            idempotency_key=f"project_external_approval:{approval.id}:project_external_approval.submitted:{submission.id}",
        )

        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(submission)
        return submission

    # ---- download ---------------------------------------------------------

    def get_evidence_file(
        self, project_id: uuid.UUID, approval_id: uuid.UUID, file_id: uuid.UUID, actor: User,
    ) -> tuple[FileObject, bytes]:
        project = self._require_access(project_id, actor)
        approval = self._get_approval(project.id, approval_id)

        # R7 / IDOR fix from doc review: joined all the way through
        # submission -> approval_id -> project_id, not just a bare
        # project-level access check, so a file_id from a different
        # approval or project can never be substituted in the URL.
        evidence = self.db.scalar(
            select(ProjectExternalApprovalEvidence)
            .join(
                ProjectExternalApprovalSubmission,
                ProjectExternalApprovalEvidence.submission_id == ProjectExternalApprovalSubmission.id,
            )
            .where(
                ProjectExternalApprovalEvidence.file_id == file_id,
                ProjectExternalApprovalSubmission.approval_id == approval.id,
            )
        )
        if not evidence:
            raise HTTPException(404, "Evidence file not found for this external approval.")

        file_object = self.db.get(FileObject, file_id)
        if not file_object:
            raise HTTPException(404, "Evidence file not found for this external approval.")

        file_path = Path(settings.evidence_upload_dir) / file_object.storage_key
        if not file_path.is_file():
            raise HTTPException(404, "Evidence file is no longer available.")

        return file_object, file_path.read_bytes()
