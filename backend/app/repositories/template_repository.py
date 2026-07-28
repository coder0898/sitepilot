"""SQL-only read repository for V2 templates.

Every public query starts from a role-filtered version statement.  Legacy
template tables are intentionally not imported into this module.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from sqlalchemy import Select, String, and_, case, cast, false, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.models import UserRole
from app.services.template_access import effective_template_statuses
from app.template_models import (
    V2Template,
    V2TemplateExternalGate,
    V2TemplateExternalGateTask,
    V2TemplateTask,
    V2TemplateTaskDependency,
    V2TemplateVersion,
)


DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class TemplateVersionSummary:
    template_id: uuid.UUID
    template_code: str
    template_name: str
    template_description: str | None
    version_id: uuid.UUID
    version_no: int
    status: str
    duration_days: int
    change_note: str | None
    content_hash: str | None
    is_current_published: bool
    created_at: Any
    updated_at: Any
    published_at: Any
    task_count: int
    dependency_count: int
    gate_count: int
    exact_mapping_count: int
    broad_text_gate_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TemplateVersionPage:
    items: list[TemplateVersionSummary]
    total: int
    page: int
    page_size: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
        }


@dataclass(frozen=True)
class TemplateTaskSummary:
    id: uuid.UUID
    code: str
    sequence_no: int | None
    title: str | None
    description: str | None
    schedule_classification: str | None
    planned_start_day: int | None
    planned_end_day: int | None
    phase: str | None
    category: str | None
    applicability: str | None
    task_class: str | None
    task_kind: str | None
    evidence_required: bool
    duration_days: int | None
    validation_state: str
    validation_issues: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TemplateTaskPage:
    items: list[TemplateTaskSummary]
    total: int
    page: int
    page_size: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
        }

@dataclass(frozen=True)
class TemplateDependencyTaskReference:
    id: uuid.UUID
    code: str
    title: str | None
    phase: str | None
    day: int | None


@dataclass(frozen=True)
class TemplateDependencySummary:
    id: uuid.UUID
    sequence_no: int
    dependency_type: str
    blocking: bool
    rule_text: str | None
    predecessor: TemplateDependencyTaskReference | None
    successor: TemplateDependencyTaskReference | None
    validation_state: str
    validation_issues: list[str]


@dataclass(frozen=True)
class TemplateDependencyCounts:
    total: int
    finish_to_start: int
    start_to_start: int
    blocking: int
    validation_issues: int


@dataclass(frozen=True)
class TemplateDependencyPage:
    items: list[TemplateDependencySummary]
    total: int
    page: int
    page_size: int
    summary: TemplateDependencyCounts

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [asdict(item) for item in self.items],
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
            "summary": asdict(self.summary),
        }

@dataclass(frozen=True)
class TemplateGateTaskReference:
    id: uuid.UUID
    code: str
    title: str | None
    phase: str | None
    day: int | None


@dataclass(frozen=True)
class TemplateGateSummary:
    id: uuid.UUID
    code: str
    sequence_no: int
    approval_name: str | None
    description: str | None
    external_party: str | None
    required_by_type: str | None
    required_by_value: str | None
    impact: str | None
    mapping_classification: str
    requires_configuration: bool
    broad_mapping_text: str | None
    affected_tasks: list[TemplateGateTaskReference]
    validation_state: str
    validation_issues: list[str]


@dataclass(frozen=True)
class TemplateGatePage:
    items: list[TemplateGateSummary]
    total: int
    page: int
    page_size: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [asdict(item) for item in self.items],
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
        }


@dataclass(frozen=True)
class TemplateAggregateCounts:
    version_count: int
    task_count: int
    dependency_count: int
    gate_count: int
    exact_mapping_count: int
    broad_text_gate_count: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _validated_pagination(page: int, page_size: int) -> tuple[int, int]:
    if page < 1:
        raise ValueError("Page must be at least 1.")
    if page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise ValueError(f"Page size must be between 1 and {MAX_PAGE_SIZE}.")
    return page, page_size


def _task_validation_issues(
    task: Any,
    *,
    duplicate_code_count: int = 1,
    duplicate_sequence_count: int = 1,
) -> list[str]:
    """Report persisted task problems without changing the stored record."""
    issues: list[str] = []
    if duplicate_code_count > 1:
        issues.append("duplicate_code")
    if duplicate_sequence_count > 1:
        issues.append("duplicate_sequence")
    if task.sequence_no is None:
        issues.append("missing_sequence")
    if not isinstance(task.title, str) or not task.title.strip():
        issues.append("missing_title")
    if task.schedule_classification not in {"pre_activation", "execution"}:
        issues.append("invalid_schedule_classification")
    if task.schedule_classification == "execution" and (
        task.planned_start_day is None or task.planned_end_day is None
    ):
        issues.append("missing_execution_day")
    days = [day for day in (task.planned_start_day, task.planned_end_day) if day is not None]
    if any(day < 1 or day > 45 for day in days):
        issues.append("execution_day_out_of_range")
    if (
        task.planned_start_day is not None
        and task.planned_end_day is not None
        and task.planned_start_day > task.planned_end_day
    ):
        issues.append("planned_start_after_end")
    if task.applicability not in {"mandatory", "conditional"}:
        issues.append("unsupported_applicability")
    return issues

def _dependency_validation_issues(
    dependency: Any,
    predecessor: Any | None,
    successor: Any | None,
    *,
    duplicate_pair_count: int = 1,
) -> list[str]:
    """Report persisted dependency problems without repairing the source row."""
    issues: list[str] = []
    if predecessor is None:
        issues.append("missing_predecessor")
    if successor is None:
        issues.append("missing_successor")
    if (
        dependency.predecessor_task_id is not None
        and dependency.successor_task_id is not None
        and dependency.predecessor_task_id == dependency.successor_task_id
    ):
        issues.append("self_dependency")
    if dependency.dependency_type not in {"finish_to_start", "start_to_start"}:
        issues.append("unsupported_dependency_type")
    if duplicate_pair_count > 1:
        issues.append("duplicate_pair")
    if (
        (predecessor is not None and predecessor.template_version_id != dependency.template_version_id)
        or (successor is not None and successor.template_version_id != dependency.template_version_id)
    ):
        issues.append("cross_version_reference")
    return issues

def _gate_validation_issues(
    gate: Any,
    mappings: Iterable[tuple[Any, Any | None]],
) -> list[str]:
    """Report persisted gate/mapping problems without repairing source data."""
    issues: list[str] = []
    mapping_rows = list(mappings)

    if not isinstance(gate.approval_name, str) or not gate.approval_name.strip():
        issues.append("missing_name")
    if not isinstance(gate.external_party, str) or not gate.external_party.strip():
        issues.append("missing_external_party")

    required_type = gate.required_by_type
    required_value = gate.required_by_value
    if (
        not isinstance(required_type, str)
        or not required_type.strip()
        or not isinstance(required_value, str)
        or not required_value.strip()
    ):
        issues.append("invalid_required_by")

    classification = gate.mapping_classification
    if classification not in {"exact", "broad_text", "unmapped"}:
        issues.append("unsupported_mapping_classification")

    mapped_task_ids: list[Any] = []
    for _link, task in mapping_rows:
        if task is None:
            if "missing_exact_task" not in issues:
                issues.append("missing_exact_task")
            continue
        mapped_task_ids.append(task.id)
        if task.template_version_id != gate.template_version_id and "cross_version_mapping" not in issues:
            issues.append("cross_version_mapping")

    if len(mapped_task_ids) != len(set(mapped_task_ids)):
        issues.append("duplicate_mapping")
    if classification == "exact" and not mapping_rows:
        issues.append("exact_gate_without_tasks")
    if classification == "broad_text":
        if mapping_rows:
            issues.append("broad_gate_has_exact_mappings")
        if not isinstance(gate.broad_mapping_text, str) or not gate.broad_mapping_text.strip():
            issues.append("missing_broad_mapping_text")
        if not gate.requires_configuration:
            issues.append("requires_configuration_missing")
    if classification == "unmapped":
        issues.append("unmapped_gate")
        if not gate.requires_configuration:
            issues.append("requires_configuration_missing")
    return issues


class TemplateRepository:
    def __init__(self, session: Session):
        self.session = session

    def visible_versions_statement(
        self,
        role: UserRole,
        *,
        search: str | None = None,
        statuses: set[str] | frozenset[str] | None = None,
    ) -> Select:
        """Build the only base statement used for role-aware version reads."""
        visible_statuses = effective_template_statuses(role, statuses)
        statement = select(V2Template, V2TemplateVersion).join(
            V2TemplateVersion,
            V2TemplateVersion.template_id == V2Template.id,
        )
        if visible_statuses:
            statement = statement.where(V2TemplateVersion.status.in_(sorted(visible_statuses)))
        else:
            # An Admin/PM asking for draft receives an empty result, not evidence
            # that drafts exist or a count derived from an unrestricted query.
            statement = statement.where(false())
        normalized_search = (search or "").strip().lower()
        if normalized_search:
            pattern = f"%{_escape_like(normalized_search)}%"
            statement = statement.where(
                or_(
                    func.lower(V2Template.code).like(pattern, escape="\\"),
                    func.lower(V2Template.name).like(pattern, escape="\\"),
                    cast(V2TemplateVersion.version_no, String).like(pattern, escape="\\"),
                )
            )
        return statement

    def published_versions_statement(self, role: UserRole, *, search: str | None = None) -> Select:
        return self.visible_versions_statement(role, search=search, statuses={"published"})

    def _summary_columns(self):
        task_count = (
            select(func.count())
            .select_from(V2TemplateTask)
            .where(V2TemplateTask.template_version_id == V2TemplateVersion.id)
            .correlate(V2TemplateVersion)
            .scalar_subquery()
        )
        dependency_count = (
            select(func.count())
            .select_from(V2TemplateTaskDependency)
            .where(V2TemplateTaskDependency.template_version_id == V2TemplateVersion.id)
            .correlate(V2TemplateVersion)
            .scalar_subquery()
        )
        gate_count = (
            select(func.count())
            .select_from(V2TemplateExternalGate)
            .where(V2TemplateExternalGate.template_version_id == V2TemplateVersion.id)
            .correlate(V2TemplateVersion)
            .scalar_subquery()
        )
        exact_mapping_count = (
            select(func.count())
            .select_from(V2TemplateExternalGateTask)
            .join(V2TemplateExternalGate, V2TemplateExternalGate.id == V2TemplateExternalGateTask.gate_id)
            .where(V2TemplateExternalGate.template_version_id == V2TemplateVersion.id)
            .correlate(V2TemplateVersion)
            .scalar_subquery()
        )
        broad_text_gate_count = (
            select(func.count())
            .select_from(V2TemplateExternalGate)
            .where(
                V2TemplateExternalGate.template_version_id == V2TemplateVersion.id,
                V2TemplateExternalGate.mapping_classification == "broad_text",
            )
            .correlate(V2TemplateVersion)
            .scalar_subquery()
        )
        return (
            task_count.label("task_count"),
            dependency_count.label("dependency_count"),
            gate_count.label("gate_count"),
            exact_mapping_count.label("exact_mapping_count"),
            broad_text_gate_count.label("broad_text_gate_count"),
        )

    def _with_summary(self, statement: Select) -> Select:
        return statement.add_columns(*self._summary_columns())

    @staticmethod
    def _summary(row: Any) -> TemplateVersionSummary:
        template, version = row[0], row[1]
        return TemplateVersionSummary(
            template_id=template.id,
            template_code=template.code,
            template_name=template.name,
            template_description=template.description,
            version_id=version.id,
            version_no=version.version_no,
            status=version.status,
            duration_days=version.duration_days,
            change_note=version.change_note,
            content_hash=version.content_hash,
            is_current_published=version.is_current_published,
            created_at=version.created_at,
            updated_at=version.updated_at,
            published_at=version.published_at,
            task_count=int(row.task_count or 0),
            dependency_count=int(row.dependency_count or 0),
            gate_count=int(row.gate_count or 0),
            exact_mapping_count=int(row.exact_mapping_count or 0),
            broad_text_gate_count=int(row.broad_text_gate_count or 0),
        )

    def list_versions(
        self,
        role: UserRole,
        *,
        search: str | None = None,
        statuses: set[str] | frozenset[str] | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> TemplateVersionPage:
        page, page_size = _validated_pagination(page, page_size)
        base = self.visible_versions_statement(role, search=search, statuses=statuses)
        total = self.session.scalar(select(func.count()).select_from(base.subquery())) or 0
        statement = (
            self._with_summary(base)
            .order_by(
                func.lower(V2Template.name).asc(),
                V2TemplateVersion.is_current_published.desc(),
                func.coalesce(V2TemplateVersion.published_at, V2TemplateVersion.created_at).desc(),
                V2TemplateVersion.id.asc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = [self._summary(row) for row in self.session.execute(statement).all()]
        return TemplateVersionPage(items=items, total=int(total), page=page, page_size=page_size)

    def get_visible_version(self, role: UserRole, version_id: uuid.UUID) -> TemplateVersionSummary | None:
        statement = self._with_summary(self.visible_versions_statement(role)).where(
            V2TemplateVersion.id == version_id
        )
        row = self.session.execute(statement).first()
        return self._summary(row) if row is not None else None

    def list_tasks(
        self,
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
        page, page_size = _validated_pagination(page, page_size)
        base = select(V2TemplateTask).where(V2TemplateTask.template_version_id == version_id)

        normalized_search = (search or "").strip().lower()
        if normalized_search:
            pattern = f"%{_escape_like(normalized_search)}%"
            base = base.where(
                or_(
                    func.lower(V2TemplateTask.code).like(pattern, escape="\\"),
                    func.lower(V2TemplateTask.title).like(pattern, escape="\\"),
                    func.lower(V2TemplateTask.description).like(pattern, escape="\\"),
                )
            )
        if schedule_classification:
            base = base.where(V2TemplateTask.schedule_classification == schedule_classification)
        normalized_phase = (phase or "").strip().lower()
        if normalized_phase:
            base = base.where(func.lower(V2TemplateTask.phase) == normalized_phase)
        normalized_category = (category or "").strip().lower()
        if normalized_category:
            base = base.where(func.lower(V2TemplateTask.category) == normalized_category)
        if applicability:
            base = base.where(V2TemplateTask.applicability == applicability)

        total = int(self.session.scalar(select(func.count()).select_from(base.subquery())) or 0)
        code_peer = aliased(V2TemplateTask)
        sequence_peer = aliased(V2TemplateTask)
        duplicate_code_count = (
            select(func.count())
            .select_from(code_peer)
            .where(
                code_peer.template_version_id == V2TemplateTask.template_version_id,
                code_peer.code == V2TemplateTask.code,
            )
            .correlate(V2TemplateTask)
            .scalar_subquery()
            .label("duplicate_code_count")
        )
        duplicate_sequence_count = (
            select(func.count())
            .select_from(sequence_peer)
            .where(
                sequence_peer.template_version_id == V2TemplateTask.template_version_id,
                sequence_peer.sequence_no == V2TemplateTask.sequence_no,
            )
            .correlate(V2TemplateTask)
            .scalar_subquery()
            .label("duplicate_sequence_count")
        )
        statement = (
            base.add_columns(duplicate_code_count, duplicate_sequence_count)
            .order_by(
                case(
                    (V2TemplateTask.schedule_classification == "pre_activation", 0),
                    (V2TemplateTask.schedule_classification == "execution", 1),
                    else_=2,
                ),
                func.coalesce(V2TemplateTask.sequence_no, 2147483647),
                func.lower(V2TemplateTask.code),
                V2TemplateTask.id,
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items: list[TemplateTaskSummary] = []
        for row in self.session.execute(statement).all():
            task = row[0]
            issues = _task_validation_issues(
                task,
                duplicate_code_count=int(row.duplicate_code_count or 0),
                duplicate_sequence_count=int(row.duplicate_sequence_count or 0),
            )
            items.append(
                TemplateTaskSummary(
                    id=task.id,
                    code=task.code,
                    sequence_no=task.sequence_no,
                    title=task.title,
                    description=task.description,
                    schedule_classification=task.schedule_classification,
                    planned_start_day=task.planned_start_day,
                    planned_end_day=task.planned_end_day,
                    phase=task.phase,
                    category=task.category,
                    applicability=task.applicability,
                    task_class=task.task_class,
                    task_kind=task.task_kind,
                    evidence_required=task.evidence_required,
                    duration_days=task.duration_days,
                    validation_state="invalid" if issues else "valid",
                    validation_issues=issues,
                )
            )
        return TemplateTaskPage(items=items, total=total, page=page, page_size=page_size)
    def list_dependencies(
        self,
        version_id: uuid.UUID,
        *,
        search: str | None = None,
        dependency_type: str | None = None,
        blocking: bool | None = None,
        validation_state: str | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> TemplateDependencyPage:
        page, page_size = _validated_pagination(page, page_size)
        if validation_state not in {None, "valid", "invalid"}:
            raise ValueError("Validation state must be 'valid' or 'invalid'.")

        predecessor = aliased(V2TemplateTask)
        successor = aliased(V2TemplateTask)
        dependency_peer = aliased(V2TemplateTaskDependency)
        duplicate_pair_count = (
            select(func.count())
            .select_from(dependency_peer)
            .where(
                dependency_peer.template_version_id == V2TemplateTaskDependency.template_version_id,
                dependency_peer.predecessor_task_id == V2TemplateTaskDependency.predecessor_task_id,
                dependency_peer.successor_task_id == V2TemplateTaskDependency.successor_task_id,
                dependency_peer.dependency_type == V2TemplateTaskDependency.dependency_type,
            )
            .correlate(V2TemplateTaskDependency)
            .scalar_subquery()
            .label("duplicate_pair_count")
        )
        invalid_condition = or_(
            predecessor.id.is_(None),
            successor.id.is_(None),
            V2TemplateTaskDependency.predecessor_task_id == V2TemplateTaskDependency.successor_task_id,
            ~V2TemplateTaskDependency.dependency_type.in_(("finish_to_start", "start_to_start")),
            duplicate_pair_count > 1,
            and_(
                predecessor.id.is_not(None),
                predecessor.template_version_id != V2TemplateTaskDependency.template_version_id,
            ),
            and_(
                successor.id.is_not(None),
                successor.template_version_id != V2TemplateTaskDependency.template_version_id,
            ),
        )
        summary_statement = (
            select(
                func.count(V2TemplateTaskDependency.id).label("total"),
                func.coalesce(
                    func.sum(
                        case(
                            (V2TemplateTaskDependency.dependency_type == "finish_to_start", 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("finish_to_start"),
                func.coalesce(
                    func.sum(
                        case(
                            (V2TemplateTaskDependency.dependency_type == "start_to_start", 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("start_to_start"),
                func.coalesce(
                    func.sum(
                        case((V2TemplateTaskDependency.blocking.is_(True), 1), else_=0)
                    ),
                    0,
                ).label("blocking"),
                func.coalesce(
                    func.sum(case((invalid_condition, 1), else_=0)),
                    0,
                ).label("validation_issues"),
            )
            .select_from(V2TemplateTaskDependency)
            .outerjoin(predecessor, predecessor.id == V2TemplateTaskDependency.predecessor_task_id)
            .outerjoin(successor, successor.id == V2TemplateTaskDependency.successor_task_id)
            .where(V2TemplateTaskDependency.template_version_id == version_id)
        )
        summary_row = self.session.execute(summary_statement).one()
        summary = TemplateDependencyCounts(
            total=int(summary_row.total or 0),
            finish_to_start=int(summary_row.finish_to_start or 0),
            start_to_start=int(summary_row.start_to_start or 0),
            blocking=int(summary_row.blocking or 0),
            validation_issues=int(summary_row.validation_issues or 0),
        )

        base = (
            select(V2TemplateTaskDependency, predecessor, successor)
            .select_from(V2TemplateTaskDependency)
            .outerjoin(predecessor, predecessor.id == V2TemplateTaskDependency.predecessor_task_id)
            .outerjoin(successor, successor.id == V2TemplateTaskDependency.successor_task_id)
            .where(V2TemplateTaskDependency.template_version_id == version_id)
        )
        normalized_search = (search or "").strip().lower()
        if normalized_search:
            pattern = f"%{_escape_like(normalized_search)}%"
            base = base.where(
                or_(
                    func.lower(predecessor.code).like(pattern, escape="\\"),
                    func.lower(predecessor.title).like(pattern, escape="\\"),
                    func.lower(successor.code).like(pattern, escape="\\"),
                    func.lower(successor.title).like(pattern, escape="\\"),
                )
            )
        if dependency_type:
            base = base.where(V2TemplateTaskDependency.dependency_type == dependency_type)
        if blocking is not None:
            base = base.where(V2TemplateTaskDependency.blocking.is_(blocking))
        if validation_state == "valid":
            base = base.where(~invalid_condition)
        elif validation_state == "invalid":
            base = base.where(invalid_condition)

        total = int(self.session.scalar(select(func.count()).select_from(base.subquery())) or 0)
        statement = (
            base.add_columns(duplicate_pair_count)
            .order_by(
                V2TemplateTaskDependency.sequence_no,
                func.coalesce(predecessor.sequence_no, 2147483647),
                func.coalesce(successor.sequence_no, 2147483647),
                V2TemplateTaskDependency.id,
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items: list[TemplateDependencySummary] = []
        for row in self.session.execute(statement).all():
            dependency, predecessor_task, successor_task = row[0], row[1], row[2]
            issues = _dependency_validation_issues(
                dependency,
                predecessor_task,
                successor_task,
                duplicate_pair_count=int(row.duplicate_pair_count or 0),
            )

            def task_reference(task: Any | None) -> TemplateDependencyTaskReference | None:
                if task is None:
                    return None
                return TemplateDependencyTaskReference(
                    id=task.id,
                    code=task.code,
                    title=task.title,
                    phase=task.phase,
                    day=task.planned_start_day,
                )

            items.append(
                TemplateDependencySummary(
                    id=dependency.id,
                    sequence_no=dependency.sequence_no,
                    dependency_type=dependency.dependency_type,
                    blocking=dependency.blocking,
                    rule_text=dependency.rule_text,
                    predecessor=task_reference(predecessor_task),
                    successor=task_reference(successor_task),
                    validation_state="invalid" if issues else "valid",
                    validation_issues=issues,
                )
            )
        return TemplateDependencyPage(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            summary=summary,
        )
    def list_gates(
        self,
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
        page, page_size = _validated_pagination(page, page_size)
        if validation_state not in {None, "valid", "invalid"}:
            raise ValueError("Validation state must be 'valid' or 'invalid'.")

        mapped_task = aliased(V2TemplateTask)
        gate_link = aliased(V2TemplateExternalGateTask)
        missing_task_link = aliased(V2TemplateExternalGateTask)
        missing_task = aliased(V2TemplateTask)
        cross_version_link = aliased(V2TemplateExternalGateTask)
        cross_version_task = aliased(V2TemplateTask)
        duplicate_link = aliased(V2TemplateExternalGateTask)

        mapping_count = (
            select(func.count(gate_link.id))
            .where(gate_link.gate_id == V2TemplateExternalGate.id)
            .correlate(V2TemplateExternalGate)
            .scalar_subquery()
        )
        missing_task_count = (
            select(func.count(missing_task_link.id))
            .select_from(missing_task_link)
            .outerjoin(missing_task, missing_task.id == missing_task_link.template_task_id)
            .where(
                missing_task_link.gate_id == V2TemplateExternalGate.id,
                missing_task.id.is_(None),
            )
            .correlate(V2TemplateExternalGate)
            .scalar_subquery()
        )
        cross_version_count = (
            select(func.count(cross_version_link.id))
            .select_from(cross_version_link)
            .join(cross_version_task, cross_version_task.id == cross_version_link.template_task_id)
            .where(
                cross_version_link.gate_id == V2TemplateExternalGate.id,
                cross_version_task.template_version_id
                != V2TemplateExternalGate.template_version_id,
            )
            .correlate(V2TemplateExternalGate)
            .scalar_subquery()
        )
        duplicate_mapping_exists = (
            select(duplicate_link.template_task_id)
            .where(duplicate_link.gate_id == V2TemplateExternalGate.id)
            .group_by(duplicate_link.template_task_id)
            .having(func.count(duplicate_link.id) > 1)
            .correlate(V2TemplateExternalGate)
            .exists()
        )

        def blank(column: Any) -> Any:
            return func.length(func.trim(func.coalesce(column, ""))) == 0

        invalid_condition = or_(
            blank(V2TemplateExternalGate.approval_name),
            blank(V2TemplateExternalGate.external_party),
            blank(V2TemplateExternalGate.required_by_type),
            blank(V2TemplateExternalGate.required_by_value),
            ~V2TemplateExternalGate.mapping_classification.in_(
                ("exact", "broad_text", "unmapped")
            ),
            V2TemplateExternalGate.mapping_classification == "unmapped",
            and_(
                V2TemplateExternalGate.mapping_classification == "exact",
                mapping_count == 0,
            ),
            and_(
                V2TemplateExternalGate.mapping_classification == "broad_text",
                mapping_count > 0,
            ),
            and_(
                V2TemplateExternalGate.mapping_classification == "broad_text",
                blank(V2TemplateExternalGate.broad_mapping_text),
            ),
            and_(
                V2TemplateExternalGate.mapping_classification.in_(
                    ("broad_text", "unmapped")
                ),
                V2TemplateExternalGate.requires_configuration.is_(False),
            ),
            missing_task_count > 0,
            cross_version_count > 0,
            duplicate_mapping_exists,
        )

        base = select(V2TemplateExternalGate).where(
            V2TemplateExternalGate.template_version_id == version_id
        )
        normalized_search = (search or "").strip().lower()
        if normalized_search:
            pattern = f"%{_escape_like(normalized_search)}%"
            base = base.where(
                or_(
                    func.lower(V2TemplateExternalGate.code).like(pattern, escape="\\"),
                    func.lower(V2TemplateExternalGate.approval_name).like(pattern, escape="\\"),
                    func.lower(V2TemplateExternalGate.external_party).like(pattern, escape="\\"),
                    func.lower(V2TemplateExternalGate.broad_mapping_text).like(pattern, escape="\\"),
                )
            )
        if mapping_classification:
            base = base.where(
                V2TemplateExternalGate.mapping_classification == mapping_classification
            )
        if requires_configuration is not None:
            base = base.where(
                V2TemplateExternalGate.requires_configuration.is_(requires_configuration)
            )
        normalized_party = (external_party or "").strip().lower()
        if normalized_party:
            base = base.where(
                func.lower(func.trim(V2TemplateExternalGate.external_party))
                == normalized_party
            )
        if validation_state == "valid":
            base = base.where(~invalid_condition)
        elif validation_state == "invalid":
            base = base.where(invalid_condition)

        total = int(self.session.scalar(select(func.count()).select_from(base.subquery())) or 0)
        gates = list(
            self.session.scalars(
                base.order_by(
                    V2TemplateExternalGate.sequence_no,
                    V2TemplateExternalGate.code,
                    V2TemplateExternalGate.id,
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        gate_ids = [gate.id for gate in gates]
        mappings_by_gate: dict[uuid.UUID, list[tuple[Any, Any | None]]] = {
            gate_id: [] for gate_id in gate_ids
        }
        if gate_ids:
            mapping_statement = (
                select(V2TemplateExternalGateTask, mapped_task)
                .select_from(V2TemplateExternalGateTask)
                .outerjoin(
                    mapped_task,
                    mapped_task.id == V2TemplateExternalGateTask.template_task_id,
                )
                .where(V2TemplateExternalGateTask.gate_id.in_(gate_ids))
                .order_by(
                    V2TemplateExternalGateTask.gate_id,
                    func.coalesce(mapped_task.sequence_no, 2147483647),
                    mapped_task.code,
                    V2TemplateExternalGateTask.id,
                )
            )
            for link, task in self.session.execute(mapping_statement).all():
                mappings_by_gate.setdefault(link.gate_id, []).append((link, task))

        items: list[TemplateGateSummary] = []
        for gate in gates:
            mappings = mappings_by_gate.get(gate.id, [])
            issues = _gate_validation_issues(gate, mappings)
            affected_tasks = []
            if gate.mapping_classification == "exact":
                affected_tasks = [
                    TemplateGateTaskReference(
                        id=task.id,
                        code=task.code,
                        title=task.title,
                        phase=task.phase,
                        day=task.planned_start_day,
                    )
                    for _link, task in mappings
                    if task is not None
                ]
            items.append(
                TemplateGateSummary(
                    id=gate.id,
                    code=gate.code,
                    sequence_no=gate.sequence_no,
                    approval_name=gate.approval_name,
                    description=gate.description,
                    external_party=gate.external_party,
                    required_by_type=gate.required_by_type,
                    required_by_value=gate.required_by_value,
                    impact=gate.impact,
                    mapping_classification=gate.mapping_classification,
                    requires_configuration=gate.requires_configuration,
                    broad_mapping_text=gate.broad_mapping_text,
                    affected_tasks=affected_tasks,
                    validation_state="invalid" if issues else "valid",
                    validation_issues=issues,
                )
            )
        return TemplateGatePage(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    def aggregate_counts(
        self,
        role: UserRole,
        *,
        search: str | None = None,
        statuses: set[str] | frozenset[str] | None = None,
    ) -> TemplateAggregateCounts:
        visible_ids = self.visible_versions_statement(role, search=search, statuses=statuses).with_only_columns(
            V2TemplateVersion.id
        ).subquery()

        def count(model: Any, version_column: Any) -> int:
            return int(
                self.session.scalar(
                    select(func.count()).select_from(model).where(version_column.in_(select(visible_ids.c.id)))
                )
                or 0
            )

        exact_mapping_count = int(
            self.session.scalar(
                select(func.count())
                .select_from(V2TemplateExternalGateTask)
                .join(V2TemplateExternalGate, V2TemplateExternalGate.id == V2TemplateExternalGateTask.gate_id)
                .where(V2TemplateExternalGate.template_version_id.in_(select(visible_ids.c.id)))
            )
            or 0
        )
        broad_text_gate_count = int(
            self.session.scalar(
                select(func.count())
                .select_from(V2TemplateExternalGate)
                .where(
                    V2TemplateExternalGate.template_version_id.in_(select(visible_ids.c.id)),
                    V2TemplateExternalGate.mapping_classification == "broad_text",
                )
            )
            or 0
        )
        return TemplateAggregateCounts(
            version_count=int(self.session.scalar(select(func.count()).select_from(visible_ids)) or 0),
            task_count=count(V2TemplateTask, V2TemplateTask.template_version_id),
            dependency_count=count(V2TemplateTaskDependency, V2TemplateTaskDependency.template_version_id),
            gate_count=count(V2TemplateExternalGate, V2TemplateExternalGate.template_version_id),
            exact_mapping_count=exact_mapping_count,
            broad_text_gate_count=broad_text_gate_count,
        )

    def visible_version_ids(
        self,
        role: UserRole,
        *,
        search: str | None = None,
        statuses: Iterable[str] | None = None,
    ) -> Select:
        requested = set(statuses) if statuses is not None else None
        return self.visible_versions_statement(role, search=search, statuses=requested).with_only_columns(
            V2TemplateVersion.id
        )
