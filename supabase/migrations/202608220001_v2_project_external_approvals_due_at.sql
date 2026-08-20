-- Phase 5: external-approval due dates.
--
-- Adds a nullable `due_at` date to `project_external_approvals`, resolved at
-- activation (and by a one-off backfill for already-activated projects) from
-- the planning-layer gate's `required_by_type`/`required_by_value`
-- (`backend/app/services/project_gate_due_date.py`).
--
-- Deliberately nullable with no CHECK constraint: a gate whose
-- `required_by_type` is null (never set) or unresolvable (`project_day` with
-- no `project.start_date` yet) legitimately has no due date. Inventing one
-- would be worse than leaving it null - see the resolver's own docstring.

alter table siteops_v2.project_external_approvals
  add column if not exists due_at date;

create index if not exists ix_v2_project_external_approvals_due_at
  on siteops_v2.project_external_approvals(due_at)
  where due_at is not null;
