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


class ProjectVendor(Base):
    """Phase 2 U2: a vendor mapped to a project (R2).

    Only a `V2Vendor` with `status == 'active'` may be mapped
    (`ProjectVendorService.map_vendor`). A `sub_vendor` additionally
    requires its `parent_vendor_id` to already have its own active mapping
    to the *same* project - that rule spans two rows (this vendor's mapping
    candidacy and its parent's existing mapping), so it is enforced in the
    service layer rather than as a single-row CHECK constraint.

    No `ended_at`/status column: this unit only adds mappings, it does not
    build an unmapping flow, so a row's mere existence is what "actively
    mapped" means for now (including for the sub-vendor parent check
    above).
    """

    __tablename__ = "project_vendors"
    __table_args__ = (
        UniqueConstraint("project_id", "vendor_id", name="uq_v2_project_vendors_project_vendor"),
        Index("ix_v2_project_vendors_project", "project_id"),
        Index("ix_v2_project_vendors_vendor", "vendor_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.vendors.id", ondelete="RESTRICT"), nullable=False
    )
    mapped_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TaskVendorAssignment(Base):
    """Phase 2 U2: a vendor delegated to an execution-layer task (R3).

    A pure delegation record - it never transfers or alters Site Supervisor
    accountability (Phase 1 U6's accountability resolution stays entirely
    independent of this table's existence) and never itself satisfies or
    affects a `TaskDependency` blocking check. `TaskVendorAssignmentService`
    requires the vendor to already be `ProjectVendor`-mapped to the task's
    project, to be `status == 'active'`, and (when the task has a
    `category`) to hold a matching `V2VendorCapability` by category name.

    `status` starts at `pending_ack` on every insert here; `acknowledged`
    and `declined` are reserved for a later unit's vendor-acknowledgement
    flow - this unit does not transition this column after creation.
    """

    __tablename__ = "task_vendor_assignments"
    __table_args__ = (
        CheckConstraint(
            "status in ('pending_ack', 'acknowledged', 'declined')",
            name="ck_v2_task_vendor_assignments_status",
        ),
        Index("ix_v2_task_vendor_assignments_task", "task_id"),
        Index("ix_v2_task_vendor_assignments_project", "project_id"),
        Index("ix_v2_task_vendor_assignments_vendor", "vendor_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Note: no direct FK class import from app.execution_models needed here -
    # this references the `siteops_v2.tasks` table by schema-qualified name
    # only, keeping this module's import surface limited to app.vendor_models
    # + app.project_models (see the "no accountability import" R3 proof).
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.tasks.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.vendors.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending_ack")
    assigned_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class VendorAcknowledgement(Base):
    """Phase 2 U3: a recorded vendor response to a `TaskVendorAssignment`
    (R4).

    Append-only: every response - 'accepted', 'declined', or
    'clarification_requested' - is kept as its own row, even across
    multiple attempts on the same assignment (a clarification request may
    be followed by a later acceptance; neither row is overwritten or
    deleted). Only `VendorAcknowledgementService.record_acknowledgement`
    transitions the parent `TaskVendorAssignment.status`, and only for the
    two terminal responses ('accepted' -> 'acknowledged', 'declined' ->
    'declined'); 'clarification_requested' never changes it.

    `channel` defaults to 'portal' because this unit's route is PM-
    submitted only (R4 - there is no vendor-identity auth here, the PM
    records on the vendor's behalf), but the column is not restricted to
    that value so a later unit's WhatsApp inbound-matching flow can append
    rows with channel = 'whatsapp' without a schema change.
    """

    __tablename__ = "vendor_acknowledgements"
    __table_args__ = (
        CheckConstraint(
            "response in ('accepted', 'declined', 'clarification_requested')",
            name="ck_v2_vendor_acknowledgements_response",
        ),
        CheckConstraint(
            "channel in ('portal', 'whatsapp', 'system')", name="ck_v2_vendor_acknowledgements_channel",
        ),
        Index("ix_v2_vendor_acknowledgements_assignment", "task_vendor_assignment_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_vendor_assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.task_vendor_assignments.id", ondelete="RESTRICT"), nullable=False
    )
    response: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False, default="portal")
    note: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class VendorActivityEvent(Base):
    """Phase 2 U3: vendor-attributable activity/incident capture (R5).

    Logs one `event_type` ('presence', 'delay', 'rework', or 'incident')
    against a specific `TaskVendorAssignment` - so it is always task+vendor
    scoped, never a bare project- or vendor-level note. `description` is
    required; `responsibility_decision` is optional free text, used mainly
    for 'delay'-type events per the plan. Evidence (0 or 1 file) is linked
    separately via `VendorActivityEvidence` and is optional for every
    event_type, including 'incident'.
    """

    __tablename__ = "vendor_activity_events"
    __table_args__ = (
        CheckConstraint(
            "event_type in ('presence', 'delay', 'rework', 'incident')",
            name="ck_v2_vendor_activity_events_event_type",
        ),
        Index("ix_v2_vendor_activity_events_assignment", "task_vendor_assignment_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_vendor_assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.task_vendor_assignments.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    responsibility_decision: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class VendorActivityEvidence(Base):
    """Phase 2 U3: real FK link between a `VendorActivityEvent` and an
    uploaded `FileObject` (`app.execution_models`) - deliberately NOT a
    polymorphic entity_type/entity_id reference, mirroring `TaskEvidence`'s
    link between `TaskProgressUpdate` and `FileObject`."""

    __tablename__ = "vendor_activity_evidence"
    __table_args__ = (
        UniqueConstraint(
            "vendor_activity_event_id", "file_id", name="uq_v2_vendor_activity_evidence_event_file",
        ),
        Index("ix_v2_vendor_activity_evidence_event", "vendor_activity_event_id"),
        Index("ix_v2_vendor_activity_evidence_file", "file_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_activity_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.vendor_activity_events.id", ondelete="RESTRICT"), nullable=False
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.file_objects.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
