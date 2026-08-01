"""Deterministic validation for authoritative V2 template fixtures."""
from __future__ import annotations

import json
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

EXPECTED_TASK_COUNT = 99
EXPECTED_DEPENDENCY_COUNT = 38
EXPECTED_GATE_COUNT = 32
SUPPORTED_DEPENDENCY_TYPES = {"finish_to_start", "start_to_start"}
BROAD_GATE_TEXT = {
    "E005": "Relevant procurement and finish tasks",
    "E006": "T008 onwards",
    "E008": "Affected activities",
    "E009": "Material delivery tasks",
    "E011": "Relevant welding/cutting tasks",
    "E026": "External signage task",
}
DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "v2_templates"


@dataclass(frozen=True)
class ValidationError:
    code: str
    message: str
    path: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationResult:
    errors: list[ValidationError]
    summary: dict[str, Any]

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": [error.to_dict() for error in self.errors],
            "summary": self.summary,
        }


def load_fixture_bundle(fixture_dir: Path | str = DEFAULT_FIXTURE_DIR) -> dict[str, Any]:
    base = Path(fixture_dir)
    paths = {
        "tasks": base / "workved_45_day_template.json",
        "dependencies": base / "workved_45_day_dependencies.json",
        "gates": base / "workved_45_day_external_gates.json",
    }
    return {name: json.loads(path.read_text(encoding="utf-8")) for name, path in paths.items()}


def _items(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get(key), list):
        return payload[key]
    return []


def _duplicates(values: Iterable[Any]) -> list[Any]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def _error(errors: list[ValidationError], code: str, message: str, path: str, **details: Any) -> None:
    errors.append(ValidationError(code=code, message=message, path=path, details=details))


def _validate_cycle(dependencies: list[dict[str, Any]], task_codes: set[str]) -> list[str] | None:
    graph: dict[str, set[str]] = defaultdict(set)
    indegree = {code: 0 for code in task_codes}
    for dep in dependencies:
        predecessor = dep.get("predecessor_task_code")
        successor = dep.get("successor_task_code")
        if predecessor not in task_codes or successor not in task_codes or predecessor == successor:
            continue
        if successor not in graph[predecessor]:
            graph[predecessor].add(successor)
            indegree[successor] += 1
    queue = deque(sorted(code for code, degree in indegree.items() if degree == 0))
    visited = 0
    while queue:
        node = queue.popleft()
        visited += 1
        for successor in sorted(graph[node]):
            indegree[successor] -= 1
            if indegree[successor] == 0:
                queue.append(successor)
    if visited == len(indegree):
        return None
    return sorted(code for code, degree in indegree.items() if degree > 0)


