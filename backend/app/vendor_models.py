"""Phase 2 U1: V2 vendor/capability models (R1).

Mirrors `supabase/migrations/202608040001_v2_vendors.sql`. See that
migration's header for the modeling rationale (legacy_vendor_id back-ref
for idempotent import, category normalization, parent_vendor_id as the
sole authoritative sub-vendor relationship).

Naming: these are prefixed `V2Vendor*` (not bare `Vendor*`) because
`app.models.Vendor` / `app.models.VendorContact` already exist for the
legacy schema - an unprefixed class name here would collide at the Python
level even though the DB tables themselves don't collide (`siteops_v2.*`
vs. legacy `public.*`). This mirrors the existing `V2Project` / `V2Task`
naming convention used throughout `app.project_models` /
`app.execution_models`.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.project_models import V2_SCHEMA


class V2Vendor(Base):
    __tablename__ = "vendors"
    __table_args__ = (
        UniqueConstraint("legacy_vendor_id", name="uq_v2_vendors_legacy_vendor_id"),
        CheckConstraint("engagement_type in ('main', 'sub_vendor')", name="ck_v2_vendors_engagement_type"),
        CheckConstraint("engagement_type != 'sub_vendor' OR parent_vendor_id IS NOT NULL", name="ck_v2_vendors_sub_vendor_parent"),
        CheckConstraint("engagement_type != 'main' OR parent_vendor_id IS NULL", name="ck_v2_vendors_main_without_parent"),
        Index("ix_v2_vendors_parent", "parent_vendor_id"),
        Index("ix_v2_vendors_status", "status"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Stable external-ID reference back to app.models.Vendor.id - what makes
    # re-running VendorImportService.import_from_legacy idempotent.
    legacy_vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    contact_person: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    whatsapp: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    gst_number: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    engagement_type: Mapped[str] = mapped_column(Text, nullable=False, default="main")
    parent_vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.vendors.id", ondelete="RESTRICT")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class V2CapabilityCategory(Base):
    __tablename__ = "capability_categories"
    __table_args__ = (
        UniqueConstraint("name", name="uq_v2_capability_categories_name"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class V2VendorCapability(Base):
    __tablename__ = "vendor_capabilities"
    __table_args__ = (
        UniqueConstraint("vendor_id", "category_id", name="uq_v2_vendor_capabilities_vendor_category"),
        Index("ix_v2_vendor_capabilities_vendor", "vendor_id"),
        Index("ix_v2_vendor_capabilities_category", "category_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.vendors.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.capability_categories.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class V2VendorContact(Base):
    __tablename__ = "vendor_contacts"
    __table_args__ = (
        Index("ix_v2_vendor_contacts_vendor", "vendor_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.vendors.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    designation: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    whatsapp: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
