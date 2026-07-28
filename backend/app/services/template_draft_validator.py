"""Authoritative, deterministic and read-only validation of template versions."""
from __future__ import annotations

import uuid
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import User
from app.repositories.template_validation_repository import TemplateValidationAggregate, TemplateValidationRepository
from app.services.template_mutation_access import concurrency_token, require_template_mutation_access, stable_template_version_not_found
from app.template_validation_schemas import (
    TemplateValidationEntityCounts,
    TemplateValidationIssue,
    TemplateValidationResponse,
    TemplateValidationSeverityCounts,
)

SUPPORTED_TYPES = {"finish_to_start", "start_to_start"}
SUPPORTED_APPLICABILITY = {"mandatory", "conditional"}
SUPPORTED_SCHEDULE = {"pre_activation", "execution"}
SUPPORTED_GATE_CLASSIFICATION = {"exact", "broad_text", "unmapped"}


def _blank(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip()


def _issue(issues: list[TemplateValidationIssue], code: str, group: str, entity_type: str,
           path: str, message: str, *, blocking: bool = True, entity_id: Any = None, **details: Any) -> None:
    issues.append(TemplateValidationIssue(
        code=code,
        severity="error" if blocking else "warning",
        blocking=blocking,
        group=group,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        path=path,
        message=message,
        details=details,
    ))


def validate_aggregate(a: TemplateValidationAggregate, *, validated_at: datetime | None = None) -> TemplateValidationResponse:
    issues: list[TemplateValidationIssue] = []
    t, v = a.template, a.version

    if _blank(t.code): _issue(issues, "template_code_required", "metadata", "template", "template.code", "Template code is required.", entity_id=t.id)
    if _blank(t.name): _issue(issues, "template_name_required", "metadata", "template", "template.name", "Template name is required.", entity_id=t.id)
    if not isinstance(v.version_no, int) or v.version_no <= 0: _issue(issues, "version_number_invalid", "metadata", "version", "version.version_no", "Version number must be positive.", entity_id=v.id)
    if not isinstance(v.duration_days, int) or v.duration_days <= 0: _issue(issues, "version_duration_invalid", "metadata", "version", "version.duration_days", "Version duration must be positive.", entity_id=v.id)
    if v.status not in {"draft", "published", "archived"}: _issue(issues, "version_status_invalid", "metadata", "version", "version.status", "Version status is unsupported.", entity_id=v.id)

    if not a.tasks:
        _issue(issues, "template_requires_task", "tasks", "version", "tasks", "A template version must contain at least one task.", entity_id=v.id)

    task_ids = {x.id for x in a.tasks}
    code_counts = Counter(x.code.strip().upper() if isinstance(x.code, str) else x.code for x in a.tasks)
    seq_counts = Counter(x.sequence_no for x in a.tasks)
    for task in a.tasks:
        p = f"tasks.{task.id}"
        if _blank(task.code): _issue(issues, "task_code_required", "tasks", "task", f"{p}.code", "Task code is required.", entity_id=task.id)
        if code_counts[task.code.strip().upper() if isinstance(task.code, str) else task.code] > 1: _issue(issues, "task_code_duplicate", "tasks", "task", f"{p}.code", "Task code must be unique within the version.", entity_id=task.id, value=task.code)
        if not isinstance(task.sequence_no, int) or task.sequence_no <= 0: _issue(issues, "task_sequence_invalid", "tasks", "task", f"{p}.sequence_no", "Task sequence must be positive.", entity_id=task.id)
        if seq_counts[task.sequence_no] > 1: _issue(issues, "task_sequence_duplicate", "tasks", "task", f"{p}.sequence_no", "Task sequence must be unique within the version.", entity_id=task.id, value=task.sequence_no)
        if _blank(task.title): _issue(issues, "task_title_required", "tasks", "task", f"{p}.title", "Task title is required.", entity_id=task.id)
        if task.applicability not in SUPPORTED_APPLICABILITY: _issue(issues, "task_applicability_invalid", "tasks", "task", f"{p}.applicability", "Task applicability is unsupported.", entity_id=task.id, value=task.applicability)
        if task.schedule_classification not in SUPPORTED_SCHEDULE:
            _issue(issues, "task_schedule_classification_invalid", "tasks", "task", f"{p}.schedule_classification", "Task schedule classification is unsupported.", entity_id=task.id)
        elif task.schedule_classification == "pre_activation":
            if task.planned_start_day is not None or task.planned_end_day is not None:
                _issue(issues, "pre_activation_task_has_days", "tasks", "task", p, "Pre-activation tasks cannot have planned execution days.", entity_id=task.id)
        else:
            if not isinstance(task.planned_start_day, int) or not isinstance(task.planned_end_day, int) or not (1 <= task.planned_start_day <= task.planned_end_day):
                _issue(issues, "task_schedule_invalid", "tasks", "task", p, "Execution task schedule must satisfy 1 <= start <= end.", entity_id=task.id)
            elif task.planned_end_day > v.duration_days:
                _issue(issues, "task_exceeds_version_duration", "schedule", "task", f"{p}.planned_end_day", "Task schedule exceeds the version duration.", entity_id=task.id, planned_end_day=task.planned_end_day, duration_days=v.duration_days)
        if task.duration_days is not None and task.duration_days <= 0:
            _issue(issues, "task_duration_invalid", "tasks", "task", f"{p}.duration_days", "Task duration must be positive.", entity_id=task.id)

    dep_keys = Counter((d.predecessor_task_id, d.successor_task_id, d.dependency_type) for d in a.dependencies)
    graph: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    indegree = {task_id: 0 for task_id in task_ids}
    for dep in a.dependencies:
        p = f"dependencies.{dep.id}"
        if dep.predecessor_task_id not in task_ids or dep.successor_task_id not in task_ids:
            _issue(issues, "dependency_task_reference_invalid", "dependencies", "dependency", p, "Dependency tasks must belong to this version.", entity_id=dep.id)
            continue
        if dep.predecessor_task_id == dep.successor_task_id: _issue(issues, "dependency_self_reference", "dependencies", "dependency", p, "A task cannot depend on itself.", entity_id=dep.id)
        if dep.dependency_type not in SUPPORTED_TYPES: _issue(issues, "dependency_type_unsupported", "dependencies", "dependency", f"{p}.dependency_type", "Dependency type is unsupported.", entity_id=dep.id, value=dep.dependency_type)
        if dep_keys[(dep.predecessor_task_id, dep.successor_task_id, dep.dependency_type)] > 1: _issue(issues, "dependency_duplicate", "dependencies", "dependency", p, "Duplicate dependency relationship.", entity_id=dep.id)
        if dep.predecessor_task_id != dep.successor_task_id and dep.successor_task_id not in graph[dep.predecessor_task_id]:
            graph[dep.predecessor_task_id].add(dep.successor_task_id); indegree[dep.successor_task_id] += 1
    queue = deque(sorted((x for x,d in indegree.items() if d == 0), key=str)); visited = 0
    while queue:
        node=queue.popleft(); visited += 1
        for nxt in sorted(graph[node], key=str):
            indegree[nxt]-=1
            if indegree[nxt]==0: queue.append(nxt)
    if visited != len(indegree):
        _issue(issues, "dependency_cycle", "dependencies", "version", "dependencies", "Dependency graph must remain acyclic.", entity_id=v.id, involved_task_ids=sorted(str(x) for x,d in indegree.items() if d>0))

    gate_ids = {g.id for g in a.gates}
    gate_code_counts = Counter(g.code.strip().upper() if isinstance(g.code, str) else g.code for g in a.gates)
    gate_seq_counts = Counter(g.sequence_no for g in a.gates)
    links_by_gate: dict[Any, list[Any]] = defaultdict(list)
    link_pairs = Counter((m.gate_id, m.template_task_id) for m in a.mappings)
    for m in a.mappings: links_by_gate[m.gate_id].append(m)
    for gate in a.gates:
        p=f"gates.{gate.id}"; links=links_by_gate[gate.id]
        if _blank(gate.code): _issue(issues, "gate_code_required", "gates", "gate", f"{p}.code", "Gate code is required.", entity_id=gate.id)
        if gate_code_counts[gate.code.strip().upper() if isinstance(gate.code,str) else gate.code] > 1: _issue(issues, "gate_code_duplicate", "gates", "gate", f"{p}.code", "Gate code must be unique within the version.", entity_id=gate.id)
        if _blank(gate.approval_name): _issue(issues, "gate_name_required", "gates", "gate", f"{p}.approval_name", "Gate approval name is required.", entity_id=gate.id)
        if not isinstance(gate.sequence_no,int) or gate.sequence_no<=0: _issue(issues, "gate_sequence_invalid", "gates", "gate", f"{p}.sequence_no", "Gate sequence must be positive.", entity_id=gate.id)
        if gate_seq_counts[gate.sequence_no] > 1: _issue(issues, "gate_sequence_duplicate", "gates", "gate", f"{p}.sequence_no", "Gate sequence must be unique within the version.", entity_id=gate.id)
        if gate.mapping_classification not in SUPPORTED_GATE_CLASSIFICATION:
            _issue(issues, "gate_classification_invalid", "gates", "gate", f"{p}.mapping_classification", "Gate mapping classification is unsupported.", entity_id=gate.id); continue
        if gate.mapping_classification == "exact":
            if gate.requires_configuration: _issue(issues, "exact_gate_configuration_flag_invalid", "gates", "gate", f"{p}.requires_configuration", "Exact gates cannot remain configuration-required.", entity_id=gate.id)
            if gate.broad_mapping_text is not None: _issue(issues, "exact_gate_has_broad_text", "gates", "gate", f"{p}.broad_mapping_text", "Exact gates cannot contain broad mapping text.", entity_id=gate.id)
            if not links: _issue(issues, "exact_gate_requires_mapping", "mappings", "gate", p, "Exact gates require at least one explicit task mapping.", entity_id=gate.id)
        elif gate.mapping_classification == "broad_text":
            if _blank(gate.broad_mapping_text): _issue(issues, "broad_gate_text_required", "gates", "gate", f"{p}.broad_mapping_text", "Broad gates must preserve original mapping text.", entity_id=gate.id)
            if links: _issue(issues, "broad_gate_has_exact_rows", "mappings", "gate", p, "Broad gates must not contain exact mapping rows.", entity_id=gate.id)
            if not gate.requires_configuration: _issue(issues, "broad_gate_configuration_flag_required", "gates", "gate", f"{p}.requires_configuration", "Broad gates must be marked configuration-required.", entity_id=gate.id)
            _issue(issues, "broad_gate_requires_configuration", "gates", "gate", p, "Broad mapping remains textual and requires project-level configuration.", blocking=False, entity_id=gate.id)
        else:
            if gate.broad_mapping_text is not None or links: _issue(issues, "unmapped_gate_contains_mapping", "mappings", "gate", p, "Unmapped gates cannot contain mapping text or exact rows.", entity_id=gate.id)
            if not gate.requires_configuration: _issue(issues, "unmapped_gate_configuration_flag_required", "gates", "gate", f"{p}.requires_configuration", "Unmapped gates must be marked configuration-required.", entity_id=gate.id)
            _issue(issues, "unmapped_gate_requires_configuration", "gates", "gate", p, "Unmapped gate requires project-level configuration.", blocking=False, entity_id=gate.id)
    for m in a.mappings:
        p=f"mappings.{m.id}"
        if m.gate_id not in gate_ids: _issue(issues, "mapping_gate_reference_invalid", "mappings", "mapping", p, "Mapping gate must belong to this version.", entity_id=m.id)
        if m.template_task_id not in task_ids: _issue(issues, "mapping_task_reference_invalid", "mappings", "mapping", p, "Mapped task must belong to this version.", entity_id=m.id)
        if link_pairs[(m.gate_id,m.template_task_id)] > 1: _issue(issues, "mapping_duplicate", "mappings", "mapping", p, "Duplicate exact gate-task mapping.", entity_id=m.id)

    issues.sort(key=lambda x: (0 if x.blocking else 1, x.group, x.code, x.path, x.entity_id or ""))
    errors=sum(i.severity=="error" for i in issues); warnings=sum(i.severity=="warning" for i in issues)
    return TemplateValidationResponse(
        version_id=str(v.id), version_status=v.status, draft_revision=concurrency_token(v),
        validated_at=validated_at or datetime.now(timezone.utc),
        is_valid=errors==0, can_publish=errors==0,
        issues=issues,
        severity_counts=TemplateValidationSeverityCounts(errors=errors,warnings=warnings,blocking=sum(i.blocking for i in issues),non_blocking=sum(not i.blocking for i in issues)),
        entity_counts=TemplateValidationEntityCounts(tasks=len(a.tasks),dependencies=len(a.dependencies),gates=len(a.gates),exact_mappings=len(a.mappings)),
    )


class TemplateDraftValidationService:
    def __init__(self, db: Session): self.repo=TemplateValidationRepository(db)
    def validate(self, actor: User, version_id: uuid.UUID) -> TemplateValidationResponse:
        require_template_mutation_access(actor)
        aggregate=self.repo.load(version_id)
        if aggregate is None: raise stable_template_version_not_found()
        return validate_aggregate(aggregate)
