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
    password: str
    role: UserRole


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


class ProjectIn(BaseModel):
    name: str
    client_name: str
    site_address: str
    start_date: date
    project_manager_id: uuid.UUID
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
