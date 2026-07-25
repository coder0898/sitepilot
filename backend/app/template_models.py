"""SQLAlchemy models for the V2 template schema.

These models intentionally live outside the legacy execution-template models.
Supabase SQL migrations own the physical V2 schema; SQLAlchemy mirrors it for
FastAPI services and tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


V2_SCHEMA = "siteops_v2"


class V2Template(Base):
    __tablename__ = "v2_templates"
    __table_args__ = (
        UniqueConstraint("code", name="uq_v2_templates_code"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    versions: Mapped[list[V2TemplateVersion]] = relationship(back_populates="template")


class V2TemplateVersion(Base):
    __tablename__ = "v2_template_versions"
    __table_args__ = (
        UniqueConstraint("template_id", "version_no", name="uq_v2_template_versions_template_version"),
        CheckConstraint("version_no > 0", name="ck_v2_template_versions_version_positive"),
        CheckConstraint("status in ('draft', 'published', 'archived')", name="ck_v2_template_versions_status"),
        CheckConstraint("duration_days > 0", name="ck_v2_template_versions_duration_positive"),
        CheckConstraint("status <> 'published' or published_at is not null", name="ck_v2_template_versions_published_fields"),
        CheckConstraint("not is_current_published or status = 'published'", name="ck_v2_template_versions_current_status"),
        Index(
            "uq_v2_template_versions_current_published",
            "template_id",
            unique=True,
            postgresql_where=text("is_current_published"),
        ),
        Index("ix_v2_template_versions_template", "template_id", text("version_no DESC")),
        Index("ix_v2_template_versions_status", "status", text("updated_at DESC")),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{V2_SCHEMA}.v2_templates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    change_note: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(Text)
    is_current_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    published_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    template: Mapped[V2Template] = relationship(back_populates="versions")
    tasks: Mapped[list[V2TemplateTask]] = relationship(back_populates="template_version")
    dependencies: Mapped[list[V2TemplateTaskDependency]] = relationship(back_populates="template_version")
    external_gates: Mapped[list[V2TemplateExternalGate]] = relationship(back_populates="template_version")


class V2TemplateTask(Base):
    __tablename__ = "v2_template_tasks"
    __table_args__ = (
        UniqueConstraint("template_version_id", "code", name="uq_v2_template_tasks_version_code"),
        UniqueConstraint("template_version_id", "sequence_no", name="uq_v2_template_tasks_version_sequence"),
        CheckConstraint("sequence_no > 0", name="ck_v2_template_tasks_sequence_positive"),
        CheckConstraint(
            "schedule_classification in ('pre_activation', 'execution')",
            name="ck_v2_template_tasks_schedule_classification",
        ),
        CheckConstraint("applicability in ('mandatory', 'conditional')", name="ck_v2_template_tasks_applicability"),
        CheckConstraint("duration_days is null or duration_days > 0", name="ck_v2_template_tasks_duration_positive"),
        CheckConstraint(
            "planned_start_day is null or planned_end_day is null or planned_start_day <= planned_end_day",
            name="ck_v2_template_tasks_day_order",
        ),
        CheckConstraint(
            "(schedule_classification = 'pre_activation' and planned_start_day is null and planned_end_day is null) "
            "or (schedule_classification = 'execution' and planned_start_day between 1 and 45 and planned_end_day between 1 and 45)",
            name="ck_v2_template_tasks_schedule_days",
        ),
        Index("ix_v2_template_tasks_version", "template_version_id", "sequence_no"),
        Index("ix_v2_template_tasks_schedule", "template_version_id", "schedule_classification", "planned_start_day"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{V2_SCHEMA}.v2_template_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    schedule_classification: Mapped[str] = mapped_column(Text, nullable=False)
    planned_start_day: Mapped[int | None] = mapped_column(SmallInteger)
    planned_end_day: Mapped[int | None] = mapped_column(SmallInteger)
    phase: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    applicability: Mapped[str] = mapped_column(Text, nullable=False, default="mandatory")
    task_class: Mapped[str | None] = mapped_column(Text)
    task_kind: Mapped[str | None] = mapped_column(Text)
    evidence_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duration_days: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    template_version: Mapped[V2TemplateVersion] = relationship(back_populates="tasks")
    predecessor_dependencies: Mapped[list[V2TemplateTaskDependency]] = relationship(
        back_populates="predecessor_task",
        foreign_keys="V2TemplateTaskDependency.predecessor_task_id",
    )
    successor_dependencies: Mapped[list[V2TemplateTaskDependency]] = relationship(
        back_populates="successor_task",
        foreign_keys="V2TemplateTaskDependency.successor_task_id",
    )
    gate_links: Mapped[list[V2TemplateExternalGateTask]] = relationship(back_populates="template_task")


class V2TemplateTaskDependency(Base):
    __tablename__ = "v2_template_task_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "predecessor_task_id",
            "successor_task_id",
            "dependency_type",
            name="uq_v2_template_task_dependency_edge",
        ),
        CheckConstraint("predecessor_task_id <> successor_task_id", name="ck_v2_template_task_dependencies_not_self"),
        CheckConstraint(
            "dependency_type in ('finish_to_start', 'start_to_start')",
            name="ck_v2_template_task_dependencies_type",
        ),
        CheckConstraint("sequence_no > 0", name="ck_v2_template_task_dependencies_sequence_positive"),
        Index("ix_v2_template_task_dependencies_version", "template_version_id", "sequence_no"),
        Index("ix_v2_template_task_dependencies_predecessor", "predecessor_task_id"),
        Index("ix_v2_template_task_dependencies_successor", "successor_task_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{V2_SCHEMA}.v2_template_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    predecessor_task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{V2_SCHEMA}.v2_template_tasks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    successor_task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{V2_SCHEMA}.v2_template_tasks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    dependency_type: Mapped[str] = mapped_column(Text, nullable=False)
    blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rule_text: Mapped[str | None] = mapped_column(Text)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    template_version: Mapped[V2TemplateVersion] = relationship(back_populates="dependencies")
    predecessor_task: Mapped[V2TemplateTask] = relationship(
        back_populates="predecessor_dependencies",
        foreign_keys=[predecessor_task_id],
    )
    successor_task: Mapped[V2TemplateTask] = relationship(
        back_populates="successor_dependencies",
        foreign_keys=[successor_task_id],
    )


class V2TemplateExternalGate(Base):
    __tablename__ = "v2_template_external_gates"
    __table_args__ = (
        UniqueConstraint("template_version_id", "code", name="uq_v2_template_external_gates_version_code"),
        CheckConstraint(
            "mapping_classification in ('exact', 'broad_text', 'unmapped')",
            name="ck_v2_template_external_gates_mapping",
        ),
        CheckConstraint("sequence_no > 0", name="ck_v2_template_external_gates_sequence_positive"),
        CheckConstraint(
            "mapping_classification = 'exact' or requires_configuration",
            name="ck_v2_template_external_gates_configuration",
        ),
        CheckConstraint(
            "(mapping_classification = 'broad_text' and nullif(btrim(broad_mapping_text), '') is not null) "
            "or (mapping_classification <> 'broad_text' and broad_mapping_text is null)",
            name="ck_v2_template_external_gates_broad_text",
        ),
        Index("ix_v2_template_external_gates_version", "template_version_id", "sequence_no"),
        Index("ix_v2_template_external_gates_mapping", "mapping_classification", "requires_configuration"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{V2_SCHEMA}.v2_template_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    approval_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    external_party: Mapped[str | None] = mapped_column(Text)
    required_by_type: Mapped[str | None] = mapped_column(Text)
    required_by_value: Mapped[str | None] = mapped_column(Text)
    impact: Mapped[str | None] = mapped_column(Text)
    mapping_classification: Mapped[str] = mapped_column(Text, nullable=False)
    broad_mapping_text: Mapped[str | None] = mapped_column(Text)
    requires_configuration: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    template_version: Mapped[V2TemplateVersion] = relationship(back_populates="external_gates")
    task_links: Mapped[list[V2TemplateExternalGateTask]] = relationship(back_populates="gate")


class V2TemplateExternalGateTask(Base):
    __tablename__ = "v2_template_external_gate_tasks"
    __table_args__ = (
        UniqueConstraint("gate_id", "template_task_id", name="uq_v2_template_external_gate_tasks_pair"),
        Index("ix_v2_template_external_gate_tasks_gate", "gate_id"),
        Index("ix_v2_template_external_gate_tasks_task", "template_task_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{V2_SCHEMA}.v2_template_external_gates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    template_task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{V2_SCHEMA}.v2_template_tasks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    gate: Mapped[V2TemplateExternalGate] = relationship(back_populates="task_links")
    template_task: Mapped[V2TemplateTask] = relationship(back_populates="gate_links")
