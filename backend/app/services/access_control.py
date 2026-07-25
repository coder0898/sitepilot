from app.models import UserRole


ROLE_DEFINITIONS = {
    UserRole.super_admin: {
        "label": "Super Admin",
        "summary": "Technical governance, security and administrator access.",
        "capabilities": ["Manage all lower-role accounts", "Review technical access", "Inspect platform health"],
    },
    UserRole.admin: {
        "label": "Admin",
        "summary": "People administration, project setup and operational fallback.",
        "capabilities": ["Manage PM, Supervisor and employee access", "Create projects", "Govern approved templates"],
    },
    UserRole.project_manager: {
        "label": "Project Manager",
        "summary": "Project control, vendors and approval-gate decisions.",
        "capabilities": ["Control assigned projects", "Manage vendors", "Approve Class A and approval-gate work"],
    },
    UserRole.supervisor: {
        "label": "Supervisor",
        "summary": "Accountable site execution, verification and employee support.",
        "capabilities": ["Control site execution", "Assign support employees", "Verify submitted work"],
    },
    UserRole.internal_employee: {
        "label": "Internal Employee",
        "summary": "Delegated task support, updates and evidence submission.",
        "capabilities": ["View assigned support work", "Submit progress updates", "Upload evidence"],
    },
}


def manageable_roles(role: UserRole) -> list[UserRole]:
    if role == UserRole.super_admin:
        return [UserRole.admin, UserRole.project_manager, UserRole.supervisor, UserRole.internal_employee]
    if role == UserRole.admin:
        return [UserRole.project_manager, UserRole.supervisor, UserRole.internal_employee]
    return []


def access_catalog() -> list[dict]:
    return [{"role": role.value, **definition} for role, definition in ROLE_DEFINITIONS.items()]
