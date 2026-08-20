-- Phase 3 (3a): task readiness declarations - an advisory, append-only
-- record of a project member's self-reported readiness against a task
-- ('ready', 'issue', or 'need_help'), independent of `Task.lifecycle_status`.
--
-- This is deliberately NOT read by `task_readiness.py`, which stays a pure
-- derived projection over already-persisted facts (approvals, dependencies)
-- per that service's own docstring. A readiness declaration is a human's
-- point-in-time signal, not a fact the derived projection is computed from.
--
-- Append-only, mirroring `siteops_v2.task_delay_events`: every declaration
-- is kept as its own row (a task may be declared 'issue' and later 'ready'
-- without either row being overwritten or deleted).

create table if not exists siteops_v2.task_readiness_declarations (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references siteops_v2.tasks(id) on delete restrict,
  project_id uuid not null references siteops_v2.projects(id) on delete restrict,
  declared_by uuid not null references users(id) on delete restrict,
  status text not null check (status in ('ready', 'issue', 'need_help')),
  note text,
  declared_at timestamptz not null default now()
);
create index if not exists ix_v2_task_readiness_declarations_task_declared
  on siteops_v2.task_readiness_declarations(task_id, declared_at desc);
revoke all on table siteops_v2.task_readiness_declarations from anon, authenticated;
