"""Import and verify the authoritative Workved V2 template fixtures.

Usage from the ``backend`` directory::

    python -m app.scripts.import_v2_template import \
        --created-by-email superadmin@example.com
    python -m app.scripts.import_v2_template verify

The fixture version ``1.0.0`` is stored as integer ``version_no = 1`` because
the approved F1 schema models template versions as positive integers.  The CLI
and reports retain ``1.0.0`` as the canonical product-facing label.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import model_registry  # noqa: F401 - register all FK targets
from app.database import SessionLocal
from app.models import User, UserRole
from app.project_models import V2AuditEvent
from app.services.template_fixture_validator import (
    DEFAULT_FIXTURE_DIR,
    load_fixture_bundle,
    validate_template_fixtures,
)
from app.template_models import (
    V2Template,
    V2TemplateExternalGate,
    V2TemplateExternalGateTask,
    V2TemplateTask,
    V2TemplateTaskDependency,
    V2TemplateVersion,
)


CANONICAL_VERSION = "1.0.0"
DATABASE_VERSION_NO = 1
EXPECTED_DURATION_DAYS = 45


class TemplateImportError(RuntimeError):
    """Base exception for a failed template import."""


class TemplateFixtureValidationError(TemplateImportError):
    """Raised before a database transaction when fixture validation fails."""


class TemplateImportConflict(TemplateImportError):
    """Raised when stable imported data conflicts with authoritative content."""


@dataclass(frozen=True)
class ImportResult:
    template_code: str
    version: str
    content_hash: str
    outcome: str
    verification: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fixture_items(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise TemplateFixtureValidationError(f"Fixture field '{key}' must be a list.")
    return value


def _validated_bundle(fixture_dir: Path | str) -> dict[str, Any]:
    bundle = load_fixture_bundle(fixture_dir)
    result = validate_template_fixtures(bundle["tasks"], bundle["dependencies"], bundle["gates"])

    identity_errors: list[str] = []
    task_fixture = bundle["tasks"]
    template_code = task_fixture.get("template_code")
    template_name = task_fixture.get("template_name")
    if not isinstance(template_code, str) or not template_code.strip():
        identity_errors.append("The task fixture requires a non-empty template_code.")
    if not isinstance(template_name, str) or not template_name.strip():
        identity_errors.append("The task fixture requires a non-empty template_name.")
    if task_fixture.get("version") != CANONICAL_VERSION:
        identity_errors.append(f"The authoritative fixture version must be {CANONICAL_VERSION}.")
    if task_fixture.get("duration_days") != EXPECTED_DURATION_DAYS:
        identity_errors.append(f"The authoritative duration must be {EXPECTED_DURATION_DAYS} days.")

    for fixture_name in ("dependencies", "gates"):
        fixture = bundle[fixture_name]
        if fixture.get("template_code") != template_code:
            identity_errors.append(f"{fixture_name} template_code does not match the task fixture.")
        if fixture.get("version") != CANONICAL_VERSION:
            identity_errors.append(f"{fixture_name} version must be {CANONICAL_VERSION}.")

    if not result.is_valid or identity_errors:
        payload = result.to_dict()
        payload["identity_errors"] = identity_errors
        raise TemplateFixtureValidationError(json.dumps(payload, indent=2, sort_keys=True))
    return bundle


def compute_content_hash(bundle: dict[str, Any]) -> str:
    """Return a deterministic hash of the semantic authoritative content."""
    task_fixture = bundle["tasks"]
    canonical = {
        "template_code": task_fixture["template_code"],
        "template_name": task_fixture["template_name"],
        "version": CANONICAL_VERSION,
        "duration_days": task_fixture["duration_days"],
        "tasks": _fixture_items(task_fixture, "tasks"),
        "dependencies": _fixture_items(bundle["dependencies"], "dependencies"),
        "external_gates": _fixture_items(bundle["gates"], "external_gates"),
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class SQLAlchemyTemplateRepository:
    """Database operations used by the transactional import workflow."""

    def __init__(self, session: Session):
        self.session = session

    def resolve_super_admin(self, email: str) -> User:
        actor = self.session.scalar(
            select(User).where(
                func.lower(User.email) == email.strip().lower(),
                User.active.is_(True),
                User.role == UserRole.super_admin,
            )
        )
        if actor is None:
            raise TemplateImportError(
                "A real, active Super Admin matching --created-by-email is required; no user was created."
            )
        return actor

    def get_template(self, code: str) -> V2Template | None:
        return self.session.scalar(select(V2Template).where(V2Template.code == code))

    def create_template(self, *, code: str, name: str, description: str | None) -> V2Template:
        template = V2Template(code=code, name=name, description=description)
        self.session.add(template)
        self.session.flush()
        return template

    def get_version(self, template_id: uuid.UUID, version_no: int) -> V2TemplateVersion | None:
        return self.session.scalar(
            select(V2TemplateVersion).where(
                V2TemplateVersion.template_id == template_id,
                V2TemplateVersion.version_no == version_no,
            )
        )

    def get_current_published(self, template_id: uuid.UUID) -> V2TemplateVersion | None:
        return self.session.scalar(
            select(V2TemplateVersion).where(
                V2TemplateVersion.template_id == template_id,
                V2TemplateVersion.is_current_published.is_(True),
            )
        )

    def create_version(
        self,
        *,
        template_id: uuid.UUID,
        content_hash: str,
        actor_user_id: uuid.UUID,
        change_note: str,
    ) -> V2TemplateVersion:
        version = V2TemplateVersion(
            template_id=template_id,
            version_no=DATABASE_VERSION_NO,
            status="draft",
            duration_days=EXPECTED_DURATION_DAYS,
            change_note=change_note,
            content_hash=content_hash,
            is_current_published=False,
            created_by=actor_user_id,
        )
        self.session.add(version)
        self.session.flush()
        return version

    def create_tasks(self, version_id: uuid.UUID, tasks: list[dict[str, Any]]) -> dict[str, V2TemplateTask]:
        rows = [
            V2TemplateTask(
                template_version_id=version_id,
                code=item["code"],
                sequence_no=item["sequence"],
                title=item["title"],
                description=item.get("description"),
                schedule_classification=item["schedule_classification"],
                planned_start_day=item.get("planned_start_day"),
                planned_end_day=item.get("planned_end_day"),
                phase=item.get("phase"),
                category=item.get("category"),
                applicability=item["applicability"],
                task_class=item.get("task_class"),
                task_kind=item.get("task_kind"),
                evidence_required=bool(item.get("evidence_required")),
                duration_days=item.get("duration_days"),
            )
            for item in tasks
        ]
        self.session.add_all(rows)
        self.session.flush()
        return {row.code: row for row in rows}

    def create_dependencies(
        self,
        version_id: uuid.UUID,
        dependencies: list[dict[str, Any]],
        tasks_by_code: dict[str, V2TemplateTask],
    ) -> None:
        self.session.add_all(
            [
                V2TemplateTaskDependency(
                    template_version_id=version_id,
                    predecessor_task_id=tasks_by_code[item["predecessor_task_code"]].id,
                    successor_task_id=tasks_by_code[item["successor_task_code"]].id,
                    dependency_type=item["dependency_type"],
                    blocking=bool(item.get("blocking", True)),
                    rule_text=item.get("rule_text"),
                    sequence_no=item["sequence"],
                )
                for item in dependencies
            ]
        )
        self.session.flush()

    def create_gates(
        self,
        version_id: uuid.UUID,
        gates: list[dict[str, Any]],
    ) -> dict[str, V2TemplateExternalGate]:
        rows = [
            V2TemplateExternalGate(
                template_version_id=version_id,
                code=item["code"],
                approval_name=item["approval_name"],
                description=item.get("description"),
                external_party=item.get("external_party"),
                required_by_type=item.get("required_by_type"),
                required_by_value=item.get("required_by_value"),
                impact=item.get("impact"),
                mapping_classification=item["mapping_classification"],
                broad_mapping_text=item.get("broad_mapping_text"),
                requires_configuration=bool(item.get("requires_configuration")),
                sequence_no=item["sequence"],
            )
            for item in gates
        ]
        self.session.add_all(rows)
        self.session.flush()
        return {row.code: row for row in rows}

    def create_exact_gate_links(
        self,
        gates: list[dict[str, Any]],
        gates_by_code: dict[str, V2TemplateExternalGate],
        tasks_by_code: dict[str, V2TemplateTask],
    ) -> None:
        links: list[V2TemplateExternalGateTask] = []
        for item in gates:
            if item["mapping_classification"] != "exact":
                continue
            gate = gates_by_code[item["code"]]
            links.extend(
                V2TemplateExternalGateTask(gate_id=gate.id, template_task_id=tasks_by_code[task_code].id)
                for task_code in item.get("task_codes", [])
            )
        self.session.add_all(links)
        self.session.flush()

    def publish_version(self, version: V2TemplateVersion, actor_user_id: uuid.UUID) -> None:
        version.status = "published"
        version.duration_days = EXPECTED_DURATION_DAYS
        version.is_current_published = True
        version.published_by = actor_user_id
        version.published_at = datetime.now(timezone.utc)
        self.session.flush()

    def write_import_audit(
        self,
        *,
        version: V2TemplateVersion,
        actor_user_id: uuid.UUID,
        content_hash: str,
        counts: dict[str, int],
    ) -> None:
        self.session.add(
            V2AuditEvent(
                actor_user_id=actor_user_id,
                action="template_version_imported",
                entity_type="template_version",
                entity_id=version.id,
                project_id=None,
                source="system",
                before_json=None,
                after_json={
                    "template_version": CANONICAL_VERSION,
                    "database_version_no": DATABASE_VERSION_NO,
                    "content_hash": content_hash,
                    **counts,
                },
                reason="Authoritative V2 template fixture import.",
            )
        )
        self.session.flush()

    def verification_report(self, template_code: str, version_no: int) -> dict[str, Any]:
        template = self.get_template(template_code)
        if template is None:
            raise TemplateImportError(f"Template '{template_code}' is not imported.")
        version = self.get_version(template.id, version_no)
        if version is None:
            raise TemplateImportError(f"Template '{template_code}' version {CANONICAL_VERSION} is not imported.")

        task_count = self.session.scalar(
            select(func.count()).select_from(V2TemplateTask).where(V2TemplateTask.template_version_id == version.id)
        ) or 0
        dependency_count = self.session.scalar(
            select(func.count()).select_from(V2TemplateTaskDependency).where(
                V2TemplateTaskDependency.template_version_id == version.id
            )
        ) or 0
        gate_count = self.session.scalar(
            select(func.count()).select_from(V2TemplateExternalGate).where(
                V2TemplateExternalGate.template_version_id == version.id
            )
        ) or 0
        broad_gate_count = self.session.scalar(
            select(func.count()).select_from(V2TemplateExternalGate).where(
                V2TemplateExternalGate.template_version_id == version.id,
                V2TemplateExternalGate.mapping_classification == "broad_text",
            )
        ) or 0
        exact_mapping_count = self.session.scalar(
            select(func.count())
            .select_from(V2TemplateExternalGateTask)
            .join(V2TemplateExternalGate, V2TemplateExternalGate.id == V2TemplateExternalGateTask.gate_id)
            .where(V2TemplateExternalGate.template_version_id == version.id)
        ) or 0

        special_codes = [f"T{i:03d}" for i in range(1, 9)] + ["T097", "T098", "T099"]
        special_tasks = self.session.scalars(
            select(V2TemplateTask)
            .where(
                V2TemplateTask.template_version_id == version.id,
                V2TemplateTask.code.in_(special_codes),
            )
            .order_by(V2TemplateTask.sequence_no)
        ).all()
        task_summary = {
            task.code: {
                "schedule_classification": task.schedule_classification,
                "planned_start_day": task.planned_start_day,
                "planned_end_day": task.planned_end_day,
                "applicability": task.applicability,
            }
            for task in special_tasks
        }
        return {
            "template": {"id": str(template.id), "code": template.code, "name": template.name},
            "version": {
                "id": str(version.id),
                "label": CANONICAL_VERSION,
                "version_no": version.version_no,
                "status": version.status,
                "duration_days": version.duration_days,
                "is_current_published": version.is_current_published,
                "content_hash": version.content_hash,
            },
            "counts": {
                "tasks": int(task_count),
                "dependencies": int(dependency_count),
                "external_gates": int(gate_count),
                "exact_gate_task_mappings": int(exact_mapping_count),
                "broad_text_gates": int(broad_gate_count),
            },
            "schedule_checks": {
                "T001_T007": {code: task_summary.get(code) for code in special_codes[:7]},
                "T008": task_summary.get("T008"),
                "T098": task_summary.get("T098"),
                "T097_T099": {code: task_summary.get(code) for code in ("T097", "T098", "T099")},
            },
        }


RepositoryFactory = Callable[[Session], Any]


def _expected_exact_mapping_count(gates: list[dict[str, Any]]) -> int:
    return sum(
        len(gate.get("task_codes", []))
        for gate in gates
        if gate.get("mapping_classification") == "exact"
    )


def _assert_verification(report: dict[str, Any], content_hash: str, exact_mapping_count: int) -> None:
    expected_counts = {
        "tasks": 99,
        "dependencies": 38,
        "external_gates": 32,
        "exact_gate_task_mappings": exact_mapping_count,
        "broad_text_gates": 6,
    }
    version = report["version"]
    if report["counts"] != expected_counts:
        raise TemplateImportConflict(
            f"Stored version {CANONICAL_VERSION} has unexpected counts: {report['counts']}; expected {expected_counts}."
        )
    if (
        version["content_hash"] != content_hash
        or version["status"] != "published"
        or version["duration_days"] != EXPECTED_DURATION_DAYS
        or version["is_current_published"] is not True
    ):
        raise TemplateImportConflict(
            f"Stored version {CANONICAL_VERSION} does not match the authoritative published state."
        )


def import_authoritative_template(
    *,
    fixture_dir: Path | str = DEFAULT_FIXTURE_DIR,
    created_by_email: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    session_factory: Any = SessionLocal,
    repository_factory: RepositoryFactory = SQLAlchemyTemplateRepository,
) -> ImportResult:
    """Validate, atomically import, or idempotently accept the template."""
    bundle = _validated_bundle(fixture_dir)  # deliberately before Session/transaction
    content_hash = compute_content_hash(bundle)
    task_fixture = bundle["tasks"]
    tasks = _fixture_items(task_fixture, "tasks")
    dependencies = _fixture_items(bundle["dependencies"], "dependencies")
    gates = _fixture_items(bundle["gates"], "external_gates")
    exact_mapping_count = _expected_exact_mapping_count(gates)
    template_code = task_fixture["template_code"]

    with session_factory() as session:
        with session.begin():
            repository = repository_factory(session)
            resolved_actor_id = actor_user_id
            if resolved_actor_id is None:
                if not created_by_email:
                    raise TemplateImportError("--created-by-email is required for an import.")
                resolved_actor_id = repository.resolve_super_admin(created_by_email).id

            template = repository.get_template(template_code)
            if template is None:
                template = repository.create_template(
                    code=template_code,
                    name=task_fixture["template_name"],
                    description=task_fixture.get("source_status"),
                )
            elif template.name != task_fixture["template_name"]:
                raise TemplateImportConflict(
                    f"Template code '{template_code}' already exists with a different stable name."
                )

            existing = repository.get_version(template.id, DATABASE_VERSION_NO)
            if existing is not None:
                if existing.content_hash != content_hash:
                    raise TemplateImportConflict(
                        f"Published version {CANONICAL_VERSION} already exists with a different content hash; it was not overwritten."
                    )
                report = repository.verification_report(template_code, DATABASE_VERSION_NO)
                _assert_verification(report, content_hash, exact_mapping_count)
                return ImportResult(
                    template_code=template_code,
                    version=CANONICAL_VERSION,
                    content_hash=content_hash,
                    outcome="already_imported",
                    verification=report,
                )

            current = repository.get_current_published(template.id)
            if current is not None:
                raise TemplateImportConflict(
                    f"Template '{template_code}' already has another current published version; no rows were changed."
                )

            version = repository.create_version(
                template_id=template.id,
                content_hash=content_hash,
                actor_user_id=resolved_actor_id,
                change_note=f"Authoritative fixture import {CANONICAL_VERSION}.",
            )
            tasks_by_code = repository.create_tasks(version.id, tasks)
            repository.create_dependencies(version.id, dependencies, tasks_by_code)
            gates_by_code = repository.create_gates(version.id, gates)
            repository.create_exact_gate_links(gates, gates_by_code, tasks_by_code)
            repository.publish_version(version, resolved_actor_id)
            repository.write_import_audit(
                version=version,
                actor_user_id=resolved_actor_id,
                content_hash=content_hash,
                counts={
                    "task_count": len(tasks),
                    "dependency_count": len(dependencies),
                    "external_gate_count": len(gates),
                    "exact_gate_task_mapping_count": exact_mapping_count,
                },
            )
            report = repository.verification_report(template_code, DATABASE_VERSION_NO)
            _assert_verification(report, content_hash, exact_mapping_count)
            return ImportResult(
                template_code=template_code,
                version=CANONICAL_VERSION,
                content_hash=content_hash,
                outcome="imported",
                verification=report,
            )


def verify_authoritative_template(
    *,
    template_code: str = "workved_45_day_permanent",
    session_factory: Any = SessionLocal,
    repository_factory: RepositoryFactory = SQLAlchemyTemplateRepository,
) -> dict[str, Any]:
    with session_factory() as session:
        return repository_factory(session).verification_report(template_code, DATABASE_VERSION_NO)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import or verify the authoritative Workved V2 template.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    import_parser = subparsers.add_parser("import", help="Validate and atomically import version 1.0.0.")
    import_parser.add_argument("--created-by-email", required=True, help="Existing active Super Admin email.")
    import_parser.add_argument("--fixture-dir", type=Path, default=DEFAULT_FIXTURE_DIR)
    verify_parser = subparsers.add_parser("verify", help="Report persisted template counts and schedule checks.")
    verify_parser.add_argument("--template-code", default="workved_45_day_permanent")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "import":
            output = import_authoritative_template(
                fixture_dir=args.fixture_dir,
                created_by_email=args.created_by_email,
            ).to_dict()
        else:
            output = verify_authoritative_template(template_code=args.template_code)
    except TemplateImportConflict as exc:
        print(json.dumps({"status": "conflict", "message": str(exc)}, indent=2), file=sys.stderr)
        return 2
    except TemplateImportError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(output, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
