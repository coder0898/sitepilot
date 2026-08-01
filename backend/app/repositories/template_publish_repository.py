"""Locking and persistence primitives for atomic template publication."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services.template_mutation_access import (
    require_current_concurrency_token,
    require_draft_template_version,
    stable_template_version_not_found,
)
from app.template_models import V2Template, V2TemplateVersion


@dataclass(frozen=True)
class PublishLock:
    template: V2Template
    version: V2TemplateVersion
    previous_current: V2TemplateVersion | None


class TemplatePublishRepository:
    def __init__(self, db: Session):
        self.db = db

    def lock_for_publish(self, version_id: uuid.UUID, expected_token: str) -> PublishLock:
        version = self.db.scalar(
            select(V2TemplateVersion)
            .where(V2TemplateVersion.id == version_id)
            .with_for_update()
        )
        if version is None:
            raise stable_template_version_not_found()
        require_draft_template_version(version)
        require_current_concurrency_token(version, expected_token)

        template = self.db.scalar(
            select(V2Template)
            .where(V2Template.id == version.template_id)
            .with_for_update()
        )
        if template is None:
            raise stable_template_version_not_found()

        previous = self.db.scalar(
            select(V2TemplateVersion)
            .where(
                V2TemplateVersion.template_id == template.id,
                V2TemplateVersion.is_current_published.is_(True),
                V2TemplateVersion.id != version.id,
            )
            .with_for_update()
        )
        return PublishLock(template=template, version=version, previous_current=previous)

    def publish(
        self,
        lock: PublishLock,
        *,
        actor_id: uuid.UUID,
        change_note: str,
        content_hash: str,
        at: datetime | None = None,
    ) -> datetime:
        published_at = at or datetime.now(timezone.utc)
        if lock.previous_current is not None:
            lock.previous_current.is_current_published = False
            # Flush the old marker first so databases enforcing the partial
            # unique current-version index never observe two current rows.
            self.db.flush()

        target = lock.version
        target.status = "published"
        target.is_current_published = True
        target.published_at = published_at
        target.published_by = actor_id
        target.change_note = change_note
        target.content_hash = content_hash
        target.updated_at = published_at
        self.db.flush()
        return published_at
