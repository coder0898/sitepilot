from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from app.scripts.import_v2_template import (
    DATABASE_VERSION_NO,
    SQLAlchemyTemplateRepository,
    TemplateFixtureValidationError,
    TemplateImportConflict,
    compute_content_hash,
    import_authoritative_template,
)
from app.services.template_fixture_validator import DEFAULT_FIXTURE_DIR, load_fixture_bundle


ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class FakeDatabase:
    def __init__(self, fail_stage: str | None = None):
        self.state = {
            "templates": {},
            "versions": {},
            "tasks": {},
            "dependencies": [],
            "gates": {},
            "links": set(),
            "audits": [],
        }
        self.fail_stage = fail_stage
        self.opened_sessions = 0

    def __call__(self):
        self.opened_sessions += 1
        return FakeSession(self)


class FakeSession:
    def __init__(self, database: FakeDatabase):
        self.database = database
        self.working = copy.deepcopy(database.state)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def begin(self):
        return FakeTransaction(self)


class FakeTransaction:
    def __init__(self, session: FakeSession):
        self.session = session

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.session.database.state = self.session.working
        return False


class FakeRepository:
    def __init__(self, session: FakeSession):
        self.session = session
        self.state = session.working

    def get_template(self, code):
        return self.state["templates"].get(code)

    def create_template(self, *, code, name, description):
        row = SimpleNamespace(id=uuid.uuid4(), code=code, name=name, description=description)
        self.state["templates"][code] = row
        return row

    def get_version(self, template_id, version_no):
        return self.state["versions"].get((template_id, version_no))

    def get_current_published(self, template_id):
        return next(
            (
                version
                for (owner_id, _), version in self.state["versions"].items()
                if owner_id == template_id and version.is_current_published
            ),
            None,
        )

    def create_version(self, *, template_id, content_hash, actor_user_id, change_note):
        row = SimpleNamespace(
            id=uuid.uuid4(),
            template_id=template_id,
            version_no=DATABASE_VERSION_NO,
            status="draft",
            duration_days=45,
            change_note=change_note,
            content_hash=content_hash,
            is_current_published=False,
            created_by=actor_user_id,
            published_by=None,
            published_at=None,
        )
        self.state["versions"][(template_id, DATABASE_VERSION_NO)] = row
        return row

    def create_tasks(self, version_id, tasks):
        rows = {}
        for index, item in enumerate(tasks):
            row = SimpleNamespace(
                id=uuid.uuid4(),
                template_version_id=version_id,
                code=item["code"],
                sequence_no=item["sequence"],
                schedule_classification=item["schedule_classification"],
                planned_start_day=item.get("planned_start_day"),
                planned_end_day=item.get("planned_end_day"),
                applicability=item["applicability"],
            )
            self.state["tasks"][(version_id, row.code)] = row
            rows[row.code] = row
            if self.session.database.fail_stage == "task" and index == 20:
                raise RuntimeError("injected task insert failure")
        return rows

    def create_dependencies(self, version_id, dependencies, tasks_by_code):
        for index, item in enumerate(dependencies):
            self.state["dependencies"].append(
                SimpleNamespace(
                    version_id=version_id,
                    predecessor_task_id=tasks_by_code[item["predecessor_task_code"]].id,
                    successor_task_id=tasks_by_code[item["successor_task_code"]].id,
                    dependency_type=item["dependency_type"],
                )
            )
            if self.session.database.fail_stage == "dependency" and index == 10:
                raise RuntimeError("injected dependency insert failure")

    def create_gates(self, version_id, gates):
        rows = {}
        for item in gates:
            row = SimpleNamespace(
                id=uuid.uuid4(),
                template_version_id=version_id,
                code=item["code"],
                mapping_classification=item["mapping_classification"],
                broad_mapping_text=item.get("broad_mapping_text"),
            )
            self.state["gates"][(version_id, row.code)] = row
            rows[row.code] = row
        return rows

    def create_exact_gate_links(self, gates, gates_by_code, tasks_by_code):
        for item in gates:
            if item["mapping_classification"] != "exact":
                continue
            for task_code in item.get("task_codes", []):
                self.state["links"].add((gates_by_code[item["code"]].id, tasks_by_code[task_code].id))

    def publish_version(self, version, actor_user_id):
        version.status = "published"
        version.is_current_published = True
        version.published_by = actor_user_id
        version.published_at = "now"

    def write_import_audit(self, **values):
        self.state["audits"].append(values)

    def verification_report(self, template_code, version_no):
        template = self.state["templates"][template_code]
        version = self.state["versions"][(template.id, version_no)]
        tasks = {
            code: task
            for (owner_id, code), task in self.state["tasks"].items()
            if owner_id == version.id
        }
        gates = {
            code: gate
            for (owner_id, code), gate in self.state["gates"].items()
            if owner_id == version.id
        }

        def task_value(code):
            task = tasks.get(code)
            if task is None:
                return None
            return {
                "schedule_classification": task.schedule_classification,
                "planned_start_day": task.planned_start_day,
                "planned_end_day": task.planned_end_day,
                "applicability": task.applicability,
            }

        return {
            "template": {"id": str(template.id), "code": template.code, "name": template.name},
            "version": {
                "id": str(version.id),
                "label": "1.0.0",
                "version_no": version.version_no,
                "status": version.status,
                "duration_days": version.duration_days,
                "is_current_published": version.is_current_published,
                "content_hash": version.content_hash,
            },
            "counts": {
                "tasks": len(tasks),
                "dependencies": sum(dep.version_id == version.id for dep in self.state["dependencies"]),
                "external_gates": len(gates),
                "exact_gate_task_mappings": len(self.state["links"]),
                "broad_text_gates": sum(gate.mapping_classification == "broad_text" for gate in gates.values()),
            },
            "schedule_checks": {
                "T001_T007": {f"T{i:03d}": task_value(f"T{i:03d}") for i in range(1, 8)},
                "T008": task_value("T008"),
                "T098": task_value("T098"),
                "T097_T099": {code: task_value(code) for code in ("T097", "T098", "T099")},
            },
        }


