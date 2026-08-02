"""Execution-layer models (U1): baseline lock and instantiated task graph.

`project_baselines` / `baseline_tasks` are the immutable snapshot captured at
project activation. `tasks` / `task_dependencies` are the execution-layer
entities instantiated from that snapshot at activation time.

This is a deliberately NEW table pair, distinct from
`app.project_models.V2ProjectTask` / `V2ProjectTaskDependency` (the planning
table, still `lifecycle_status = 'draft'`-only). `V2ProjectTask` remains
purely a planning/authoring artifact; `tasks` here is purely an execution
artifact. Never conflate the two - see the plan's Key Technical Decisions.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, SmallInteger, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.project_models import V2_SCHEMA


TASK_LIFECYCLE_STATUSES = (
    "planned", "ready", "in_progress", "submitted", "verified",
    "approval_pending", "rejected", "completed", "cancelled",
)


class ProjectBaseline(Base):
    __tablename__ = "project_baselines"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_v2_project_baselines_project"),
        CheckConstraint("task_count > 0", name="ck_v2_project_baselines_task_count_positive"),
        CheckConstraint("dependency_count >= 0", name="ck_v2_project_baselines_dependency_count"),
        CheckConstraint("gate_count >= 0", name="ck_v2_project_baselines_gate_count"),
        Index("ix_v2_project_baselines_project", "project_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False)
    task_count: Mapped[int] = mapped_column(Integer, nullable=False)
    dependency_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    locked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BaselineTask(Base):
    """An immutable snapshot row of one included V2ProjectTask at lock time.

    DB-level immutability (reject UPDATE/DELETE) is enforced by a Postgres
    trigger in the migration, not by application code - see
    supabase/migrations/202608020001_v2_project_baseline_and_tasks.sql.
    `content_hash` here is a cheap cross-environment integrity check only.
    """

    __tablename__ = "baseline_tasks"
    __table_args__ = (
        UniqueConstraint("baseline_id", "project_task_id", name="uq_v2_baseline_tasks_baseline_project_task"),
        UniqueConstraint("baseline_id", "original_code", name="uq_v2_baseline_tasks_baseline_code"),
        CheckConstraint("template_sequence > 0", name="ck_v2_baseline_tasks_sequence_positive"),
        CheckConstraint("schedule_classification in ('pre_activation', 'execution')", name="ck_v2_baseline_tasks_schedule_classification"),
        CheckConstraint("applicability in ('mandatory', 'conditional')", name="ck_v2_baseline_tasks_applicability"),
        CheckConstraint("task_class is null or task_class in ('standard', 'class_a')", name="ck_v2_baseline_tasks_task_class"),
        CheckConstraint("task_kind is null or task_kind in ('work', 'approval_gate', 'milestone')", name="ck_v2_baseline_tasks_task_kind"),
        Index("ix_v2_baseline_tasks_baseline", "baseline_id"),
        Index("ix_v2_baseline_tasks_project", "project_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    baseline_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_baselines.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False)
    project_task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_tasks.id", ondelete="RESTRICT"), nullable=False)
    original_code: Mapped[str] = mapped_column(Text, nullable=False)
    template_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    schedule_classification: Mapped[str] = mapped_column(Text, nullable=False)
    planned_start_day: Mapped[int | None] = mapped_column(SmallInteger)
    planned_end_day: Mapped[int | None] = mapped_column(SmallInteger)
    phase: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    applicability: Mapped[str] = mapped_column(Text, nullable=False)
    task_class: Mapped[str | None] = mapped_column(Text)
    task_kind: Mapped[str | None] = mapped_column(Text)
    evidence_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duration_days: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Task(Base):
    """Execution-layer task instantiated from a BaselineTask at activation."""

    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("project_id", "original_code", name="uq_v2_tasks_project_code"),
        UniqueConstraint("baseline_task_id", name="uq_v2_tasks_baseline_task"),
        CheckConstraint("template_sequence > 0", name="ck_v2_tasks_sequence_positive"),
        CheckConstraint("schedule_classification in ('pre_activation', 'execution')", name="ck_v2_tasks_schedule_classification"),
        CheckConstraint("applicability in ('mandatory', 'conditional')", name="ck_v2_tasks_applicability"),
        CheckConstraint("task_class is null or task_class in ('standard', 'class_a')", name="ck_v2_tasks_task_class"),
        CheckConstraint("task_kind is null or task_kind in ('work', 'approval_gate', 'milestone')", name="ck_v2_tasks_task_kind"),
        CheckConstraint(f"lifecycle_status in {TASK_LIFECYCLE_STATUSES!r}", name="ck_v2_tasks_lifecycle_status"),
        Index("ix_v2_tasks_project_sequence", "project_id", "template_sequence"),
        Index("ix_v2_tasks_baseline", "baseline_id"),
        Index("ix_v2_tasks_project_status", "project_id", "lifecycle_status"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False)
    baseline_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_baselines.id", ondelete="RESTRICT"), nullable=False)
    baseline_task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.baseline_tasks.id", ondelete="RESTRICT"), nullable=False)
    original_code: Mapped[str] = mapped_column(Text, nullable=False)
    template_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    schedule_classification: Mapped[str] = mapped_column(Text, nullable=False)
    planned_start_day: Mapped[int | None] = mapped_column(SmallInteger)
    planned_end_day: Mapped[int | None] = mapped_column(SmallInteger)
    phase: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    applicability: Mapped[str] = mapped_column(Text, nullable=False)
    task_class: Mapped[str | None] = mapped_column(Text)
    task_kind: Mapped[str | None] = mapped_column(Text)
    evidence_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duration_days: Mapped[int | None] = mapped_column(Integer)
    lifecycle_status: Mapped[str] = mapped_column(Text, nullable=False, default="planned")
    created_from_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class TaskDependency(Base):
    """Execution-layer dependency edge, copied 1:1 from the baseline graph."""

    __tablename__ = "task_dependencies"
    __table_args__ = (
        UniqueConstraint("project_id", "predecessor_task_id", "successor_task_id", "dependency_type", name="uq_v2_task_dependencies_edge"),
        CheckConstraint("predecessor_task_id <> successor_task_id", name="ck_v2_task_dependencies_not_self"),
        CheckConstraint("dependency_type in ('finish_to_start', 'start_to_start')", name="ck_v2_task_dependencies_type"),
        Index("ix_v2_task_dependencies_project", "project_id"),
        Index("ix_v2_task_dependencies_predecessor", "predecessor_task_id"),
        Index("ix_v2_task_dependencies_successor", "successor_task_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False)
    baseline_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_baselines.id", ondelete="RESTRICT"), nullable=False)
    project_dependency_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_task_dependencies.id", ondelete="RESTRICT"))
    predecessor_task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.tasks.id", ondelete="RESTRICT"), nullable=False)
    successor_task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.tasks.id", ondelete="RESTRICT"), nullable=False)
    dependency_type: Mapped[str] = mapped_column(Text, nullable=False)
    blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rule_text: Mapped[str | None] = mapped_column(Text)
    created_from_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TaskProgressUpdate(Base):
    """U3: append-only progress note against an execution-layer task.

    Never itself changes `Task.lifecycle_status` - it's evidence a later
    `submitted` transition (U2's TaskLifecycleService) can reference. May
    optionally carry evidence files via `TaskEvidence` link rows.
    """

    __tablename__ = "task_progress_updates"
    __table_args__ = (
        CheckConstraint("update_type in ('note', 'evidence')", name="ck_v2_task_progress_updates_update_type"),
        CheckConstraint("source in ('portal', 'whatsapp', 'system')", name="ck_v2_task_progress_updates_source"),
        Index("ix_v2_task_progress_updates_task", "task_id"),
        Index("ix_v2_task_progress_updates_project", "project_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.tasks.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False)
    update_type: Mapped[str] = mapped_column(Text, nullable=False)
    status_claim: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    submitted_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="portal")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class FileObject(Base):
    """U3: metadata for one uploaded file. Bytes live on disk under
    `settings.evidence_upload_dir` - a directory deliberately never passed
    to StaticFiles (see backend/app/main.py) - keyed by `storage_key`. This
    table never stores a public URL, only enough metadata for the
    authenticated download route to locate and validate the file."""

    __tablename__ = "file_objects"
    __table_args__ = (
        UniqueConstraint("storage_key", name="uq_v2_file_objects_storage_key"),
        CheckConstraint("size_bytes > 0", name="ck_v2_file_objects_size_positive"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TaskEvidence(Base):
    """U3: real FK link between a progress update and an uploaded file -
    deliberately NOT a polymorphic entity_type/entity_id reference, per the
    plan's Key Technical Decisions."""

    __tablename__ = "task_evidence"
    __table_args__ = (
        UniqueConstraint("task_progress_update_id", "file_id", name="uq_v2_task_evidence_update_file"),
        Index("ix_v2_task_evidence_progress_update", "task_progress_update_id"),
        Index("ix_v2_task_evidence_file", "file_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_progress_update_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.task_progress_updates.id", ondelete="RESTRICT"), nullable=False)
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.file_objects.id", ondelete="RESTRICT"), nullable=False)
    evidence_type: Mapped[str] = mapped_column(Text, nullable=False, default="photo")
    caption: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TaskVerification(Base):
    """U4: a Supervisor's (or audited PM/Admin fallback's) verification
    decision on a `work` task's submitted evidence (BR-008). Never applies
    to `approval_gate` tasks - those skip Supervisor verification entirely
    and go straight to `TaskApprovalDecision`.

    `submission_update_id` links back to the `TaskProgressUpdate` (U3) that
    was being verified. On `decision == 'verified'`,
    `TaskLifecycleService.transition` advances the task to `verified`
    (and immediately to `completed` for `standard` work, since standard
    work needs no PM step). On `decision == 'rejected'`, the task returns
    to `in_progress` under Supervisor accountability again.
    """

    __tablename__ = "task_verifications"
    __table_args__ = (
        CheckConstraint("decision in ('verified', 'rejected')", name="ck_v2_task_verifications_decision"),
        Index("ix_v2_task_verifications_task", "task_id"),
        Index("ix_v2_task_verifications_task_verified_at", "task_id", "verified_at"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.tasks.id", ondelete="RESTRICT"), nullable=False)
    submission_update_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.task_progress_updates.id", ondelete="RESTRICT"), nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text)
    verified_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TaskApprovalDecision(Base):
    """U4: a PM's (or audited Admin fallback's) approval decision (BR-008).

    Required for every `class_a` work task (after Supervisor verification -
    `verification_id` populated, and the verifying actor may not also be
    the approving actor for the same decision cycle - enforced in
    `TaskApprovalService`, not at the schema level) and every
    `approval_gate` task (directly, no verification prerequisite -
    `verification_id` is null).
    """

    __tablename__ = "task_approval_decisions"
    __table_args__ = (
        CheckConstraint("decision in ('approved', 'rejected')", name="ck_v2_task_approval_decisions_decision"),
        Index("ix_v2_task_approval_decisions_task", "task_id"),
        Index("ix_v2_task_approval_decisions_task_decided_at", "task_id", "decided_at"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.tasks.id", ondelete="RESTRICT"), nullable=False)
    verification_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.task_verifications.id", ondelete="RESTRICT"))
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
