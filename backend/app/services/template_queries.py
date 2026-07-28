"""Application-facing read services for V2 templates.

Every read delegates to the role-aware V2 repository. Inaccessible drafts and
nonexistent versions deliberately share the same 404 response.
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import User, UserRole
from app.repositories.template_repository import (
    DEFAULT_PAGE_SIZE,
    TemplateAggregateCounts,
    TemplateDependencyPage,
    TemplateGatePage,
    TemplateRepository,
    TemplateTaskPage,
    TemplateVersionPage,
    TemplateVersionSummary,
)
from app.services.template_access import require_template_module_access


TEMPLATE_NOT_FOUND_DETAIL = "Template version not found."


class TemplateQueryService:
    def __init__(self, session: Session, repository: TemplateRepository | None = None):
        self.repository = repository or TemplateRepository(session)

    @staticmethod
    def _role(user_or_role: User | UserRole) -> UserRole:
        return require_template_module_access(user_or_role)

    def list_versions(
        self,
        user_or_role: User | UserRole,
        *,
        search: str | None = None,
        statuses: set[str] | frozenset[str] | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> TemplateVersionPage:
        role = self._role(user_or_role)
        return self.repository.list_versions(
            role,
            search=search,
            statuses=statuses,
            page=page,
            page_size=page_size,
        )

    def get_version(
        self,
        user_or_role: User | UserRole,
        version_id: uuid.UUID,
    ) -> TemplateVersionSummary:
        role = self._role(user_or_role)
        version = self.repository.get_visible_version(role, version_id)
        if version is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=TEMPLATE_NOT_FOUND_DETAIL)
        return version

    def list_tasks(
        self,
        user_or_role: User | UserRole,
        version_id: uuid.UUID,
        *,
        search: str | None = None,
        schedule_classification: str | None = None,
        phase: str | None = None,
        category: str | None = None,
        applicability: str | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> TemplateTaskPage:
        role = self._role(user_or_role)
        if self.repository.get_visible_version(role, version_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=TEMPLATE_NOT_FOUND_DETAIL)
        return self.repository.list_tasks(
            version_id,
            search=search,
            schedule_classification=schedule_classification,
            phase=phase,
            category=category,
            applicability=applicability,
            page=page,
            page_size=page_size,
        )

    def list_dependencies(
        self,
        user_or_role: User | UserRole,
        version_id: uuid.UUID,
        *,
        search: str | None = None,
        dependency_type: str | None = None,
        blocking: bool | None = None,
        validation_state: str | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> TemplateDependencyPage:
        role = self._role(user_or_role)
        if self.repository.get_visible_version(role, version_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=TEMPLATE_NOT_FOUND_DETAIL)
        return self.repository.list_dependencies(
            version_id,
            search=search,
            dependency_type=dependency_type,
            blocking=blocking,
            validation_state=validation_state,
            page=page,
            page_size=page_size,
        )

    def list_gates(
        self,
        user_or_role: User | UserRole,
        version_id: uuid.UUID,
        *,
        search: str | None = None,
        mapping_classification: str | None = None,
        requires_configuration: bool | None = None,
        external_party: str | None = None,
        validation_state: str | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> TemplateGatePage:
        role = self._role(user_or_role)
        if self.repository.get_visible_version(role, version_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=TEMPLATE_NOT_FOUND_DETAIL)
        return self.repository.list_gates(
            version_id,
            search=search,
            mapping_classification=mapping_classification,
            requires_configuration=requires_configuration,
            external_party=external_party,
            validation_state=validation_state,
            page=page,
            page_size=page_size,
        )
    def aggregate_counts(
        self,
        user_or_role: User | UserRole,
        *,
        search: str | None = None,
        statuses: set[str] | frozenset[str] | None = None,
    ) -> TemplateAggregateCounts:
        role = self._role(user_or_role)
        return self.repository.aggregate_counts(role, search=search, statuses=statuses)