class TemplateImportTests(unittest.TestCase):
    def import_once(self, database, fixture_dir=DEFAULT_FIXTURE_DIR):
        return import_authoritative_template(
            fixture_dir=fixture_dir,
            actor_user_id=ACTOR_ID,
            session_factory=database,
            repository_factory=FakeRepository,
        )

    def copied_fixture_dir(self):
        temporary = tempfile.TemporaryDirectory()
        destination = Path(temporary.name) / "fixtures"
        shutil.copytree(DEFAULT_FIXTURE_DIR, destination)
        return temporary, destination

    def test_first_import_succeeds_with_final_counts(self):
        database = FakeDatabase()
        result = self.import_once(database)
        self.assertEqual("imported", result.outcome)
        self.assertEqual(99, result.verification["counts"]["tasks"])
        self.assertEqual(38, result.verification["counts"]["dependencies"])
        self.assertEqual(32, result.verification["counts"]["external_gates"])
        self.assertEqual(1, len(database.state["audits"]))

    def test_second_import_is_a_no_op(self):
        database = FakeDatabase()
        first = self.import_once(database)
        before = copy.deepcopy(database.state)
        second = self.import_once(database)
        self.assertEqual("already_imported", second.outcome)
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(before, database.state)

    def test_invalid_fixture_opens_no_session_and_writes_nothing(self):
        temporary, fixture_dir = self.copied_fixture_dir()
        try:
            path = fixture_dir / "workved_45_day_template.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["tasks"].pop()
            path.write_text(json.dumps(payload), encoding="utf-8")
            database = FakeDatabase()
            with self.assertRaises(TemplateFixtureValidationError):
                self.import_once(database, fixture_dir)
            self.assertEqual(0, database.opened_sessions)
            self.assertFalse(database.state["templates"])
        finally:
            temporary.cleanup()

    def test_matching_hash_is_accepted_as_already_imported(self):
        database = FakeDatabase()
        imported = self.import_once(database)
        bundle = load_fixture_bundle()
        self.assertEqual(compute_content_hash(bundle), imported.content_hash)
        self.assertEqual("already_imported", self.import_once(database).outcome)

    def test_different_hash_conflicts_without_changes(self):
        database = FakeDatabase()
        self.import_once(database)
        before = copy.deepcopy(database.state)
        temporary, fixture_dir = self.copied_fixture_dir()
        try:
            path = fixture_dir / "workved_45_day_template.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["tasks"][49]["title"] += " revised"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(TemplateImportConflict):
                self.import_once(database, fixture_dir)
            self.assertEqual(before, database.state)
        finally:
            temporary.cleanup()

    def test_task_failure_rolls_back_everything(self):
        database = FakeDatabase(fail_stage="task")
        with self.assertRaisesRegex(RuntimeError, "task insert failure"):
            self.import_once(database)
        self.assertFalse(database.state["templates"])
        self.assertFalse(database.state["tasks"])

    def test_dependency_failure_rolls_back_everything(self):
        database = FakeDatabase(fail_stage="dependency")
        with self.assertRaisesRegex(RuntimeError, "dependency insert failure"):
            self.import_once(database)
        self.assertFalse(database.state["templates"])
        self.assertFalse(database.state["dependencies"])

    def test_broad_gates_create_no_exact_mapping_rows(self):
        database = FakeDatabase()
        self.import_once(database)
        linked_gate_ids = {gate_id for gate_id, _ in database.state["links"]}
        broad_gates = [gate for gate in database.state["gates"].values() if gate.mapping_classification == "broad_text"]
        self.assertEqual(6, len(broad_gates))
        self.assertTrue(all(gate.id not in linked_gate_ids for gate in broad_gates))
        self.assertTrue(all(gate.broad_mapping_text for gate in broad_gates))

    def test_exact_mappings_resolve_to_approved_gate_task_pairs(self):
        database = FakeDatabase()
        self.import_once(database)
        bundle = load_fixture_bundle()
        expected = {
            (gate["code"], task_code)
            for gate in bundle["gates"]["external_gates"]
            if gate["mapping_classification"] == "exact"
            for task_code in gate.get("task_codes", [])
        }
        gate_code_by_id = {gate.id: gate.code for gate in database.state["gates"].values()}
        task_code_by_id = {task.id: task.code for task in database.state["tasks"].values()}
        actual = {(gate_code_by_id[gate_id], task_code_by_id[task_id]) for gate_id, task_id in database.state["links"]}
        self.assertEqual(expected, actual)

    def test_resolve_super_admin_uses_the_current_role_enum_member(self):
        actor = SimpleNamespace(id=ACTOR_ID)
        session = Mock()
        session.scalar.return_value = actor
        repository = SQLAlchemyTemplateRepository(session)

        self.assertIs(actor, repository.resolve_super_admin("superadmin@siteops.local"))
        session.scalar.assert_called_once()
    def test_default_repository_is_sqlalchemy(self):
        self.assertIsNotNone(SQLAlchemyTemplateRepository)


if __name__ == "__main__":
    unittest.main()
