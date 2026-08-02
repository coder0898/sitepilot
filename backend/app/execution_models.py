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