def validate_template_fixtures(task_payload: Any, dependency_payload: Any, gate_payload: Any) -> ValidationResult:
    tasks = _items(task_payload, "tasks")
    dependencies = _items(dependency_payload, "dependencies")
    gates = _items(gate_payload, "external_gates")
    errors: list[ValidationError] = []

    for name, actual, expected in (
        ("tasks", len(tasks), EXPECTED_TASK_COUNT),
        ("dependencies", len(dependencies), EXPECTED_DEPENDENCY_COUNT),
        ("external_gates", len(gates), EXPECTED_GATE_COUNT),
    ):
        if actual != expected:
            _error(errors, "incorrect_count", f"Expected exactly {expected} {name}; found {actual}.", name, expected=expected, actual=actual)

    task_codes = [task.get("code") for task in tasks]
    sequences = [task.get("sequence") for task in tasks]
    for duplicate in _duplicates(task_codes):
        _error(errors, "duplicate_task_code", f"Duplicate task code: {duplicate}.", "tasks", value=duplicate)
    for duplicate in _duplicates(sequences):
        _error(errors, "duplicate_task_sequence", f"Duplicate task sequence: {duplicate}.", "tasks", value=duplicate)

    expected_codes = [f"T{i:03d}" for i in range(1, EXPECTED_TASK_COUNT + 1)]
    if sorted(code for code in task_codes if isinstance(code, str)) != expected_codes:
        missing = sorted(set(expected_codes) - set(task_codes))
        unexpected = sorted(set(task_codes) - set(expected_codes))
        _error(errors, "task_code_continuity", "Task codes must be continuous from T001 through T099.", "tasks", missing=missing, unexpected=unexpected)

    by_code = {task.get("code"): task for task in tasks if isinstance(task.get("code"), str)}
    for index, task in enumerate(tasks):
        path = f"tasks[{index}]"
        classification = task.get("schedule_classification")
        start = task.get("planned_start_day")
        end = task.get("planned_end_day")
        if classification == "pre_activation":
            if start is not None or end is not None:
                _error(errors, "invalid_pre_activation_day", "Pre-Activation tasks must have null planned days.", path, start=start, end=end)
        elif classification == "execution":
            if not isinstance(start, int) or not isinstance(end, int) or not (1 <= start <= end <= 45):
                _error(errors, "invalid_execution_day", "Execution task days must satisfy 1 <= start <= end <= 45.", path, start=start, end=end)
        else:
            _error(errors, "invalid_schedule_classification", "Unsupported schedule classification.", path, value=classification)

    for code in expected_codes[:7]:
        task = by_code.get(code)
        if task and (task.get("schedule_classification") != "pre_activation" or task.get("phase") != "Pre-Activation"):
            _error(errors, "invalid_pre_activation_task", f"{code} must be Pre-Activation.", f"tasks.{code}")
    t008 = by_code.get("T008")
    if t008 and (t008.get("schedule_classification") != "execution" or t008.get("planned_start_day") != 1):
        _error(errors, "invalid_first_execution_task", "T008 must be the first Day 1 execution task.", "tasks.T008")
    earlier_execution = [t.get("code") for t in tasks if (t.get("sequence") or 0) < 8 and t.get("schedule_classification") == "execution"]
    if earlier_execution:
        _error(errors, "invalid_first_execution_task", "No task before T008 may be an execution task.", "tasks", codes=earlier_execution)
    for code in ("T097", "T098", "T099"):
        task = by_code.get(code)
        if task and (task.get("planned_start_day"), task.get("planned_end_day")) != (45, 45):
            _error(errors, "invalid_day_45_task", f"{code} must be scheduled on Day 45.", f"tasks.{code}")
    if by_code.get("T098") and by_code["T098"].get("applicability") != "conditional":
        _error(errors, "invalid_t098_applicability", "T098 must be conditional.", "tasks.T098")

    code_set = set(code for code in task_codes if isinstance(code, str))
    relation_keys: list[tuple[Any, Any, Any]] = []
    for index, dep in enumerate(dependencies):
        path = f"dependencies[{index}]"
        predecessor = dep.get("predecessor_task_code")
        successor = dep.get("successor_task_code")
        dep_type = dep.get("dependency_type")
        if predecessor not in code_set or successor not in code_set:
            _error(errors, "invalid_dependency_reference", "Dependency references an unknown task code.", path, predecessor=predecessor, successor=successor)
        if predecessor == successor:
            _error(errors, "self_dependency", "A task cannot depend on itself.", path, task_code=predecessor)
        if dep_type not in SUPPORTED_DEPENDENCY_TYPES:
            _error(errors, "unsupported_dependency_type", "Unsupported dependency type.", path, value=dep_type)
        relation_keys.append((predecessor, successor, dep_type))
    for duplicate in _duplicates(relation_keys):
        _error(errors, "duplicate_dependency", "Duplicate dependency relationship.", "dependencies", relationship=list(duplicate))
    cycle_nodes = _validate_cycle(dependencies, code_set)
    if cycle_nodes:
        _error(errors, "dependency_cycle", "Dependency graph must be acyclic.", "dependencies", involved_task_codes=cycle_nodes)

    gate_codes = [gate.get("code") for gate in gates]
    for duplicate in _duplicates(gate_codes):
        _error(errors, "duplicate_gate_code", f"Duplicate gate code: {duplicate}.", "external_gates", value=duplicate)
    for index, gate in enumerate(gates):
        path = f"external_gates[{index}]"
        classification = gate.get("mapping_classification")
        mapped_codes = gate.get("task_codes") or []
        code = gate.get("code")
        if classification == "exact":
            for task_code in mapped_codes:
                if task_code not in code_set:
                    _error(errors, "invalid_gate_task_reference", "Exact gate mapping references an unknown task.", path, gate_code=code, task_code=task_code)
        elif classification == "broad_text":
            if mapped_codes:
                _error(errors, "broad_gate_has_exact_mappings", "Broad-text gates must not contain exact task mappings.", path, gate_code=code, task_codes=mapped_codes)
            if not gate.get("broad_mapping_text"):
                _error(errors, "missing_broad_mapping_text", "Broad-text gates must preserve the original mapping text.", path, gate_code=code)
        elif classification != "unmapped":
            _error(errors, "invalid_mapping_classification", "Unsupported gate mapping classification.", path, value=classification)
    gate_by_code = {gate.get("code"): gate for gate in gates}
    for code, text in BROAD_GATE_TEXT.items():
        gate = gate_by_code.get(code)
        if gate and (gate.get("mapping_classification") != "broad_text" or gate.get("broad_mapping_text") != text or gate.get("task_codes") or gate.get("requires_configuration") is not True):
            _error(errors, "broad_gate_not_preserved", f"{code} must remain an unresolved broad-text mapping.", f"external_gates.{code}", expected_text=text)

    summary = {
        "task_count": len(tasks),
        "dependency_count": len(dependencies),
        "external_gate_count": len(gates),
        "dependency_graph_acyclic": cycle_nodes is None,
        "exact_gate_count": sum(g.get("mapping_classification") == "exact" for g in gates),
        "broad_gate_count": sum(g.get("mapping_classification") == "broad_text" for g in gates),
    }
    return ValidationResult(errors=errors, summary=summary)


def validate_fixture_directory(fixture_dir: Path | str = DEFAULT_FIXTURE_DIR) -> ValidationResult:
    bundle = load_fixture_bundle(fixture_dir)
    return validate_template_fixtures(bundle["tasks"], bundle["dependencies"], bundle["gates"])
