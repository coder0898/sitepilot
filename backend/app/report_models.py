"""Phase 3 U3: versioned daily/weekly report snapshots (R5/R6, BR-016).

A dedicated module (not `execution_models.py`) since a report snapshot is a
read-side artifact over U1's aggregation, not part of the execution-layer
task graph itself.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.project_models import V2_SCHEMA

REPORT_TYPES = ("daily", "weekly")


class ReportSnapshot(Base):
    __tablename__ = "report_snapshots"
    __table_args__ = (
        CheckConstraint(f"report_type in {REPORT_TYPES!r}", name="ck_v2_report_snapshots_report_type"),
        CheckConstraint("version_no > 0", name="ck_v2_report_snapshots_version_positive"),
        CheckConstraint("period_end > period_start", name="ck_v2_report_snapshots_period"),
        UniqueConstraint(
            "project_id", "report_type", "period_start", "period_end", "version_no",
            name="uq_v2_report_snapshots_period_version",
        ),
        Index("ix_v2_report_snapshots_project", "project_id", "report_type", "period_start"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False)
    report_type: Mapped[str] = mapped_column(Text, nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    generated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
