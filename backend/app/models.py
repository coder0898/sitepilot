import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserRole(str, enum.Enum):
    super_admin = "super_admin"
    admin = "admin"
    project_manager = "project_manager"
    supervisor = "supervisor"
    internal_employee = "internal_employee"


class TaskStatus(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    submitted = "submitted"
    completed = "completed"
    rejected = "rejected"
    delayed = "delayed"
    blocked = "blocked"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    phone: Mapped[str | None] = mapped_column(Text)
    # Passwords and sessions are owned by Supabase Auth.
    password_hash: Mapped[str | None] = mapped_column(Text)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    supabase_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), unique=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RoleModulePermission(Base):
    __tablename__ = "role_module_permissions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    module_key: Mapped[str] = mapped_column(Text, nullable=False)
    can_view: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class EmployeeProfile(Base):
    __tablename__ = "employee_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    employee_code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    designation: Mapped[str] = mapped_column(Text, nullable=False)
    department: Mapped[str | None] = mapped_column(Text)
    availability: Mapped[str] = mapped_column(Text, nullable=False, default="available")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (CheckConstraint("availability in ('available', 'restricted', 'unavailable')", name="ck_employee_profile_availability"),)


class UserAccountEvent(Base):
    __tablename__ = "user_account_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    from_role: Mapped[str | None] = mapped_column(Text)
    to_role: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class AccessRequest(Base):
    __tablename__ = "access_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str | None] = mapped_column(Text)
    employee_code: Mapped[str] = mapped_column(Text, nullable=False)
    designation: Mapped[str] = mapped_column(Text, nullable=False)
    department: Mapped[str | None] = mapped_column(Text)
    requested_role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role", create_type=False), nullable=False)
    project_reference: Mapped[str | None] = mapped_column(Text)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending_email_verification")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supabase_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (CheckConstraint(
        "status in ('pending_email_verification', 'pending_approval', 'approved', 'rejected', 'expired', 'cancelled')",
        name="ck_access_request_status",
    ),)


class AccessRequestEvent(Base):
    __tablename__ = "access_request_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    access_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("access_requests.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Vendor(Base):
    __tablename__ = "vendors"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    contact_person: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    whatsapp: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    engagement_type: Mapped[str] = mapped_column(Text, nullable=False, default="main")
    parent_vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="RESTRICT"))
    migration_status: Mapped[str] = mapped_column(Text, nullable=False, default="ready")
    email: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    gst_number: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("engagement_type in ('main', 'sub_vendor', 'migration_pending')", name="ck_vendor_engagement_type"),
        CheckConstraint("engagement_type != 'sub_vendor' OR parent_vendor_id IS NOT NULL", name="ck_vendor_sub_vendor_parent"),
        CheckConstraint("engagement_type != 'main' OR parent_vendor_id IS NULL", name="ck_vendor_main_without_parent"),
        CheckConstraint("migration_status in ('ready', 'parent_required')", name="ck_vendor_migration_status"),
        CheckConstraint("engagement_type != 'migration_pending' OR (migration_status = 'parent_required' AND parent_vendor_id IS NULL)", name="ck_vendor_pending_state"),
        CheckConstraint("engagement_type = 'migration_pending' OR migration_status = 'ready'", name="ck_vendor_ready_state"),
    )

class VendorCategory(Base):
    __tablename__ = "vendor_categories"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    category_type: Mapped[str] = mapped_column(Text, nullable=False, default="service")
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendor_categories.id", ondelete="RESTRICT"))
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("category_type in ('material', 'service')", name="ck_vendor_category_type"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_vendor_category_not_self_parent"),
    )

class ContractorCategory(Base):
    __tablename__ = "contractor_categories"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vendor_categories.id", ondelete="CASCADE"), nullable=False)

class VendorContact(Base):
    __tablename__ = "vendor_contacts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    designation: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    whatsapp: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectVendor(Base):
    __tablename__ = "project_vendors"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContractorRelationship(Base):
    __tablename__ = "contractor_relationships"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    main_contractor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False)
    subcontractor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("subcontractor_id", name="uq_contractor_relationship_subcontractor"),)

