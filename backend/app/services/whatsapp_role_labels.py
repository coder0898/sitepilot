"""Phase 2: canonical WhatsApp-facing role labels (R15).

`UserRole.supervisor` (the account-level enum in `app.models`) and
`V2ProjectMembership.project_role == "site_supervisor"` (the
membership-level string in `app.project_models`) are two different string
spellings for the same real-world role. Reconciling them with a rename
would touch every table/query keyed on either spelling for no functional
gain - this module exists instead so any WhatsApp template variable like
`{{role}}` renders one consistent label regardless of which underlying
spelling backed the value it was built from.

This promotes `broadcast_service.py`'s existing `GROUP_ROLE_LABEL` dict (a
project-role-only lookup used for broadcast recipient grouping) into a
shared helper that also covers the account-level `UserRole` enum, so
task/approval/gate dispatch code (which more often has a `User.role`
on hand than a `project_role` string) can resolve the same labels.
"""

from __future__ import annotations

from app.models import UserRole

_LABEL_BY_PROJECT_ROLE: dict[str, str] = {
    "project_manager": "Project Manager",
    "site_supervisor": "Site Supervisor",
    "internal_employee": "Internal Employee",
}

_LABEL_BY_ACCOUNT_ROLE: dict[UserRole, str] = {
    UserRole.super_admin: "Super Admin",
    UserRole.admin: "Admin",
    UserRole.project_manager: "Project Manager",
    UserRole.supervisor: "Site Supervisor",
    UserRole.internal_employee: "Internal Employee",
}

_FALLBACK_LABEL = "Team Member"


def whatsapp_role_label(*, project_role: str | None = None, account_role: UserRole | None = None) -> str:
    """One canonical human-facing role label for WhatsApp template
    variables. `project_role` (the project-membership spelling) takes
    precedence when both are supplied, since it's the more specific,
    project-context-relevant value for a message about a particular
    project; `account_role` is the fallback for callers that only have a
    `User.role` on hand (e.g. resolving Admin/super_admin, which never
    appears as a `project_role`). Neither underlying enum/string is
    modified - this is purely a rendering-time reconciliation."""
    if project_role is not None:
        label = _LABEL_BY_PROJECT_ROLE.get(project_role)
        if label is not None:
            return label
    if account_role is not None:
        label = _LABEL_BY_ACCOUNT_ROLE.get(account_role)
        if label is not None:
            return label
    return _FALLBACK_LABEL
