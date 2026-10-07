"""Read access to template reference files (Admin-provided material, never evidence)."""
from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import FileObject
from app.template_models import V2TemplateGateReferenceFile, V2TemplateTaskReferenceFile

ReferenceTarget = Literal["task", "gate"]


def reference_link_model(target: ReferenceTarget):
    return V2TemplateTaskReferenceFile if target == "task" else V2TemplateGateReferenceFile


def reference_owner_column(target: ReferenceTarget):
    return V2TemplateTaskReferenceFile.template_task_id if target == "task" else V2TemplateGateReferenceFile.gate_id


def reference_files_by_owner(db: Session, target: ReferenceTarget, owner_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict]]:
    """One query: the reference files of many template tasks or gates, oldest first."""
    if not owner_ids:
        return {}
    model, owner = reference_link_model(target), reference_owner_column(target)
    rows = db.execute(
        select(model, FileObject)
        .join(FileObject, FileObject.id == model.file_id)
        .where(owner.in_(owner_ids))
        .order_by(model.created_at, model.id)
    ).all()
    grouped: dict[uuid.UUID, list[dict]] = {}
    for link, file_object in rows:
        owner_id = link.template_task_id if target == "task" else link.gate_id
        grouped.setdefault(owner_id, []).append({
            "id": link.id,
            "file_id": file_object.id,
            "filename": file_object.original_filename,
            "mime_type": file_object.mime_type,
            "size_bytes": file_object.size_bytes,
            "checksum": file_object.checksum,
            "description": link.description,
            "created_at": link.created_at,
        })
    return grouped
