-- 45-day scheduling POC integration, U3: instantiate external approvals
-- into the execution layer at activation.
--
-- Until now `project_external_gates` was the only gate record, and it is a
-- planning-layer table - Draft-time scope, frozen once the project goes
-- active. There was nothing in the execution layer to approve, which is
-- why an approval could be recorded and release no work.
--
-- NOTE ON CONSTRAINT NAMING. Every check here is declared with an explicit
-- name. 202607290005 and 202607290008 declared theirs inline and unnamed,
-- Postgres auto-named them, and the migrations that later tried to relax
-- those rules dropped names that only ever existed in the ORM - see the
-- header of 202608120001. Do not repeat that here.

BEGIN;

create table if not exists siteops_v2.execution_gates (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references siteops_v2.projects(id) on delete restrict,
    baseline_id uuid not null references siteops_v2.project_baselines(id) on delete restrict,
    project_gate_id uuid references siteops_v2.project_external_gates(id) on delete restrict,
    original_code text not null,
    approval_name text not null,
    external_party text,
    required_by_at timestamptz,
    status text not null default 'pending_review',
    status_recorded_by_user_id uuid references public.users(id) on delete restrict,
    status_recorded_at timestamptz,
    blocking boolean not null default true,
    mapping_classification text,
    accountable_pm_user_id uuid not null references public.users(id) on delete restrict,
    created_at timestamptz not null default now(),
    -- Re-runnability of the backfill depends on this key, not on the
    -- backfill being careful. A duplicate gate row is invisible in the UI
    -- and would leave a twin still blocking after a PM approves the first.
    constraint uq_v2_execution_gates_project_code unique (project_id, original_code),
    constraint ck_v2_execution_gates_status
      check (status in ('not_required', 'pending_review', 'submitted', 'approved', 'rejected'))
);

create index if not exists ix_v2_execution_gates_project
  on siteops_v2.execution_gates(project_id);
create index if not exists ix_v2_execution_gates_project_status
  on siteops_v2.execution_gates(project_id, status);

create table if not exists siteops_v2.execution_gate_tasks (
    id uuid primary key default gen_random_uuid(),
    execution_gate_id uuid not null references siteops_v2.execution_gates(id) on delete cascade,
    task_id uuid not null references siteops_v2.tasks(id) on delete restrict,
    created_at timestamptz not null default now(),
    constraint uq_v2_execution_gate_tasks_pair unique (execution_gate_id, task_id)
);

create index if not exists ix_v2_execution_gate_tasks_gate
  on siteops_v2.execution_gate_tasks(execution_gate_id);
create index if not exists ix_v2_execution_gate_tasks_task
  on siteops_v2.execution_gate_tasks(task_id);

-- Edges dropped at baseline lock because their predecessor was excluded
-- from scope. Baseline lock keeps only edges with both endpoints included,
-- so without this the successor silently looks unblocked. Recording them
-- lets readiness name the exclusion as an advisory reason. Deliberately
-- NOT a task_dependencies row: that would change what the transition guard
-- permits, on edges nobody has validated against real site practice yet.
create table if not exists siteops_v2.execution_excluded_dependencies (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references siteops_v2.projects(id) on delete restrict,
    baseline_id uuid not null references siteops_v2.project_baselines(id) on delete restrict,
    successor_task_id uuid not null references siteops_v2.tasks(id) on delete restrict,
    excluded_predecessor_code text not null,
    excluded_predecessor_title text,
    dependency_type text not null,
    blocking boolean not null default true,
    rule_text text,
    created_at timestamptz not null default now(),
    constraint uq_v2_execution_excluded_dependencies_edge
      unique (project_id, successor_task_id, excluded_predecessor_code, dependency_type),
    constraint ck_v2_execution_excluded_dependencies_type
      check (dependency_type in ('finish_to_start', 'start_to_start'))
);

create index if not exists ix_v2_execution_excluded_dependencies_successor
  on siteops_v2.execution_excluded_dependencies(successor_task_id);

revoke all on siteops_v2.execution_gates from anon, authenticated;
revoke all on siteops_v2.execution_gate_tasks from anon, authenticated;
revoke all on siteops_v2.execution_excluded_dependencies from anon, authenticated;

COMMIT;
