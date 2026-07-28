"""Reusable role policy for read-only V2 template access."""
from __future__ import annotations

from fastapi import HTTPException, status

from app.auth import require_roles
from app.models import User, UserRole


TEMPLATE_READER_ROLES = (
    UserRole.super_admin,
    UserRole.admin,
    UserRole.project_manager,
)
TEMPLATE_VERSION_STATUSES = frozenset({"draft", "published", "archived"})
TEMPLATE_ALLOWED_STATUSES = {
    UserRole.super_admin: frozenset({"draft", "published"}),
    UserRole.admin: frozenset({"published"}),
    UserRole.project_manager: frozenset({"published"}),
}

# Future API routes can use this dependency directly. Authentication remains
# owned by current_user through the existing require_roles implementation.
require_template_reader = require_roles(*TEMPLATE_READER_ROLES)


def template_role(role_or_user: UserRole | User) -> UserRole:
    return role_or_user.role if isinstance(role_or_user, User) else role_or_user


def require_template_module_access(role_or_user: UserRole | User) -> UserRole:
    role = template_role(role_or_user)
    if role not in TEMPLATE_ALLOWED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission for this action.",
        )
    return role


def allowed_template_statuses(role_or_user: UserRole | User) -> frozenset[str]:
    role = require_template_module_access(role_or_user)
    return TEMPLATE_ALLOWED_STATUSES[role]


def effective_template_statuses(
    role_or_user: UserRole | User,
    requested_statuses: set[str] | frozenset[str] | None = None,
) -> frozenset[str]:
    """Intersect requested filters with role visibility without revealing rows."""
    allowed = allowed_template_statuses(role_or_user)
    if requested_statuses is None:
        return allowed
    unknown = set(requested_statuses) - TEMPLATE_VERSION_STATUSES
    if unknown:
        raise ValueError(f"Unsupported template status filter: {', '.join(sorted(unknown))}.")
    return frozenset(set(requested_statuses) & set(allowed))


def published_template_statuses(role_or_user: UserRole | User) -> frozenset[str]:
    """Return a reusable published-only filter after the module role check."""
    require_template_module_access(role_or_user)
    return frozenset({"published"})

# Phase 2 mutation authorization is intentionally separate from read visibility.
# Re-exported here for discoverability while preserving all Phase 1 behavior.
from app.services.template_mutation_access import require_template_mutator  # noqa: E402,F401
