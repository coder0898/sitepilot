"""U3: progress updates and evidence submission (R3).

`TaskProgressService.submit_progress` records an append-only progress note
against an execution-layer task, optionally with one evidence file. It never
changes `Task.lifecycle_status` itself - that stays U2's job, via a later
`submitted` transition that references this evidence.

Evidence bytes are written to `settings.evidence_upload_dir`, a directory
deliberately separate from `settings.upload_dir` and NEVER passed to
FastAPI's `StaticFiles` (see backend/app/main.py) - so a `file_objects.
storage_key` alone is never a reachable public URL. The only read path is
`TaskProgressService.get_evidence_file`, which re-checks the requester's
project access before returning bytes.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.execution_models import FileObject, Task, TaskEvidence, TaskProgressUpdate
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.services.outbox import OutboxService

# Reuse of the legacy module's (execution_v2.py `submit_task`) MIME
# allowlist and size-cap pattern - NOT its storage/URL approach, which is
# the exact public-URL mistake this unit corrects.
ALLOWED_EVIDENCE_MIME_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}
MAX_EVIDENCE_SIZE_BYTES = 10 * 1024 * 1024


class TaskProgressService:
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

    def _get_task(self, project_id: uuid.UUID, task_id: uuid.UUID) -> Task:
        task = self.db.scalar(
            select(Task).where(Task.id == task_id, Task.project_id == project_id)
        )
        if not task:
            raise HTTPException(404, "Task not found.")
        return task

    # ---- submit -----------------------------------------------------------

    def submit_progress(
        self,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        actor: User,
        note: str | None,
        status_claim: str | None = None,
        evidence_bytes: bytes | None = None,
        evidence_filename: str | None = None,
        evidence_content_type: str | None = None,
        source: str = "portal",
    ) -> TaskProgressUpdate:
        project = self._require_access(project_id, actor)
        task = self._get_task(project.id, task_id)

        clean_note = (note or "").strip() or None
        clean_status_claim = (status_claim or "").strip() or None

        if not clean_note and not evidence_bytes:
            raise HTTPException(422, "A progress update requires a note, evidence, or both.")

        file_object: FileObject | None = None
        if evidence_bytes is not None:
            if evidence_content_type not in ALLOWED_EVIDENCE_MIME_TYPES:
                raise HTTPException(422, "Evidence must be JPG, PNG, WebP, or PDF.")
            if len(evidence_bytes) == 0:
                raise HTTPException(422, "Evidence file is empty.")
            if len(evidence_bytes) > MAX_EVIDENCE_SIZE_BYTES:
                raise HTTPException(422, "Evidence must be 10 MB or smaller.")

            extension = ALLOWED_EVIDENCE_MIME_TYPES[evidence_content_type]
            storage_key = f"{task.id}-{uuid.uuid4().hex}{extension}"
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
            self.db.flush()

        progress_update = TaskProgressUpdate(
            task_id=task.id,
            project_id=project.id,
            update_type="evidence" if file_object else "note",
            status_claim=clean_status_claim,
            note=clean_note,
            submitted_by=actor.id,
            source=source,
        )
        self.db.add(progress_update)
        self.db.flush()

        if file_object:
            self.db.add(TaskEvidence(
                task_progress_update_id=progress_update.id,
                file_id=file_object.id,
                evidence_type="photo" if evidence_content_type != "application/pdf" else "document",
                caption=None,
            ))
            self.db.flush()

        # Added beyond the plan's literal U4 file list: R6/BR-015 explicitly
        # names "evidence submitted" as a mandatory outbox event, and this
        # is a Phase 1 mutation service exactly like the other six - see
        # the U4 unit report for the full reasoning.
        OutboxService(self.db).emit(
            event_type="task.evidence_submitted",
            aggregate_type="task",
            aggregate_id=task.id,
            payload={
                "task_id": str(task.id),
                "project_id": str(project.id),
                "progress_update_id": str(progress_update.id),
                "update_type": progress_update.update_type,
            },
            idempotency_key=f"task:{task.id}:task.evidence_submitted:{progress_update.id}",
        )

        self.db.commit()
        self.db.refresh(progress_update)
        return progress_update

    # ---- download ---------------------------------------------------------

    def get_evidence_file(
        self, project_id: uuid.UUID, task_id: uuid.UUID, file_id: uuid.UUID, actor: User,
    ) -> tuple[FileObject, bytes]:
        project = self._require_access(project_id, actor)
        task = self._get_task(project.id, task_id)

        evidence = self.db.scalar(
            select(TaskEvidence)
            .join(TaskProgressUpdate, TaskEvidence.task_progress_update_id == TaskProgressUpdate.id)
            .where(
                TaskEvidence.file_id == file_id,
                TaskProgressUpdate.task_id == task.id,
                TaskProgressUpdate.project_id == project.id,
            )
        )
        if not evidence:
            raise HTTPException(404, "Evidence file not found for this task.")

        file_object = self.db.get(FileObject, file_id)
        if not file_object:
            raise HTTPException(404, "Evidence file not found for this task.")

        file_path = Path(settings.evidence_upload_dir) / file_object.storage_key
        if not file_path.is_file():
            raise HTTPException(404, "Evidence file is no longer available.")

        return file_object, file_path.read_bytes()
