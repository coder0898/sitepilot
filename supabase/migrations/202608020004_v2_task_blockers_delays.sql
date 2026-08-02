-- U5: Blocker and delay capture (BR-010 / R5).
--
-- task_blockers and task_delay_events are independently queryable
-- conditions against an execution-layer task (siteops_v2.tasks). Per
-- BR-010, "blocked/delayed/overdue/no_update are separate conditions, not
-- mutually exclusive lifecycle states" - neither table has any FK or
-- trigger relationship to tasks.lifecycle_status, and nothing in this
-- migration constrains a task's lifecycle_status based on the presence of
-- an unresolved blocker or a logged delay. `overdue` and `no_update`
-- remain derived at query time from due_at/update_sla_hours - no storage
-- here for those two.

create table if not exists siteops_v2.task_blockers (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references siteops_v2.tasks(id) on delete restrict,
  project_id uuid not null references siteops_v2.projects(id) on delete restrict,
  type text not null,
  description text not null,
  owner_employee_id uuid references employee_profiles(id) on delete restrict,
  started_at timestamptz not null default now(),
  resolved_at timestamptz,
  resolved_by uuid references users(id) on delete restrict,
  created_at timestamptz not null default now(),
  constraint ck_v2_task_blockers_resolution_pair check (
    (resolved_at is null and resolved_by is null) or (resolved_at is not null and resolved_by is not null)
  )
);
create index if not exists ix_v2_task_blockers_task on siteops_v2.task_blockers(task_id);
create index if not exists ix_v2_task_blockers_project on siteops_v2.task_blockers(project_id);
create index if not exists ix_v2_task_blockers_task_unresolved on siteops_v2.task_blockers(task_id) where resolved_at is null;
revoke all on table siteops_v2.task_blockers from anon, authenticated;

-- responsible_vendor_id is a plain nullable uuid column, not an FK, because
-- no vendor V2 table exists yet in this schema (see docs gap noted in the
-- U5 plan section) - adding an FK target here would require inventing a
-- vendors table out of scope for this unit. Application-level validation
-- (backend/app/services/task_delay.py) enforces it is present only when
-- responsibility_type = 'vendor', and null otherwise.
create table if not exists siteops_v2.task_delay_events (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references siteops_v2.tasks(id) on delete restrict,
  project_id uuid not null references siteops_v2.projects(id) on delete restrict,
  responsibility_type text not null check (
    responsibility_type in ('vendor', 'client', 'approval', 'design', 'site_readiness', 'internal', 'other')
  ),
  responsible_vendor_id uuid,
  reason text not null,
  impact_days integer not null check (impact_days > 0),
  recorded_by uuid not null references users(id) on delete restrict,
  created_at timestamptz not null default now(),
  constraint ck_v2_task_delay_events_vendor_id_pairing check (
    (responsibility_type = 'vendor' and responsible_vendor_id is not null)
    or (responsibility_type <> 'vendor' and responsible_vendor_id is null)
  )
);
create index if not exists ix_v2_task_delay_events_task on siteops_v2.task_delay_events(task_id);
create index if not exists ix_v2_task_delay_events_project on siteops_v2.task_delay_events(project_id);
revoke all on table siteops_v2.task_delay_events from anon, authenticated;
