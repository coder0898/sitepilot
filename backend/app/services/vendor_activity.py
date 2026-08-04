"""Phase 2 U3: vendor-attributable activity/incident capture (R5).

`VendorActivityService.log_activity` records a 'presence', 'delay',
'rework', or 'incident' event against a specific `TaskVendorAssignment`
(always task+vendor scoped), with a required `description`, an optional
`responsibility_decision` free text (used mainly for 'delay'-type events per
the plan), and 0 or 1 evidence files.

Evidence upload reuses `TaskProgressService`'s exact pattern (imported, not
redefined): the `ALLOWED_EVIDENCE_MIME_TYPES` allowlist and
`MAX_EVIDENCE_SIZE_BYTES` cap from `app.services.task_progress`, bytes
written under `settings.evidence_upload_dir`, a sha256 checksum, and a
`FileObject` row - then linked via `VendorActivityEvidence`, a dedicated
join table, never a polymorphic entity_type/entity_id reference (mirrors
`TaskEvidence`).

This module deliberately imports nothing from `app.services.task_lifecycle`
or `app.services.task_verification` - logging vendor activity never mutates
task lifecycle/verification/approval state (R5): a vendor cannot
start/complete/verify/approve/close a task through this mechanism.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.execution_models import FileObject
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.services.task_progress import ALLOWED_EVIDENCE_MIME_TYPES, MAX_EVIDENCE_SIZE_BYTES
from app.vendor_models import TaskVendorAssignment, VendorActivityEvent, VendorActivityEvidence

EVENT_TYPES = ("presence", "delay", "rework", "incident")


class VendorActivityService:
    def __init__(self, db: Session):
        self.db = db

    # ---- access -----------------------------------------------------

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

    def _require_pm(self, project: V2Project, actor: User) -> None:
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return
        roles = self._actor_project_roles(project.id, actor)
        if "project_manager" in roles:
            return
        raise HTTPException(403, "Only the project's PM, or an Admin, can log vendor activity.")

    def _get_assignment(
        self, project_id: uuid.UUID, task_id: uuid.UUID, assignment_id: uuid.UUID,
    ) -> TaskVendorAssignment:
        assignment = self.db.scalar(
            select(TaskVendorAssignment).where(
                TaskVendorAssignment.id == assignment_id,
                TaskVendorAssignment.task_id == task_id,
                TaskVendorAssignment.project_id == project_id,
            )
        )
        if not assignment:
            raise HTTPException(404, "Vendor assignment not found.")
        return assignment

    # ---- activity ---------------------------------------------------------

    def log_activity(
        self,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        assignment_id: uuid.UUID,
        actor: User,
        event_type: str,
        description: str | None,
        responsibility_decision: str | None = None,
        evidence_bytes: bytes | None = None,
        evidence_filename: str | None = None,
        evidence_content_type: str | None = None,
    ) -> VendorActivityEvent:
        project = self._require_access(project_id, actor)
        self._require_pm(project, actor)
        assignment = self._get_assignment(project.id, task_id, assignment_id)

        if event_type not in EVENT_TYPES:
            raise HTTPException(422, "Invalid event_type.")

        clean_description = (description or "").strip()
        if not clean_description:
            raise HTTPException(422, "A description is required.")
        clean_responsibility = (responsibility_decision or "").strip() or None

        file_object: FileObject | None = None
        if evidence_bytes is not None:
            if evidence_content_type not in ALLOWED_EVIDENCE_MIME_TYPES:
                raise HTTPException(422, "Evidence must be JPG, PNG, WebP, or PDF.")
            if len(evidence_bytes) == 0:
                raise HTTPException(422, "Evidence file is empty.")
            if len(evidence_bytes) > MAX_EVIDENCE_SIZE_BYTES:
                raise HTTPException(422, "Evidence must be 10 MB or smaller.")

            extension = ALLOWED_EVIDENCE_MIME_TYPES[evidence_content_type]
            storage_key = f"{assignment.id}-{uuid.uuid4().hex}{extension}"
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

        event = VendorActivityEvent(
            task_vendor_assignment_id=assignment.id,
            event_type=event_type,
            description=clean_description,
            responsibility_decision=clean_responsibility,
            recorded_by=actor.id,
        )
        self.db.add(event)
        self.db.flush()

        if file_object:
            self.db.add(VendorActivityEvidence(vendor_activity_event_id=event.id, file_id=file_object.id))
            self.db.flush()

        self.db.commit()
        self.db.refresh(event)
        return event