class VendorStatusHistory(Base):
    __tablename__ = "vendor_status_history"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False)
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class VendorParentMigrationCandidate(Base):
    __table_args__ = (UniqueConstraint("vendor_id", "candidate_parent_vendor_id", name="uq_vendor_parent_migration_candidate"),)
    __tablename__ = "vendor_parent_migration_candidates"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False)
    candidate_parent_vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"))
    original_engagement_type: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class CommunicationLog(Base):
    __tablename__ = "communication_logs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendor_contacts.id", ondelete="SET NULL"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    execution_project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("execution_projects.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    client_name: Mapped[str] = mapped_column(Text, nullable=False)
    site_address: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_handover_date: Mapped[date] = mapped_column(Date, nullable=False)
    project_manager_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    supervisor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tasks: Mapped[list["ProjectTask"]] = relationship(back_populates="project", cascade="all, delete")


class TaskTemplate(Base):
    __tablename__ = "task_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    day_no: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    vendor_category: Mapped[str | None] = mapped_column(Text)
    default_notes: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    supervisor_instruction: Mapped[str | None] = mapped_column(Text)
    pm_instruction: Mapped[str | None] = mapped_column(Text)
    proof_required: Mapped[str | None] = mapped_column(Text)
    dependency_note: Mapped[str | None] = mapped_column(Text)


class ProjectTask(Base):
    __tablename__ = "project_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    template_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("task_templates.id"))
    day_no: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id"))
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus, name="task_status"), nullable=False, default=TaskStatus.pending)
    description: Mapped[str | None] = mapped_column(Text)
    supervisor_instruction: Mapped[str | None] = mapped_column(Text)
    pm_instruction: Mapped[str | None] = mapped_column(Text)
    proof_required: Mapped[str | None] = mapped_column(Text)
    dependency_note: Mapped[str | None] = mapped_column(Text)
    admin_note: Mapped[str | None] = mapped_column(Text)
    supervisor_note: Mapped[str | None] = mapped_column(Text)
    delay_reason: Mapped[str | None] = mapped_column(Text)
    proof_url: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    project: Mapped[Project] = relationship(back_populates="tasks")
    vendor: Mapped[Vendor | None] = relationship()



class ExecutionTemplate(Base):
    __tablename__ = "execution_templates"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    project_type: Mapped[str] = mapped_column(Text, nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ExecutionTemplateTask(Base):
    __tablename__ = "execution_template_tasks"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("execution_templates.id", ondelete="CASCADE"), nullable=False)
    day_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False, default="General")
    category_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendor_categories.id", ondelete="SET NULL"))
    subcategory_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendor_categories.id", ondelete="SET NULL"))
    priority: Mapped[str] = mapped_column(Text, nullable=False, default="medium")
    instructions: Mapped[str | None] = mapped_column(Text)
    materials_required: Mapped[str | None] = mapped_column(Text)
    material_reminder: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reminder_lead_days: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ExecutionProject(Base):
    __tablename__ = "execution_projects"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    client_name: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str] = mapped_column(Text, nullable=False)
    project_type: Mapped[str] = mapped_column(Text, nullable=False)
    area: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    project_manager_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    supervisor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    template_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("execution_templates.id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExecutionDay(Base):
    __tablename__ = "execution_days"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("execution_projects.id", ondelete="CASCADE"), nullable=False)
    day_no: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)


class ExecutionProjectContractor(Base):
    __tablename__ = "execution_project_contractors"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("execution_projects.id", ondelete="CASCADE"), nullable=False)
    contractor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False)
    scope: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExecutionTask(Base):
    __tablename__ = "execution_tasks"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("execution_projects.id", ondelete="CASCADE"), nullable=False)
    day_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("execution_days.id", ondelete="CASCADE"), nullable=False)
    template_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("execution_template_tasks.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False, default="General")
    category_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendor_categories.id", ondelete="SET NULL"))
    subcategory_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendor_categories.id", ondelete="SET NULL"))
    instructions: Mapped[str | None] = mapped_column(Text)
    materials_required: Mapped[str | None] = mapped_column(Text)
    material_reminder: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reminder_lead_days: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    assigned_supervisor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    assigned_contractor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id"))
    assigned_subcontractor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id"))
    priority: Mapped[str] = mapped_column(Text, nullable=False, default="medium")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="assigned")
    proof_url: Mapped[str | None] = mapped_column(Text)
    proof_required: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    remarks: Mapped[str | None] = mapped_column(Text)
    rescheduled_date: Mapped[date | None] = mapped_column(Date)
    delay_reason: Mapped[str | None] = mapped_column(Text)
    rescheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rescheduled_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    reschedule_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ExecutionTaskStatusHistory(Base):
    __tablename__ = "execution_task_status_history"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("execution_tasks.id", ondelete="CASCADE"), nullable=False)
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ExecutionTaskAssignmentHistory(Base):
    __tablename__ = "execution_task_assignment_history"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("execution_tasks.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    from_contractor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="SET NULL"))
    from_subcontractor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="SET NULL"))
    to_contractor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="SET NULL"))
    to_subcontractor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="SET NULL"))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExecutionTaskDelayReport(Base):
    __tablename__ = "execution_task_delay_reports"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("execution_tasks.id", ondelete="CASCADE"), nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class ExecutionTaskReschedule(Base):
    __tablename__ = "execution_task_reschedules"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("execution_tasks.id", ondelete="CASCADE"), nullable=False)
    previous_date: Mapped[date] = mapped_column(Date, nullable=False)
    new_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())




class TaskVendorCategoryMapping(Base):
    __tablename__ = "task_vendor_category_mappings"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_category: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    vendor_category_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendor_categories.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskVendorCategoryMappingAudit(Base):
    __tablename__ = "task_vendor_category_mapping_audit"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_category: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    old_vendor_category_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    new_vendor_category_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
