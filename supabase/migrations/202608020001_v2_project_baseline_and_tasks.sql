-- U1: Baseline lock and execution-layer task/dependency instantiation.
--
-- project_baselines / baseline_tasks are the immutable snapshot captured at
-- project activation (replacing the status-flag-only "lock" that existed
-- before). tasks / task_dependencies are the execution-layer entities
-- instantiated from that snapshot; they are a NEW table pair distinct from
-- siteops_v2.project_tasks (V2ProjectTask), which remains the planning-time
-- table and is not modified by this migration.
--
-- baseline_tasks immutability is enforced at the database level via a
-- trigger that rejects UPDATE/DELETE, not merely by convention. content_hash
-- is a secondary, cheap cross-environment integrity check (mirroring
-- v2_template_versions.content_hash), not the enforcement mechanism itself.

create table if not exists siteops_v2.project_baselines (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references siteops_v2.projects(id) on delete restrict,
  task_count integer not null check (task_count > 0),
  dependency_count integer not null default 0 check (dependency_count >= 0),
  gate_count integer not null default 0 check (gate_count >= 0),
  locked_by uuid not null references users(id) on delete restrict,
  locked_at timestamptz not null default now(),
  constraint uq_v2_project_baselines_project unique (project_id)
);
create index if not exists ix_v2_project_baselines_project on siteops_v2.project_baselines(project_id);
revoke all on table siteops_v2.project_baselines from anon, authenticated;

create table if not exists siteops_v2.baseline_tasks (
  id uuid primary key default gen_random_uuid(),
  baseline_id uuid not null references siteops_v2.project_baselines(id) on delete restrict,
  project_id uuid not null references siteops_v2.projects(id) on delete restrict,
  project_task_id uuid not null references siteops_v2.project_tasks(id) on delete restrict,
  original_code text not null,
  template_sequence integer not null check (template_sequence > 0),
  title text not null,
  description text,
  schedule_classification text not null check (schedule_classification in ('pre_activation','execution')),
  planned_start_day smallint,
  planned_end_day smallint,
  phase text,
  category text,
  applicability text not null check (applicability in ('mandatory','conditional')),
  task_class text check (task_class in ('standard','class_a')),
  task_kind text check (task_kind in ('work','approval_gate','milestone')),
  evidence_required boolean not null default false,
  duration_days integer,
  content_hash text not null,
  created_at timestamptz not null default now(),
  constraint uq_v2_baseline_tasks_baseline_project_task unique (baseline_id, project_task_id),
  constraint uq_v2_baseline_tasks_baseline_code unique (baseline_id, original_code)
);
create index if not exists ix_v2_baseline_tasks_baseline on siteops_v2.baseline_tasks(baseline_id);
create index if not exists ix_v2_baseline_tasks_project on siteops_v2.baseline_tasks(project_id);
revoke all on table siteops_v2.baseline_tasks from anon, authenticated;

-- DB-level immutability enforcement for baseline_tasks: reject any UPDATE or
-- DELETE unconditionally once a row has been written. This is the actual
-- enforcement mechanism per the plan's Key Technical Decisions; content_hash
-- above is only a convenience integrity check, not what prevents tampering.
create or replace function siteops_v2.reject_baseline_task_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception 'baseline_tasks rows are immutable once written (id=%)', coalesce(old.id, new.id)
    using errcode = '23000';
  return null;
end;
$$;

drop trigger if exists trg_v2_baseline_tasks_immutable_update on siteops_v2.baseline_tasks;
create trigger trg_v2_baseline_tasks_immutable_update
  before update on siteops_v2.baseline_tasks
  for each row execute function siteops_v2.reject_baseline_task_mutation();

drop trigger if exists trg_v2_baseline_tasks_immutable_delete on siteops_v2.baseline_tasks;
create trigger trg_v2_baseline_tasks_immutable_delete
  before delete on siteops_v2.baseline_tasks
  for each row execute function siteops_v2.reject_baseline_task_mutation();

-- Execution-layer tasks, instantiated 1:1 from baseline_tasks at activation.
create table if not exists siteops_v2.tasks (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references siteops_v2.projects(id) on delete restrict,
  baseline_id uuid not null references siteops_v2.project_baselines(id) on delete restrict,
  baseline_task_id uuid not null references siteops_v2.baseline_tasks(id) on delete restrict,
  original_code text not null,
  template_sequence integer not null check (template_sequence > 0),
  title text not null,
  description text,
  schedule_classification text not null check (schedule_classification in ('pre_activation','execution')),
  planned_start_day smallint,
  planned_end_day smallint,
  phase text,
  category text,
  applicability text not null check (applicability in ('mandatory','conditional')),
  task_class text check (task_class in ('standard','class_a')),
  task_kind text check (task_kind in ('work','approval_gate','milestone')),
  evidence_required boolean not null default false,
  duration_days integer,
  lifecycle_status text not null default 'planned' check (
    lifecycle_status in (
      'planned','ready','in_progress','submitted','verified',
      'approval_pending','rejected','completed','cancelled'
    )
  ),
  created_from_baseline boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_v2_tasks_project_code unique (project_id, original_code),
  constraint uq_v2_tasks_baseline_task unique (baseline_task_id)
);
create index if not exists ix_v2_tasks_project_sequence on siteops_v2.tasks(project_id, template_sequence);
create index if not exists ix_v2_tasks_baseline on siteops_v2.tasks(baseline_id);
create index if not exists ix_v2_tasks_project_status on siteops_v2.tasks(project_id, lifecycle_status);
revoke all on table siteops_v2.tasks from anon, authenticated;

create table if not exists siteops_v2.task_dependencies (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references siteops_v2.projects(id) on delete restrict,
  baseline_id uuid not null references siteops_v2.project_baselines(id) on delete restrict,
  project_dependency_id uuid references siteops_v2.project_task_dependencies(id) on delete restrict,
  predecessor_task_id uuid not null references siteops_v2.tasks(id) on delete restrict,
  successor_task_id uuid not null references siteops_v2.tasks(id) on delete restrict,
  dependency_type text not null check (dependency_type in ('finish_to_start','start_to_start')),
  blocking boolean not null default true,
  rule_text text,
  created_from_baseline boolean not null default true,
  created_at timestamptz not null default now(),
  constraint uq_v2_task_dependencies_edge unique (project_id, predecessor_task_id, successor_task_id, dependency_type),
  constraint ck_v2_task_dependencies_not_self check (predecessor_task_id <> successor_task_id)
);
create index if not exists ix_v2_task_dependencies_project on siteops_v2.task_dependencies(project_id);
create index if not exists ix_v2_task_dependencies_predecessor on siteops_v2.task_dependencies(predecessor_task_id);
create index if not exists ix_v2_task_dependencies_successor on siteops_v2.task_dependencies(successor_task_id);
revoke all on table siteops_v2.task_dependencies from anon, authenticated;
