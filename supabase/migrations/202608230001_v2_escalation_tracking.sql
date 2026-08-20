-- Phase 6 (first half): escalation-tracking table for `EscalationService`
-- (`backend/app/services/escalation.py`). One row per (entity_type,
-- entity_id, stage) marks that a sweep has already triggered a given
-- escalation stage against a given entity, so repeated sweeps stay
-- idempotent instead of re-tracking/re-emitting on every pass.
--
-- `entity_id` is deliberately NOT a foreign key. It names a row in
-- `siteops_v2.tasks` when `entity_type = 'task'`, or a row in
-- `siteops_v2.project_external_approvals` when
-- `entity_type = 'project_external_approval'` - a genuinely polymorphic
-- reference, since a single column cannot carry two different real FKs at
-- once and there is no shared parent table between those two entities to
-- FK against instead. This is a deliberate one-off exception to this
-- schema's default: `TaskEvidence` (see `backend/app/execution_models.py`)
-- documents that this codebase otherwise avoids polymorphic
-- entity_type/entity_id references in favor of real, typed FK columns.
-- `EscalationService` never trusts `entity_id` alone as truth - every sweep
-- re-derives the referenced entity's live state via its own FK'd query
-- (`tasks`/`project_external_approvals`) before acting on a tracking row.
--
-- Not append-only like the Phase 3 overlay tables (task_readiness_declarations,
-- task_attendance_events, project_external_approval_status_checks): this
-- table's whole purpose is sweep idempotency, not a signal history. Only one
-- OPEN (resolved_at is null) row may exist per (entity_type, entity_id,
-- stage) at a time - `uq_v2_escalation_tracking_entity_stage_open` is
-- deliberately a PARTIAL unique index, not a table-wide one: an entity that
-- escalates, resolves, and later stalls again (a second, unrelated
-- follow-up episode) must be able to get a second row for the same stage.
-- A table-wide unique constraint would permanently block re-escalation
-- after the first resolved row, which is wrong - see
-- `uq_v2_task_support_assignments_active_task_employee`
-- (202608020005_v2_support_assignments_role_changes.sql) for the same
-- "partial unique index, service-layer check does the rest" pattern already
-- used in this schema. As with that table, this partial index is DB-level
-- only and is not mirrored in `EscalationTracking.__table_args__` - the
-- SQLite test harness relies on `EscalationService`'s own open-row check.

create table if not exists siteops_v2.escalation_tracking (
  id uuid primary key default gen_random_uuid(),
  entity_type text not null check (entity_type in ('task', 'project_external_approval')),
  entity_id uuid not null,
  stage text not null check (stage in ('followup', 'admin_escalation')),
  triggered_at timestamptz not null default now(),
  resolved_at timestamptz
);
create unique index if not exists uq_v2_escalation_tracking_entity_stage_open
  on siteops_v2.escalation_tracking(entity_type, entity_id, stage)
  where resolved_at is null;
create index if not exists ix_v2_escalation_tracking_entity on siteops_v2.escalation_tracking(entity_type, entity_id);
revoke all on table siteops_v2.escalation_tracking from anon, authenticated;
