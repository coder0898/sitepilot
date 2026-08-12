"""U14 (R13): documents attached to an external approval.

WHO MAY ATTACH: Admin, and an Internal Employee actively delegated to this
gate. The delegate is the person who lodged the application and who receives
what comes back, so requiring an Admin to upload the acknowledgement they
never saw would just mean the file never gets attached.

Attaching a file is not deciding anything. The approval's *status* still
moves only where `GATE_ADMIN_ONLY_TRANSITIONS` allows, so a delegate can put
the landlord's letter on the record and still cannot mark the gate approved.
Evidence and decision stay separate.

WHO MAY READ: any project member. A blocked crew asking "what did the fire
officer actually say" should not need Admin to open the PDF for them.

STORAGE: `FileObject` under `settings.evidence_upload_dir`, the same private
store task evidence uses - a directory deliberately never handed to
StaticFiles. A signed NOC does not belong on a guessable public URL. The
only read path is `download_document`, which checks project access first.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.execution_models import (
    GATE_DOCUMENT_TYPES,
    ExecutionGate,
    ExecutionGateDelegation,
    ExecutionGateDocument,
    FileObject,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership

_ADMIN_ROLES = {UserRole.super_admin, UserRole.admin}

# Same allowlist and cap as task evidence. An approval arrives as a scan, a
# photo of a stamped letter, or a PDF - nothing here needs a wider surface.
ALLOWED_GATE_DOCUMENT_MIME_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}
MAX_GATE_DOCUMENT_SIZE_BYTES = 10 * 1024 * 1024


class ExecutionGateDocumentService:
    def __init__(self, db: Session):
        self.db = db

    # ---- guards ---------------------------------------------------------

    def _require_access(self, project_id: uuid.UUID, actor: User) -> V2Project:
        project = self.db.get(V2Project, project_id)
        if not project:
            raise HTTPException(404, "Project not found.")
        if actor.role in _ADMIN_ROLES or self._is_project_member(project.id, actor):
            return project
        raise HTTPException(403, "You do not have access to this project.")

    def _is_project_member(self, project_id: uuid.UUID, actor: User) -> bool:
        return self.db.scalar(
            select(V2ProjectMembership.id)
            .join(EmployeeProfile, EmployeeProfile.id == V2ProjectMembership.employee_id)
            .where(
                V2ProjectMembership.project_id == project_id,
                V2ProjectMembership.ends_at.is_(None),
                EmployeeProfile.user_id == actor.id,
            )
            .limit(1)
        ) is not None

    def _get_gate(self, project_id: uuid.UUID, gate_id: uuid.UUID) -> ExecutionGate:
        gate = self.db.scalar(select(ExecutionGate).where(
            ExecutionGate.id == gate_id, ExecutionGate.project_id == project_id
        ))
        if not gate:
            raise HTTPException(404, "Gate not found.")
        return gate

    def _require_uploader(self, gate: ExecutionGate, actor: User) -> None:
        if actor.role in _ADMIN_ROLES:
            return
        is_delegate = self.db.scalar(
            select(ExecutionGateDelegation.id)
            .join(EmployeeProfile, EmployeeProfile.id == ExecutionGateDelegation.employee_id)
            .where(
                ExecutionGateDelegation.execution_gate_id == gate.id,
                ExecutionGateDelegation.status == "active",
                ExecutionGateDelegation.ends_at.is_(None),
                EmployeeProfile.user_id == actor.id,
            )
            .limit(1)
        ) is not None
        if is_delegate:
            return
        raise HTTPException(
            403,
            "Only Admin, or an Internal Employee delegated to this approval, can attach a document to it.",
        )

    # ---- write ----------------------------------------------------------

    def attach_document(
        self, project_id: uuid.UUID, gate_id: uuid.UUID, actor: User,
        document_type: str, content: bytes, content_type: str | None,
        filename: str | None, caption: str | None = None,
    ) -> ExecutionGateDocument:
        project = self._require_access(project_id, actor)
        gate = self._get_gate(project.id, gate_id)
        self._require_uploader(gate, actor)

        if document_type not in GATE_DOCUMENT_TYPES:
            raise HTTPException(422, "document_type must be 'submission', 'outcome' or 'supporting'.")
        if not content:
            raise HTTPException(422, "The uploaded file is empty.")
        if content_type not in ALLOWED_GATE_DOCUMENT_MIME_TYPES:
            raise HTTPException(422, "Attach a PDF or an image (JPEG, PNG or WebP).")
        if len(content) > MAX_GATE_DOCUMENT_SIZE_BYTES:
            raise HTTPException(422, "This file is larger than 10 MB.")

        extension = ALLOWED_GATE_DOCUMENT_MIME_TYPES[content_type]
        storage_key = f"gate-{gate.id}-{uuid.uuid4().hex}{extension}"
        storage_dir = Path(settings.evidence_upload_dir)
        storage_dir.mkdir(parents=True, exist_ok=True)
        (storage_dir / storage_key).write_bytes(content)

        file_object = FileObject(
            storage_key=storage_key,
            original_filename=(filename or storage_key),
            mime_type=content_type,
            size_bytes=len(content),
            checksum=hashlib.sha256(content).hexdigest(),
            uploaded_by=actor.id,
        )
        self.db.add(file_object)
        self.db.flush()

        document = ExecutionGateDocument(
            execution_gate_id=gate.id, project_id=project.id, file_id=file_object.id,
            document_type=document_type, caption=(caption or "").strip() or None,
            uploaded_by=actor.id,
        )
        self.db.add(document)
        self.db.add(V2AuditEvent(
            actor_user_id=actor.id,
            action="PROJECT_GATE_DOCUMENT_ATTACHED",
            entity_type="execution_gate",
            entity_id=gate.id,
            project_id=project.id,
            source="portal",
            after_json={
                "gate_code": gate.original_code, "document_type": document_type,
                "filename": file_object.original_filename,
            },
            reason=f"Attached {document_type} document to {gate.original_code}.",
        ))
        self.db.commit()
        self.db.refresh(document)
        return document

    # ---- reads ----------------------------------------------------------

    def list_documents(self, project_id: uuid.UUID, gate_id: uuid.UUID, actor: User) -> list[tuple[ExecutionGateDocument, FileObject]]:
        project = self._require_access(project_id, actor)
        gate = self._get_gate(project.id, gate_id)
        return list(self.db.execute(
            select(ExecutionGateDocument, FileObject)
            .join(FileObject, FileObject.id == ExecutionGateDocument.file_id)
            .where(ExecutionGateDocument.execution_gate_id == gate.id)
            .order_by(ExecutionGateDocument.created_at.asc())
        ).all())

    def download_document(
        self, project_id: uuid.UUID, gate_id: uuid.UUID, document_id: uuid.UUID, actor: User,
    ) -> tuple[FileObject, bytes]:
        """The only read path to the bytes. Project access is checked before
        anything touches the filesystem, and the document is matched against
        *this* gate so a valid id from another project resolves to nothing."""
        project = self._require_access(project_id, actor)
        gate = self._get_gate(project.id, gate_id)

        document = self.db.scalar(select(ExecutionGateDocument).where(
            ExecutionGateDocument.id == document_id,
            ExecutionGateDocument.execution_gate_id == gate.id,
        ))
        if not document:
            raise HTTPException(404, "Document not found for this approval.")

        file_object = self.db.get(FileObject, document.file_id)
        if not file_object:
            raise HTTPException(404, "Document not found for this approval.")

        file_path = Path(settings.evidence_upload_dir) / file_object.storage_key
        if not file_path.is_file():
            raise HTTPException(404, "This document is no longer available.")
        return file_object, file_path.read_bytes()
