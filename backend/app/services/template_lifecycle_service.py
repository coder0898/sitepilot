"""Controlled cleanup for published test versions without destroying history."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import User
from app.services.template_audit import TemplateAuditAction, TemplateAuditWrite, write_template_audit_event
from app.services.template_mutation_access import (
    require_current_concurrency_token,
    require_template_mutation_access,
    stable_template_version_not_found,
)
from app.services.transaction_boundary import command_transaction
from app.template_lifecycle_schemas import TemplateArchiveVersionRequest, TemplateArchiveVersionResponse, TemplateDeleteDraftRequest, TemplateDeleteDraftResponse
from app.template_models import V2Template, V2TemplateExternalGate, V2TemplateExternalGateTask, V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion


class TemplateLifecycleService:
    def __init__(self, db: Session):
        self.db = db

    def archive_published_version(
        self,
        actor: User,
        version_id: uuid.UUID,
        payload: TemplateArchiveVersionRequest,
    ) -> TemplateArchiveVersionResponse:
        require_template_mutation_access(actor)
        with command_transaction(self.db):
            version = self.db.scalar(
                select(V2TemplateVersion)
                .where(V2TemplateVersion.id == version_id)
                .with_for_update()
            )
            if version is None:
                raise stable_template_version_not_found()
            if version.status != "published":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "published_version_required",
                        "message": "Only published template versions can be archived by this action.",
                        "version_id": str(version.id),
                        "status": version.status,
                    },
                )
            require_current_concurrency_token(version, payload.revision_token)

            template = self.db.scalar(
                select(V2Template)
                .where(V2Template.id == version.template_id)
                .with_for_update()
            )
            if template is None:
                raise stable_template_version_not_found()

            replacement = None
            if version.is_current_published:
                if payload.replacement_current_version_id is None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "code": "replacement_current_required",
                            "message": "Select another published version as current before archiving the current version.",
                            "version_id": str(version.id),
                        },
                    )
                if payload.replacement_current_version_id == version.id:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail={"code": "replacement_same_version", "message": "The replacement must be a different published version."},
                    )
                replacement = self.db.scalar(
                    select(V2TemplateVersion)
                    .where(V2TemplateVersion.id == payload.replacement_current_version_id)
                    .with_for_update()
                )
                if replacement is None or replacement.template_id != version.template_id or replacement.status != "published":
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "code": "invalid_replacement_current",
                            "message": "The replacement must be another published version of the same template.",
                        },
                    )

            before = {
                "status": version.status,
                "is_current_published": version.is_current_published,
                "replacement_current_version_id": str(replacement.id) if replacement else None,
            }
            now = datetime.now(timezone.utc)
            if replacement is not None:
                # Clear first so the partial unique index is never transiently violated.
                version.is_current_published = False
                self.db.flush()
                replacement.is_current_published = True
                replacement.updated_at = now
            version.status = "archived"
            version.is_current_published = False
            version.updated_at = now

            write_template_audit_event(
                self.db,
                TemplateAuditWrite(
                    action=TemplateAuditAction.TEMPLATE_VERSION_ARCHIVED,
                    entity_type="template_version",
                    entity_id=version.id,
                    actor_user_id=actor.id,
                    reason=payload.reason,
                    before_json=before,
                    after_json={
                        "status": "archived",
                        "is_current_published": False,
                        "replacement_current_version_id": str(replacement.id) if replacement else None,
                    },
                ),
            )

            return TemplateArchiveVersionResponse(
                template_id=template.id,
                version_id=version.id,
                version_no=version.version_no,
                status=version.status,
                is_current_published=version.is_current_published,
                archived_at=now,
                replacement_current_version_id=replacement.id if replacement else None,
            )
    def delete_unused_draft(
        self, actor: User, version_id: uuid.UUID, payload: TemplateDeleteDraftRequest
    ) -> TemplateDeleteDraftResponse:
        require_template_mutation_access(actor)
        with command_transaction(self.db):
            version = self.db.scalar(select(V2TemplateVersion).where(V2TemplateVersion.id == version_id).with_for_update())
            if version is None:
                raise stable_template_version_not_found()
            if version.status != "draft":
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "draft_version_required", "message": "Only draft versions can be deleted."})
            require_current_concurrency_token(version, payload.revision_token)
            template = self.db.scalar(select(V2Template).where(V2Template.id == version.template_id).with_for_update())
            if template is None:
                raise stable_template_version_not_found()

            gate_ids = select(V2TemplateExternalGate.id).where(V2TemplateExternalGate.template_version_id == version.id)
            task_ids = select(V2TemplateTask.id).where(V2TemplateTask.template_version_id == version.id)
            self.db.execute(delete(V2TemplateExternalGateTask).where((V2TemplateExternalGateTask.gate_id.in_(gate_ids)) | (V2TemplateExternalGateTask.template_task_id.in_(task_ids))))
            self.db.execute(delete(V2TemplateTaskDependency).where(V2TemplateTaskDependency.template_version_id == version.id))
            self.db.execute(delete(V2TemplateExternalGate).where(V2TemplateExternalGate.template_version_id == version.id))
            self.db.execute(delete(V2TemplateTask).where(V2TemplateTask.template_version_id == version.id))

            write_template_audit_event(self.db, TemplateAuditWrite(
                action=TemplateAuditAction.TEMPLATE_DRAFT_DELETED, entity_type="template_version", entity_id=version.id,
                actor_user_id=actor.id, reason=payload.reason,
                before_json={"status": "draft", "template_id": str(template.id), "version_no": version.version_no},
                after_json={"deleted": True},
            ))
            self.db.delete(version)
            self.db.flush()
            remaining = self.db.scalar(select(func.count()).select_from(V2TemplateVersion).where(V2TemplateVersion.template_id == template.id)) or 0
            template_deleted = remaining == 0
            if template_deleted:
                self.db.delete(template)
            return TemplateDeleteDraftResponse(template_id=template.id, version_id=version_id, deleted=True, template_deleted=template_deleted)

