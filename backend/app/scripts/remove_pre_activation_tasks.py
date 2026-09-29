"""Publish a new template version without the seven pre-activation tasks
(T001-T007), so future projects no longer generate them.

Why: these tasks are work that happens before the site timeline starts, so
the template gives them no planned day. With no dates they never receive a
reminder, overdue alert or escalation, yet they sat in every project's task
list. Decision 2026-09-29: drop them from future projects.

What it does, entirely through the template services the Super Admin
template editor uses (same validation, same audit):
  1. clone the current published version of the template into a draft;
  2. remove every dependency that touches T001-T007;
  3. unlink T001-T007 from any gate. A gate left with no linked task becomes
     "unmapped" (still a gate, still assigned and decided as normal) - today
     that is only E004 "Approved BOQ and material specifications";
  4. delete T001-T007 from the draft;
  5. publish the draft as the new current version.
Existing projects are untouched: their tasks are copies taken at creation,
and the previous version stays in the database, no longer current.

Dry run by default (read-only: prints the plan). APPLY=1 performs it.
Run inside the backend container:
    docker exec -e PYTHONPATH=/app -w /app siteops_mvp_backend \
        python -m app.scripts.remove_pre_activation_tasks
Pass `-e DATABASE_URL=...` to point it at another database (e.g. prod).
"""

from __future__ import annotations

import os
import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models import User, UserRole
from app.services.template_commands import TemplateCommandService
from app.services.template_dependency_commands import TemplateDependencyCommandService
from app.services.template_gate_commands import TemplateGateCommandService
from app.services.template_mutation_access import concurrency_token
from app.services.template_publish_service import TemplatePublishService
from app.services.template_task_commands import TemplateTaskCommandService
from app.template_gate_mutation_schemas import TemplateGateMappingRequest
from app.template_models import (
    V2TemplateExternalGate,
    V2TemplateExternalGateTask,
    V2TemplateTask,
    V2TemplateTaskDependency,
    V2TemplateVersion,
)
from app.template_mutation_schemas import TemplateCloneRequest
from app.template_publish_schemas import TemplatePublishRequest

PRE_ACTIVATION_CODES = ("T001", "T002", "T003", "T004", "T005", "T006", "T007")
CHANGE_NOTE = (
    "Removed pre-activation tasks T001-T007 (no planned dates, so never tracked). "
    "Gates left without a linked task are kept as unmapped."
)


def _plan(db, version_id: uuid.UUID) -> dict:
    tasks = {t.code: t for t in db.scalars(select(V2TemplateTask).where(V2TemplateTask.template_version_id == version_id))}
    missing = [code for code in PRE_ACTIVATION_CODES if code not in tasks]
    if missing:
        raise SystemExit(f"abort: tasks not found in this version: {missing} (already removed?)")
    remove_ids = {tasks[code].id for code in PRE_ACTIVATION_CODES}
    code_of = {t.id: code for code, t in tasks.items()}
    dependencies = [
        d for d in db.scalars(select(V2TemplateTaskDependency).where(V2TemplateTaskDependency.template_version_id == version_id))
        if d.predecessor_task_id in remove_ids or d.successor_task_id in remove_ids
    ]
    gates = []
    for gate in db.scalars(select(V2TemplateExternalGate).where(V2TemplateExternalGate.template_version_id == version_id)):
        linked = [m.template_task_id for m in db.scalars(select(V2TemplateExternalGateTask).where(V2TemplateExternalGateTask.gate_id == gate.id))]
        if any(task_id in remove_ids for task_id in linked):
            keep = [task_id for task_id in linked if task_id not in remove_ids]
            gates.append((gate, keep))
    return {"tasks": tasks, "remove_ids": remove_ids, "code_of": code_of, "dependencies": dependencies, "gates": gates}


def _token(db, version_id: uuid.UUID) -> str:
    db.expire_all()
    return concurrency_token(db.get(V2TemplateVersion, version_id))


def main() -> None:
    apply = os.environ.get("APPLY") == "1"
    with SessionLocal() as db:
        actor = db.scalar(select(User).where(User.role == UserRole.super_admin, User.active.is_(True)).limit(1))
        if actor is None:
            raise SystemExit("abort: no active Super Admin to act as.")
        current = db.scalars(select(V2TemplateVersion).where(V2TemplateVersion.is_current_published.is_(True))).all()
        if len(current) != 1:
            raise SystemExit(f"abort: expected exactly one current published version, found {len(current)}.")
        source = current[0]
        plan = _plan(db, source.id)
        print(f"source: version {source.version_no} ({len(plan['tasks'])} tasks), acting as {actor.email}")
        print("remove tasks:", ", ".join(PRE_ACTIVATION_CODES))
        for d in plan["dependencies"]:
            print(f"remove dependency: {plan['code_of'][d.predecessor_task_id]} -> {plan['code_of'][d.successor_task_id]}")
        for gate, keep in plan["gates"]:
            after = f"keeps {len(keep)} linked task(s)" if keep else "becomes unmapped (no linked task)"
            print(f"gate {gate.code} '{gate.approval_name}': unlink removed tasks, {after}")
        if not apply:
            print("DRY RUN - nothing changed. Set APPLY=1 to publish the new version.")
            return

        draft = TemplateCommandService(db).clone_version(actor, source.id, TemplateCloneRequest(change_note=CHANGE_NOTE))
        draft_id = draft.version_id
        print(f"cloned into draft version {draft.version_no}")
        plan = _plan(db, draft_id)  # the draft's own row ids

        for d in plan["dependencies"]:
            TemplateDependencyCommandService(db).delete_dependency(actor, draft_id, d.id, revision_token=_token(db, draft_id))
        for gate, keep in plan["gates"]:
            payload = (
                {"mapping_classification": "exact", "task_ids": keep}
                if keep else {"mapping_classification": "unmapped", "task_ids": []}
            )
            TemplateGateCommandService(db).configure_mappings(
                actor, draft_id, gate.id, TemplateGateMappingRequest(revision_token=_token(db, draft_id), **payload),
            )
        for code in PRE_ACTIVATION_CODES:
            TemplateTaskCommandService(db).delete_task(actor, draft_id, plan["tasks"][code].id, revision_token=_token(db, draft_id))

        published = TemplatePublishService(db).publish(
            actor, draft_id, TemplatePublishRequest(revision_token=_token(db, draft_id), change_note=CHANGE_NOTE),
        )
        db.expire_all()
        remaining = db.scalars(select(V2TemplateTask.code).where(V2TemplateTask.template_version_id == draft_id)).all()
        print(f"PUBLISHED version {draft.version_no} as current: {len(remaining)} tasks, "
              f"pre-activation tasks left: {[c for c in PRE_ACTIVATION_CODES if c in remaining]}")
        print("publish result:", getattr(published, "status", published))


if __name__ == "__main__":
    main()
