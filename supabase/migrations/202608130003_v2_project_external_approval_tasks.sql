-- U8: which execution tasks each external approval covers.
--
-- The execution-layer mirror of siteops_v2.project_external_gate_tasks, which
-- points at planning-layer project_tasks. Activation maps each of those links
-- through to the instantiated tasks row and records the result here, so
-- readiness can answer "which tasks does this ungranted approval block?"
-- without ever reading the planning tables (KTD8).
--
-- Rows exist only where coverage was resolvable from the template's explicit
-- task references. An approval whose coverage is prose or absent carries
-- coverage_state = 'unresolved' and has no rows here - which is why that
-- state is a stored column on the approval rather than something inferred
-- from the absence of links in this table. Absence here is ambiguous;
-- the column is not.
--
-- project_id is denormalised from the approval, as on task_dependencies, so a
-- project's whole coverage set is one indexed read rather than a join.

begin;

create table if not exists siteops_v2.project_external_approval_tasks (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references siteops_v2.projects(id) on delete restrict,
  approval_id uuid not null references siteops_v2.project_external_approvals(id) on delete cascade,
  task_id uuid not null references siteops_v2.tasks(id) on delete restrict,
  created_at timestamptz not null default now()
);

-- An approval covers a task once. Re-running instantiation must not be able
-- to double-link, independently of the service's own skip-if-present guard.
alter table siteops_v2.project_external_approval_tasks
  drop constraint if exists uq_v2_project_external_approval_tasks_pair;
alter table siteops_v2.project_external_approval_tasks
  add constraint uq_v2_project_external_approval_tasks_pair unique (approval_id, task_id);

-- Readiness walks this both ways: given an approval, which tasks does it
-- block, and given a task, which approvals are still pending against it.
create index if not exists ix_v2_project_external_approval_tasks_approval
  on siteops_v2.project_external_approval_tasks(approval_id);
create index if not exists ix_v2_project_external_approval_tasks_task
  on siteops_v2.project_external_approval_tasks(task_id);
create index if not exists ix_v2_project_external_approval_tasks_project
  on siteops_v2.project_external_approval_tasks(project_id);

revoke all on table siteops_v2.project_external_approval_tasks from anon, authenticated;

commit;
