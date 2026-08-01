from __future__ import annotations

from copy import deepcopy

from app.services.template_fixture_validator import load_fixture_bundle, validate_template_fixtures


def fixture_bundle():
    return load_fixture_bundle()


def validate(bundle):
    return validate_template_fixtures(bundle["tasks"], bundle["dependencies"], bundle["gates"])


def codes(result):
    return {error.code for error in result.errors}


def test_valid_approved_fixture():
    result = validate(fixture_bundle())
    assert result.is_valid, result.to_dict()
    assert result.summary == {
        "task_count": 99,
        "dependency_count": 38,
        "external_gate_count": 32,
        "dependency_graph_acyclic": True,
        "exact_gate_count": 26,
        "broad_gate_count": 6,
    }


def test_missing_task():
    bundle = fixture_bundle(); bundle["tasks"]["tasks"].pop()
    result = validate(bundle)
    assert {"incorrect_count", "task_code_continuity"} <= codes(result)


def test_duplicate_task_code():
    bundle = fixture_bundle(); bundle["tasks"]["tasks"][1]["code"] = "T001"
    assert "duplicate_task_code" in codes(validate(bundle))


def test_duplicate_sequence():
    bundle = fixture_bundle(); bundle["tasks"]["tasks"][1]["sequence"] = 1
    assert "duplicate_task_sequence" in codes(validate(bundle))


def test_invalid_execution_day():
    bundle = fixture_bundle(); bundle["tasks"]["tasks"][7]["planned_start_day"] = 0
    assert "invalid_execution_day" in codes(validate(bundle))


def test_invalid_dependency_reference():
    bundle = fixture_bundle(); bundle["dependencies"]["dependencies"][0]["predecessor_task_code"] = "T999"
    assert "invalid_dependency_reference" in codes(validate(bundle))


def test_self_dependency():
    bundle = fixture_bundle(); dep = bundle["dependencies"]["dependencies"][0]; dep["successor_task_code"] = dep["predecessor_task_code"]
    assert "self_dependency" in codes(validate(bundle))


def test_duplicate_dependency():
    bundle = fixture_bundle(); bundle["dependencies"]["dependencies"][1] = deepcopy(bundle["dependencies"]["dependencies"][0])
    assert "duplicate_dependency" in codes(validate(bundle))


def test_dependency_cycle():
    bundle = fixture_bundle(); dep = bundle["dependencies"]["dependencies"][-1]; dep.update(predecessor_task_code="T010", successor_task_code="T001")
    assert "dependency_cycle" in codes(validate(bundle))


def test_unsupported_dependency_type():
    bundle = fixture_bundle(); bundle["dependencies"]["dependencies"][0]["dependency_type"] = "finish_to_finish"
    assert "unsupported_dependency_type" in codes(validate(bundle))


def test_exact_gate_mapping_to_missing_task():
    bundle = fixture_bundle(); bundle["gates"]["external_gates"][0]["task_codes"] = ["T999"]
    assert "invalid_gate_task_reference" in codes(validate(bundle))


def test_broad_gate_with_exact_mappings():
    bundle = fixture_bundle(); bundle["gates"]["external_gates"][4]["task_codes"] = ["T003"]
    result = validate(bundle)
    assert {"broad_gate_has_exact_mappings", "broad_gate_not_preserved"} <= codes(result)


def test_incorrect_counts():
    bundle = fixture_bundle(); bundle["dependencies"]["dependencies"].pop(); bundle["gates"]["external_gates"].pop()
    count_errors = [error for error in validate(bundle).errors if error.code == "incorrect_count"]
    assert len(count_errors) == 2
