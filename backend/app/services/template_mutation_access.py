"""Authorization and invariant guards shared by Phase 2 template mutations.

No public mutation routes are defined here. Future command endpoints should depend
on ``require_template_mutator`` and re-check draft/version invariants in their
command service before writing.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status

from app.auth import require_roles
from app.models import User, UserRole


require_template_mutator = require_roles(UserRole.super_admin)


def require_template_mutation_access(actor: User) -> User:
    """Allow only an active Super Admin to mutate template aggregates."""
    if actor.role != UserRole.super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission for this action.",
        )
    return actor


def stable_template_version_not_found() -> HTTPException:
    """Return the stable not-found response used by all mutation services."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Template version not found.",
    )


def require_draft_template_version(version: Any) -> Any:
    """Reject missing and non-draft versions without permitting mutation."""
    if version is None:
        raise stable_template_version_not_found()
    if version.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "template_version_immutable",
                "message": "Only draft template versions may be modified.",
                "version_id": str(version.id),
                "status": version.status,
            },
        )
    return version


def concurrency_token(version: Any) -> str:
    """Return the best available aggregate concurrency token.

    Phase 1 has no explicit revision column. ``updated_at`` is therefore the
    current token. Every future child mutation must call ``touch_version`` in
    the same transaction so that this remains an aggregate-level token.
    """
    value = version.updated_at
    if value is None:
        raise RuntimeError("Template version has no updated_at concurrency token.")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalise_token(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def require_current_concurrency_token(version: Any, expected_token: str) -> Any:
    """Raise a structured 409 when a client submits a stale update token."""
    current = concurrency_token(version)
    if _normalise_token(expected_token) != current:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "stale_template_version",
                "message": "The draft changed after it was loaded. Reload and retry.",
                "version_id": str(version.id),
                "expected_token": expected_token,
                "current_token": current,
            },
        )
    return version


def touch_version(version: Any, *, at: datetime | None = None) -> str:
    """Advance the aggregate token after a successful draft mutation."""
    version.updated_at = at or datetime.now(timezone.utc)
    return concurrency_token(version)
