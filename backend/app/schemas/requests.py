from datetime import date
import uuid

from pydantic import BaseModel

from app.models import TaskStatus, UserRole


class LoginIn(BaseModel):
    email: str
    password: str


class UserCreateIn(BaseModel):
    name: str
    email: str
    phone: str | None = None
    password: str
    role: UserRole


class UserUpdateIn(BaseModel):
    name: str
    email: str
    phone: str | None = None
    role: UserRole | None = None


class PasswordIn(BaseModel):
    password: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


class ResetRequestIn(BaseModel):
    email: str


class ResetPasswordIn(BaseModel):
    token: str
    password: str


class VendorIn(BaseModel):
    name: str
    category: str
    contact_person: str
    phone: str
    whatsapp: str | None = None
    notes: str | None = None


class VendorContactIn(BaseModel):
    vendor_id: uuid.UUID
    name: str
    designation: str | None = None
    phone: str
    whatsapp: str | None = None
    is_primary: bool = False


class VendorCategoryIn(BaseModel):
    name: str


class ProjectVendorIn(BaseModel):
    project_id: uuid.UUID
    vendor_id: uuid.UUID


class ContractorRelationshipIn(BaseModel):
    main_contractor_id: uuid.UUID
    subcontractor_id: uuid.UUID

class ContractorProfileIn(BaseModel):
    name: str
    engagement_type: str = "main"
    status: str = "active"
    category_ids: list[uuid.UUID]
    email: str | None = None
    address: str | None = None
    gst_number: str | None = None
    notes: str | None = None

class CommunicationLogIn(BaseModel):
    vendor_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    channel: str
    note: str

class ProjectIn(BaseModel):
    name: str
    client_name: str
    site_address: str
    start_date: date
    project_manager_id: uuid.UUID | None = None
    supervisor_id: uuid.UUID


class ProjectUpdateIn(BaseModel):
    name: str
    client_name: str
    site_address: str
    status: str
    project_manager_id: uuid.UUID | None = None
    supervisor_id: uuid.UUID


class TaskAdminIn(BaseModel):
    title: str
    category: str
    description: str | None = None
    supervisor_instruction: str | None = None
    pm_instruction: str | None = None
    proof_required: str | None = None
    dependency_note: str | None = None
    due_date: date
    vendor_id: uuid.UUID | None = None
    admin_note: str | None = None


class ReviewIn(BaseModel):
    action: str
    rejection_reason: str | None = None


class ModulePermissionRow(BaseModel):
    role: UserRole
    module_key: str
    can_view: bool


class ModulePermissionIn(BaseModel):
    permissions: list[ModulePermissionRow]
class ExecutionTemplateTaskIn(BaseModel):
    day_no: int
    title: str
    category: str = "General"
    priority: str = "medium"
    instructions: str | None = None
    materials_required: str | None = None
    material_reminder: bool = False
    reminder_lead_days: int = 1

class ExecutionTemplateIn(BaseModel):
    name: str
    project_type: str
    duration_days: int = 3
    tasks: list[ExecutionTemplateTaskIn]

class ExecutionProjectIn(BaseModel):
    name: str
    client_name: str
    location: str
    project_type: str
    area: str | None = None
    start_date: date
    duration_days: int = 3
    project_manager_id: uuid.UUID | None = None
    supervisor_id: uuid.UUID
    template_id: uuid.UUID | None = None

class ExecutionTaskIn(BaseModel):
    project_id: uuid.UUID
    day_id: uuid.UUID
    title: str
    category: str = "General"
    instructions: str | None = None
    proof_required: str | None = None
    materials_required: str | None = None
    material_reminder: bool = False
    reminder_lead_days: int = 1
    assigned_supervisor_id: uuid.UUID
    assigned_contractor_id: uuid.UUID | None = None
    assigned_subcontractor_id: uuid.UUID | None = None
    priority: str = "medium"

class ExecutionProjectContractorIn(BaseModel):
    project_id: uuid.UUID
    contractor_id: uuid.UUID
    scope: str | None = None




class ExecutionProjectUpdateIn(BaseModel):
    name: str
    client_name: str
    location: str
    area: str | None = None
    status: str = "active"
    project_manager_id: uuid.UUID
    supervisor_id: uuid.UUID

class ExecutionTaskStatusIn(BaseModel):
    status: str

class ExecutionTaskReviewIn(BaseModel):
    action: str
    rejection_reason: str | None = None

class ExecutionTaskDelayReportIn(BaseModel):
    category: str
    reason: str
    proposed_date: date
class ExecutionTaskRescheduleIn(BaseModel):
    scheduled_date: date
    reason: str

