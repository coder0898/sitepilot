from __future__ import annotations

import re
import unittest
from pathlib import Path

from sqlalchemy import CheckConstraint

from app import model_registry  # noqa: F401
from app.database import Base


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = REPO_ROOT / "supabase" / "migrations" / "20260725083225_v2_template_schema.sql"
TASK_DURATION_MIGRATION = REPO_ROOT / "supabase" / "migrations" / "202607280001_v2_template_configured_duration_tasks.sql"
TABLE_NAMES = {
    "v2_templates",
    "v2_template_versions",
    "v2_template_tasks",
    "v2_template_task_dependencies",
    "v2_template_external_gates",
    "v2_template_external_gate_tasks",
}


class V2TemplateSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = MIGRATION.read_text(encoding="utf-8")
        cls.task_duration_sql = TASK_DURATION_MIGRATION.read_text(encoding="utf-8")

    def test_sql_and_sqlalchemy_table_names_match(self) -> None:
        sql_tables = set(re.findall(r"create table if not exists siteops_v2\.(v2_[a-z_]+)", self.sql))
        model_tables = {
            table.name
            for table in Base.metadata.tables.values()
            if table.schema == "siteops_v2" and table.name.startswith("v2_template")
        }
        self.assertEqual(TABLE_NAMES, sql_tables)
        self.assertEqual(TABLE_NAMES, model_tables)

    def test_important_check_values_match(self) -> None:
        expected_groups = [
            {"draft", "published", "archived"},
            {"pre_activation", "execution"},
            {"mandatory", "conditional"},
            {"finish_to_start", "start_to_start"},
            {"exact", "broad_text", "unmapped"},
        ]
        model_check_sql = "\n".join(
            str(constraint.sqltext)
            for table in Base.metadata.tables.values()
            if table.schema == "siteops_v2"
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        )
        for values in expected_groups:
            for value in values:
                self.assertIn(f"'{value}'", self.sql)
                self.assertIn(f"'{value}'", model_check_sql)

    def test_configured_duration_constraint_is_owned_by_service(self) -> None:
        self.assertIn(
            "drop constraint if exists ck_v2_template_tasks_schedule_days",
            self.task_duration_sql.lower(),
        )
        self.assertNotIn("between 1 and 45", self.task_duration_sql.lower())
        self.assertIn("planned_start_day >= 1", self.task_duration_sql)
        task_table = Base.metadata.tables["siteops_v2.v2_template_tasks"]
        schedule_checks = [
            str(constraint.sqltext)
            for constraint in task_table.constraints
            if isinstance(constraint, CheckConstraint)
            and constraint.name == "ck_v2_template_tasks_schedule_days"
        ]
        self.assertEqual(len(schedule_checks), 1)
        self.assertNotIn("between 1 and 45", schedule_checks[0])
        self.assertIn("planned_start_day >= 1", schedule_checks[0])

    def test_primary_relationships_are_correct(self) -> None:
        expected_foreign_keys = {
            "siteops_v2.v2_template_versions": {"siteops_v2.v2_templates.id"},
            "siteops_v2.v2_template_tasks": {"siteops_v2.v2_template_versions.id"},
            "siteops_v2.v2_template_task_dependencies": {
                "siteops_v2.v2_template_versions.id",
                "siteops_v2.v2_template_tasks.id",
            },
            "siteops_v2.v2_template_external_gates": {"siteops_v2.v2_template_versions.id"},
            "siteops_v2.v2_template_external_gate_tasks": {
                "siteops_v2.v2_template_external_gates.id",
                "siteops_v2.v2_template_tasks.id",
            },
        }
        for table_key, expected_targets in expected_foreign_keys.items():
            table = Base.metadata.tables[table_key]
            actual_targets = {fk.target_fullname for fk in table.foreign_keys}
            self.assertTrue(expected_targets.issubset(actual_targets))

    def test_no_new_alembic_migration_for_template_schema(self) -> None:
        alembic_files = list((REPO_ROOT / "backend" / "alembic" / "versions").glob("*.py"))
        self.assertFalse(any("template_schema" in path.name for path in alembic_files))

    def test_migration_does_not_modify_legacy_tables(self) -> None:
        self.assertNotRegex(self.sql, r"(?i)alter\s+table\s+public\.")
        self.assertNotRegex(self.sql, r"(?i)(create|alter|drop)\s+table\s+(task_templates|execution_templates|execution_template_tasks)\b")


if __name__ == "__main__":
    unittest.main()
