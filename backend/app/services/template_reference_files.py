"""Admin reference material on template tasks and prerequisite approvals.

Reference material is what an Admin gives the person doing the work - an
approved specification, a drawing, a form to fill in. It is deliberately
separate from execution evidence (TaskEvidence / ProjectExternalApprovalEvidence),
which is proof submitted while the work happens.

- Files reuse `FileObject` and the private `evidence` bucket under a
  `template-references/` key prefix. Evidence retention only follows the
  evidence link tables, so it never purges reference files.
- Only a draft version can gain or lose reference files, and only an org
  admin can change them (the same rule as every other template mutation).
- A clone links the same `FileObject` rows; a file is never modified in
  place, so sharing is safe. Removing a reference removes only the link -
  the bytes stay, because another (possibly published) version may share them.
- Projects read references through the template version they are pinned to,
  so a later version can never change an existing project's material.
"""
from __future__ import annotations

import hashlib
import io
import uuid
import zipfile
from pathlib import PurePosixPath

from fastapi import HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import FileObject
from app.models import User
from app.repositories.template_mutation_repository import TemplateMutationRepository
from app.repositories.template_reference_repository import (
    ReferenceTarget,
    reference_files_by_owner,
    reference_link_model as _link_model,
    reference_owner_column as _owner_column,
)
from app.services import evidence_storage
from app.services.template_access import allowed_template_statuses
from app.services.template_audit import TemplateAuditAction, TemplateAuditWrite, write_template_audit_event
from app.services.template_mutation_access import require_template_mutation_access, stable_template_version_not_found
from app.services.transaction_boundary import command_transaction
from app.template_models import (
    V2TemplateExternalGate,
    V2TemplateTask,
    V2TemplateVersion,
)

