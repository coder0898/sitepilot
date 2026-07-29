"""Transactional draft-only task commands for V2 template versions."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import User
from app.repositories.template_mutation_repository import TemplateMutationRepository
from app.repositories.template_task_repository import TemplateTaskRepository
from app.services.template_audit import (
    TemplateAuditAction,
    TemplateAuditWrite,
    write_template_audit_event,
)
from app.services.template_mutation_access import require_template_mutation_access
from app.services.transaction_boundary import command_transaction
from app.template_models import V2TemplateTask
from app.template_task_mutation_schemas import (
    TemplateTaskCreateRequest,
    TemplateTaskDeleteResponse,
    TemplateTaskMutationItem,
    TemplateTaskMutationResponse,
    TemplateTaskReorderRequest,
    TemplateTaskReorderResponse,
    TemplateTaskReorderResult,
    TemplateTaskUpdateRequest,
)


TASK_FIELDS = (
    "code",
    "sequence_no",
    "title",
    "description",
    "schedule_classification",
    "planned_start_day",
    "planned_end_day",
    "phase",
    "category",
    "applicability",
    "task_class",
    "task_kind",
    "evidence_required",
    "duration_days",
)


def _task_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Template task not found.",
    )


def _conflict(code: str, message: str, **details: Any) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": message, **details},
    )


def _invalid_task(message: str, **details: Any) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": "invalid_template_task", "message": message, **details},
    )


def _normalize_code(value: str) -> str:
    return value.strip().upper()


def _snapshot(task: V2TemplateTask) -> dict[str, Any]:
    return {field: getattr(task, field) for field in TASK_FIELDS}


def _audit_snapshot(task: V2TemplateTask) -> dict[str, Any]:
    return {
        "task_id": str(task.id),
        "template_version_id": str(task.template_version_id),
        **_snapshot(task),
    }


def _validate_task(values: dict[str, Any], *, duration_days: int) -> None:
    code = _normalize_code(values.get("code") or "")
    title = (values.get("title") or "").strip()
    if not code:
        raise _invalid_task("Task code is required.")
    if not title:
        raise _invalid_task("Task title is required.")
    if not isinstance(values.get("sequence_no"), int) or values["sequence_no"] <= 0:
        raise _invalid_task("Task sequence must be a positive integer.")

    classification = values.get("schedule_classification")
    start_day = values.get("planned_start_day")
    end_day = values.get("planned_end_day")
    if classification == "pre_activation":
        if start_day is not None or end_day is not None:
            raise _invalid_task(
                "Pre-Activation tasks cannot have project-day values.",
                schedule_classification=classification,
            )
    elif classification == "execution":
        if start_day is None or end_day is None:
            raise _invalid_task(
                "Execution tasks require both planned start and end days.",
                schedule_classification=classification,
            )
        if start_day < 1 or end_day < 1 or start_day > duration_days or end_day > duration_days:
            raise _invalid_task(
                "Execution task days must be within the template duration.",
                duration_days=duration_days,
                planned_start_day=start_day,
                planned_end_day=end_day,
            )
        if start_day > end_day:
            raise _invalid_task(
                "Planned start day cannot exceed planned end day.",
                planned_start_day=start_day,
                planned_end_day=end_day,
            )
    else:
        raise _invalid_task("Unsupported schedule classification.")

    if values.get("applicability") not in {"mandatory", "conditional"}:
        raise _invalid_task("Applicability must be mandatory or conditional.")

    # Execution duration is authoritative and derived from persisted schedule days.
    # Pre-Activation duration remains optional because it has no project-day placement.
    if classification == "execution":
        values["duration_days"] = end_day - start_day + 1


def _mutation_item(task: V2TemplateTask) -> TemplateTaskMutationItem:
    return TemplateTaskMutationItem(
        id=task.id,
        template_version_id=task.template_version_id,
        **_snapshot(task),
    )


class TemplateTaskCommandService:
    def __init__(self, db: Session):
        self.db = db
        self.versions = TemplateMutationRepository(db)
        self.tasks = TemplateTaskRepository(db)

    def _require_unique(
        self,
        version_id: uuid.UUID,
        *,
        code: str,
        sequence_no: int,
        exclude_task_id: uuid.UUID | None = None,
    ) -> None:
        if self.tasks.code_exists(version_id, code, exclude_task_id=exclude_task_id):
            raise _conflict(
                "template_task_code_exists",
                f"Task code {code} already exists in this version.",
                version_id=str(version_id),
                task_code=code,
            )
        if self.tasks.sequence_exists(
            version_id, sequence_no, exclude_task_id=exclude_task_id
        ):
            raise _conflict(
                "template_task_sequence_exists",
                f"Task sequence {sequence_no} already exists in this version.",
                version_id=str(version_id),
                sequence_no=sequence_no,
            )

    def create_task(
        self,
        actor: User,
        version_id: uuid.UUID,
        payload: TemplateTaskCreateRequest,
    ) -> TemplateTaskMutationResponse:
        require_template_mutation_access(actor)
        try:
            with command_transaction(self.db):
                version = self.versions.get_version_for_mutation(
                    version_id,
                    expected_token=payload.revision_token,
                )
                values = payload.model_dump(exclude={"revision_token"})
                values["code"] = _normalize_code(values["code"])
                values["title"] = values["title"].strip()
                _validate_task(values, duration_days=version.duration_days)
                self._require_unique(
                    version.id,
                    code=values["code"],
                    sequence_no=values["sequence_no"],
                )
                task = self.tasks.create_task(version.id, values)
                revision_token = self.versions.touch(version)
                write_template_audit_event(
                    self.db,
                    TemplateAuditWrite(
                        action=TemplateAuditAction.TEMPLATE_TASK_CREATED,
                        entity_type="template_task",
                        entity_id=task.id,
                        actor_user_id=actor.id,
                        reason=f"Created draft template task {task.code}.",
                        after_json=_audit_snapshot(task),
                    ),
                )
                result = TemplateTaskMutationResponse(
                    task=_mutation_item(task),
                    revision_token=revision_token,
                )
            return result
        except HTTPException:
            raise
        except IntegrityError as exc:
            raise _conflict(
                "template_task_conflict",
                "The task could not be created because its code or sequence changed concurrently.",
                version_id=str(version_id),
            ) from exc

    def update_task(
        self,
        actor: User,
        version_id: uuid.UUID,
        task_id: uuid.UUID,
        payload: TemplateTaskUpdateRequest,
    ) -> TemplateTaskMutationResponse:
        require_template_mutation_access(actor)
        try:
            with command_transaction(self.db):
                version = self.versions.get_version_for_mutation(
                    version_id,
                    expected_token=payload.revision_token,
                )
                task = self.tasks.get_task(version.id, task_id)
                if task is None:
                    raise _task_not_found()
                before = _audit_snapshot(task)
                changes = payload.model_dump(
                    exclude={"revision_token"},
                    exclude_unset=True,
                )
                if "code" in changes:
                    changes["code"] = _normalize_code(changes["code"])
                if "title" in changes:
                    changes["title"] = changes["title"].strip()
                candidate = {**_snapshot(task), **changes}
                if candidate == _snapshot(task):
                    raise _invalid_task(
                        "Task update does not contain an effective change.",
                        task_id=str(task.id),
                    )
                _validate_task(candidate, duration_days=version.duration_days)
                self._require_unique(
                    version.id,
                    code=candidate["code"],
                    sequence_no=candidate["sequence_no"],
                    exclude_task_id=task.id,
                )
                self.tasks.update_task(task, changes)
                revision_token = self.versions.touch(version)
                write_template_audit_event(
                    self.db,
                    TemplateAuditWrite(
                        action=TemplateAuditAction.TEMPLATE_TASK_UPDATED,
                        entity_type="template_task",
                        entity_id=task.id,
                        actor_user_id=actor.id,
                        reason=f"Updated draft template task {task.code}.",
                        before_json=before,
                        after_json=_audit_snapshot(task),
                    ),
                )
                result = TemplateTaskMutationResponse(
                    task=_mutation_item(task),
                    revision_token=revision_token,
                )
            return result
        except HTTPException:
            raise
        except IntegrityError as exc:
            raise _conflict(
                "template_task_conflict",
                "The task could not be updated because its code or sequence changed concurrently.",
                version_id=str(version_id),
                task_id=str(task_id),
            ) from exc

    def delete_task(
        self,
        actor: User,
        version_id: uuid.UUID,
        task_id: uuid.UUID,
        *,
        revision_token: str,
    ) -> TemplateTaskDeleteResponse:
        require_template_mutation_access(actor)
        with command_transaction(self.db):
            version = self.versions.get_version_for_mutation(
                version_id,
                expected_token=revision_token,
            )
            task = self.tasks.get_task(version.id, task_id)
            if task is None:
                raise _task_not_found()
            references = self.tasks.blocking_references(task)
            if references.blocked:
                raise _conflict(
                    "template_task_referenced",
                    "Remove or remap the task references before deleting this task.",
                    version_id=str(version.id),
                    task_id=str(task.id),
                    dependencies=[
                        {
                            "dependency_id": str(item.id),
                            "relationship": item.relationship,
                            "other_task_id": str(item.other_task_id),
                        }
                        for item in references.dependencies
                    ],
                    gate_mappings=[
                        {
                            "mapping_id": str(item.id),
                            "gate_id": str(item.gate_id),
                            "gate_code": item.gate_code,
                        }
                        for item in references.gate_mappings
                    ],
                )
            before = _audit_snapshot(task)
            deleted_id = task.id
            deleted_code = task.code
            self.tasks.delete_task(task)
            new_revision = self.versions.touch(version)
            write_template_audit_event(
                self.db,
                TemplateAuditWrite(
                    action=TemplateAuditAction.TEMPLATE_TASK_DELETED,
                    entity_type="template_task",
                    entity_id=deleted_id,
                    actor_user_id=actor.id,
                    reason=f"Deleted unreferenced draft template task {deleted_code}.",
                    before_json=before,
                ),
            )
            result = TemplateTaskDeleteResponse(
                task_id=deleted_id,
                revision_token=new_revision,
            )
        return result

    def reorder_tasks(
        self,
        actor: User,
        version_id: uuid.UUID,
        payload: TemplateTaskReorderRequest,
    ) -> TemplateTaskReorderResponse:
        require_template_mutation_access(actor)
        with command_transaction(self.db):
            version = self.versions.get_version_for_mutation(
                version_id,
                expected_token=payload.revision_token,
            )
            tasks = self.tasks.list_tasks(version.id)
            existing_ids = {task.id for task in tasks}
            supplied_ids = [item.task_id for item in payload.items]
            supplied_sequences = [item.sequence_no for item in payload.items]
            if len(set(supplied_ids)) != len(supplied_ids):
                raise _invalid_task("Reorder payload contains duplicate task IDs.")
            if set(supplied_ids) != existing_ids:
                raise _invalid_task(
                    "Complete reorder must include every task exactly once.",
                    expected_task_ids=sorted(str(value) for value in existing_ids),
                )
            expected_sequences = set(range(1, len(tasks) + 1))
            if set(supplied_sequences) != expected_sequences or len(
                set(supplied_sequences)
            ) != len(supplied_sequences):
                raise _invalid_task(
                    "Complete reorder sequences must contain every value from 1 through the task count exactly once.",
                    expected_sequences=sorted(expected_sequences),
                )

            before = [
                {"task_id": str(task.id), "code": task.code, "sequence_no": task.sequence_no}
                for task in tasks
            ]
            sequence_by_id = {
                item.task_id: item.sequence_no
                for item in payload.items
            }
            if all(sequence_by_id[task.id] == task.sequence_no for task in tasks):
                return TemplateTaskReorderResponse(
                    items=[
                        TemplateTaskReorderResult(
                            task_id=task.id,
                            code=task.code,
                            sequence_no=task.sequence_no,
                        )
                        for task in tasks
                    ],
                    revision_token=payload.revision_token,
                )
            ordered = self.tasks.reorder_complete(tasks, sequence_by_id)
            new_revision = self.versions.touch(version)
            after = [
                {"task_id": str(task.id), "code": task.code, "sequence_no": task.sequence_no}
                for task in ordered
            ]
            write_template_audit_event(
                self.db,
                TemplateAuditWrite(
                    action=TemplateAuditAction.TEMPLATE_TASKS_REORDERED,
                    entity_type="template_version",
                    entity_id=version.id,
                    actor_user_id=actor.id,
                    reason="Reordered all tasks in the draft template version.",
                    before_json={"tasks": before},
                    after_json={"tasks": after},
                ),
            )
            result = TemplateTaskReorderResponse(
                items=[
                    TemplateTaskReorderResult(
                        task_id=task.id,
                        code=task.code,
                        sequence_no=task.sequence_no,
                    )
                    for task in ordered
                ],
                revision_token=new_revision,
            )
        return result