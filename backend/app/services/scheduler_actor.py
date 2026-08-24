"""Plan Phase 8 (Part A) / Phase 9: the acting identity behind a scheduled,
no-human-behind-it process.

Two schedulers (this phase's `weekly_summary_scheduler.py`, and Phase 9's
`meeting_reminder_scheduler.py` soon after) need to call a service that
requires a real `User` for its own access check - `ReportGenerationService.
generate` calls `get_project`, which calls `can_view`, which requires an
`actor: User` - even though nothing a human did triggered the call. Two
existing hand-rolled schedulers (`outbox_scheduler.py`,
`evidence_retention_scheduler.py`) never faced this: `MessageDispatchService.
process_pending` and the evidence-retention sweep operate on rows directly
and call no actor-gated service, so neither scheduler needed an actor at
all. That is an absence of precedent, not evidence against needing one here.

The decision (locked in the plan's "Decisions locked for this build"): reuse
ONE dedicated system `User` row for both schedulers, rather than inventing a
per-service bypass parameter (e.g. an `internal=True` flag threaded through
every actor-gated service) or a second bootstrap flow. Concretely, that
means reusing `seed.py`'s bootstrap Super Admin - looked up the exact same
way `_ensure_super_admin` finds it (`settings.bootstrap_super_admin_email`,
lower-cased and stripped, falling back to the same local default), rather
than minting a new row or a new setting.

Why this is safe:

- `V2AuditEvent.actor_user_id` is nullable (see `project_models.py`), so
  nothing about the audit trail *requires* a real human; the constraint this
  module is actually satisfying is `ReportGenerationService.generate`'s own
  `get_project` call, which needs a real `User` row, not a null.
- `get_project`'s access check (`app.routes.projects_v2.can_view`) grants
  access to `actor.role in {UserRole.super_admin, UserRole.admin}`
  unconditionally, with no project-membership check at all for that role
  pair. The bootstrap Super Admin (`UserRole.super_admin`) therefore passes
  `get_project` for every project without needing a `V2ProjectMembership`
  row of its own - exactly the "any authenticated super_admin/admin-role
  user, no project-specific membership required" shape a system actor
  needs.
- The plan's own "Decisions locked for this build" section already accepts
  that "the bootstrap super-admin will not resolve as a recipient" (it has
  no `EmployeeProfile`) - that is fine here too: this actor is never a
  notification recipient, only the attributed `generated_by`/access-check
  identity on rows a scheduler writes on nobody's behalf.

Deliberately NOT a new migration/bootstrap flow: `seed.py` already
guarantees this row exists on every boot (`ensure_seed_data` ->
`_ensure_super_admin`), so a second bootstrap mechanism here would be
redundant infrastructure for the same row.

`get_system_actor`'s name and signature are the contract Phase 9's
`meeting_reminder_scheduler.py` is expected to import unchanged - do not
rename or add a service-specific variant when that phase lands.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User


def get_system_actor(db: Session) -> User:
    """Resolves the one dedicated system/service-account actor for a
    scheduled pass with no real acting human behind it.

    Mirrors `seed.py`'s `_ensure_super_admin` lookup exactly (same email
    resolution, same lower-cased/stripped comparison) so this always finds
    the same row that boot already guarantees exists - never mints a new
    one, never falls back to a different account.

    Raises `RuntimeError` (not a silent `None`/fabricated actor) if the
    bootstrap Super Admin can't be found - a scheduler pass should fail
    loudly and be caught/logged by its own loop's existing
    swallow-and-log exception handling, never proceed and produce a report
    or reminder attributed to nothing real.
    """
    email = (settings.bootstrap_super_admin_email or "superadmin@siteops.local").strip().lower()
    actor = db.scalar(select(User).where(User.email == email))
    if actor is None:
        raise RuntimeError(
            f"System actor lookup failed: no User found for bootstrap Super Admin email {email!r}. "
            "ensure_seed_data() should have created this row on startup."
        )
    return actor