# Extension -> (accepted MIME types, canonical MIME). Browsers often send DOCX
# and XLSX as application/octet-stream, so a generic type is accepted and the
# file's own bytes decide.
_GENERIC_MIME = {"", "application/octet-stream", "binary/octet-stream"}
ALLOWED_REFERENCE_TYPES: dict[str, tuple[frozenset[str], str]] = {
    ".pdf": (frozenset({"application/pdf"}), "application/pdf"),
    ".jpg": (frozenset({"image/jpeg"}), "image/jpeg"),
    ".jpeg": (frozenset({"image/jpeg"}), "image/jpeg"),
    ".png": (frozenset({"image/png"}), "image/png"),
    ".webp": (frozenset({"image/webp"}), "image/webp"),
    ".docx": (
        frozenset({"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    ".xlsx": (
        frozenset({"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
}
# Same cap as execution evidence.
MAX_REFERENCE_SIZE_BYTES = 10 * 1024 * 1024
MAX_DESCRIPTION_LENGTH = 500
TYPE_ERROR = "Reference files must be PDF, JPG, PNG, WebP, DOCX or XLSX."


def _content_matches(extension: str, data: bytes) -> bool:
    """Check the bytes really are the claimed type, so a renamed HTML or
    executable file cannot be stored as a "PDF"."""
    if extension == ".pdf":
        return data.startswith(b"%PDF-")
    if extension in (".jpg", ".jpeg"):
        return data.startswith(b"\xff\xd8\xff")
    if extension == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if extension == ".webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if extension in (".docx", ".xlsx"):
        marker = "word/document.xml" if extension == ".docx" else "xl/workbook.xml"
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                return marker in archive.namelist()
        except zipfile.BadZipFile:
            return False
    return False


def validate_reference_file(data: bytes, filename: str | None, content_type: str | None) -> tuple[str, str, str]:
    """Return (extension, canonical MIME, clean filename) or raise 422."""
    clean_name = PurePosixPath((filename or "").replace("\\", "/")).name.strip()
    extension = PurePosixPath(clean_name).suffix.lower()
    if extension not in ALLOWED_REFERENCE_TYPES:
        raise HTTPException(422, TYPE_ERROR)
    accepted, canonical = ALLOWED_REFERENCE_TYPES[extension]
    claimed = (content_type or "").split(";")[0].strip().lower()
    if claimed not in accepted and claimed not in _GENERIC_MIME:
        raise HTTPException(422, TYPE_ERROR)
    if not data:
        raise HTTPException(422, "The reference file is empty.")
    if len(data) > MAX_REFERENCE_SIZE_BYTES:
        raise HTTPException(422, "Reference files must be 10 MB or smaller.")
    if not _content_matches(extension, data):
        raise HTTPException(422, f"The file's contents do not match its {extension[1:].upper()} type.")
    return extension, canonical, clean_name


def read_reference_bytes(file_object: FileObject) -> bytes:
    data = evidence_storage.read(file_object.storage_key)
    if data is None:
        raise HTTPException(404, "The reference file is no longer available.")
    return data


def reference_file_response(file_object: FileObject, content: bytes) -> StreamingResponse:
    """Always an attachment with sniffing off, like evidence downloads."""
    # Drop quotes, backslashes and line breaks so the header cannot be split.
    safe_filename = "".join(ch for ch in file_object.original_filename if ch not in ('"', chr(92), chr(10), chr(13)))
    return StreamingResponse(
        io.BytesIO(content),
        media_type=file_object.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


class TemplateReferenceFileService:
    def __init__(self, db: Session):
        self.db = db
        self.versions = TemplateMutationRepository(db)

    def _owner(self, version: V2TemplateVersion, target: ReferenceTarget, owner_id: uuid.UUID):
        model = V2TemplateTask if target == "task" else V2TemplateExternalGate
        owner = self.db.scalar(select(model).where(model.id == owner_id, model.template_version_id == version.id))
        if owner is None:
            raise HTTPException(404, "Template task not found." if target == "task" else "Template external gate not found.")
        return owner

    def add(
        self,
        actor: User,
        version_id: uuid.UUID,
        target: ReferenceTarget,
        owner_id: uuid.UUID,
        *,
        data: bytes,
        filename: str | None,
        content_type: str | None,
        description: str | None,
        revision_token: str,
    ) -> dict:
        require_template_mutation_access(actor)
        clean_description = (description or "").strip() or None
        if clean_description and len(clean_description) > MAX_DESCRIPTION_LENGTH:
            raise HTTPException(422, f"The description must be {MAX_DESCRIPTION_LENGTH} characters or fewer.")
        # Validated before anything is stored, so a refusal leaves nothing behind.
        extension, mime_type, clean_name = validate_reference_file(data, filename, content_type)
        with command_transaction(self.db):
            version = self.versions.get_version_for_mutation(version_id, expected_token=revision_token)
            owner = self._owner(version, target, owner_id)
            storage_key = f"template-references/{version.id}/{uuid.uuid4().hex}{extension}"
            evidence_storage.write(storage_key, data, mime_type)
            file_object = FileObject(
                storage_key=storage_key,
                original_filename=clean_name,
                mime_type=mime_type,
                size_bytes=len(data),
                checksum=hashlib.sha256(data).hexdigest(),
                uploaded_by=actor.id,
            )
            self.db.add(file_object)
            self.db.flush()
            owner_field = {"template_task_id": owner.id} if target == "task" else {"gate_id": owner.id}
            link = _link_model(target)(file_id=file_object.id, description=clean_description, created_by=actor.id, **owner_field)
            self.db.add(link)
            self.db.flush()
            revision_token = self.versions.touch(version)
            write_template_audit_event(self.db, TemplateAuditWrite(
                action=TemplateAuditAction.TEMPLATE_REFERENCE_FILE_ADDED,
                entity_type=f"template_{target}_reference_file",
                entity_id=link.id,
                actor_user_id=actor.id,
                reason=f"Added reference file {clean_name} to template {target} {owner.code}.",
                after_json={"template_version_id": str(version.id), f"{target}_id": str(owner.id), "file_id": str(file_object.id),
                            "filename": clean_name, "mime_type": mime_type, "size_bytes": len(data)},
            ))
            reference = reference_files_by_owner(self.db, target, [owner.id])[owner.id]
            result = {"reference": next(item for item in reference if item["id"] == link.id), "revision_token": revision_token}
        return result

    def remove(
        self,
        actor: User,
        version_id: uuid.UUID,
        target: ReferenceTarget,
        owner_id: uuid.UUID,
        reference_id: uuid.UUID,
        *,
        revision_token: str,
    ) -> dict:
        require_template_mutation_access(actor)
        model, owner_column = _link_model(target), _owner_column(target)
        with command_transaction(self.db):
            version = self.versions.get_version_for_mutation(version_id, expected_token=revision_token)
            owner = self._owner(version, target, owner_id)
            link = self.db.scalar(select(model).where(model.id == reference_id, owner_column == owner.id))
            if link is None:
                raise HTTPException(404, "Reference file not found.")
            # The link only: the bytes may be shared with another version.
            file_id = link.file_id
            self.db.delete(link)
            self.db.flush()
            revision_token = self.versions.touch(version)
            write_template_audit_event(self.db, TemplateAuditWrite(
                action=TemplateAuditAction.TEMPLATE_REFERENCE_FILE_REMOVED,
                entity_type=f"template_{target}_reference_file",
                entity_id=reference_id,
                actor_user_id=actor.id,
                reason=f"Removed a reference file from template {target} {owner.code}.",
                before_json={"template_version_id": str(version.id), f"{target}_id": str(owner.id), "file_id": str(file_id)},
            ))
            result = {"reference_id": reference_id, "deleted": True, "revision_token": revision_token}
        return result

    def download(
        self,
        actor: User,
        version_id: uuid.UUID,
        target: ReferenceTarget,
        owner_id: uuid.UUID,
        reference_id: uuid.UUID,
    ) -> tuple[FileObject, bytes]:
        """Template-side preview: visible to anyone who may see this version
        (Admins any status; a PM only published versions)."""
        allowed = allowed_template_statuses(actor)
        version = self.db.get(V2TemplateVersion, version_id)
        if version is None or version.status not in allowed:
            raise stable_template_version_not_found()
        model, owner_column = _link_model(target), _owner_column(target)
        owner = self._owner(version, target, owner_id)
        row = self.db.execute(
            select(model, FileObject)
            .join(FileObject, FileObject.id == model.file_id)
            .where(model.id == reference_id, owner_column == owner.id)
        ).first()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Reference file not found.")
        file_object = row[1]
        return file_object, read_reference_bytes(file_object)
