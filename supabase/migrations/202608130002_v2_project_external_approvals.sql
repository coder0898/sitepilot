-- U4: the execution-layer external approval record.
--
-- One row per external approval that a project actually has to obtain,
-- instantiated at activation (U8) from the planning-layer gate it names, and
-- decided at runtime (U11). Its status is the runtime question -- has the
-- approval been granted? -- and it is the only place that question is
-- answered.
--
-- WHY A NEW TABLE RATHER THAN A COLUMN ON project_external_gates:
--   * that table's `status` is a Draft-time review marker, written only
--     while the project is still a draft (backend/app/services/
--     project_gate_generation.py) and CHECK-constrained at the ORM layer to
--     'pending_review';
--   * `applicability_state` next to it answers a different question again --
--     does this approval apply to this project at all?
-- Widening either would conflate a planning-time question with a runtime
-- decision and split one approval's state across the planning and execution
-- table families. See KTD3/KTD8 in the plan.
--
-- This migration therefore does NOT touch siteops_v2.project_external_gates:
-- no column is added, altered or dropped there, and no constraint on it is
-- created or removed. That matters beyond tidiness -- some developer
-- machines carry `status_recorded_at` / `status_recorded_by_user_id` on that
-- table plus a widened NOT NULL `status`, all from reverted work that was
-- never pushed, while a fresh clone has none of it. Because nothing here
-- reads or writes that table's shape, both machines get the same result.
-- The only reference to it is the foreign key below, which depends solely on
-- its primary key -- present in every variant.

begin;

create table if not exists siteops_v2.project_external_approvals (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references siteops_v2.projects(id) on delete restrict,
  -- The instantiated-from link, mirroring tasks.baseline_task_id. RESTRICT
  -- rather than the CASCADE the planning layer uses between projects and
  -- gates: a granted approval is an execution record and must not evaporate
  -- because a planning row was removed underneath it.
  project_gate_id uuid not null references siteops_v2.project_external_gates(id) on delete restrict,
  status text not null default 'pending',
  -- Nullable pair: this row exists from activation onward and spends its
  -- early life undecided. The completeness check below keeps them together.
  decided_by uuid references users(id) on delete restrict,
  decided_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- An approval is instantiated exactly once per gate.
create unique index if not exists uq_v2_project_external_approvals_gate
  on siteops_v2.project_external_approvals(project_gate_id);

-- Constraints are added separately rather than inline so a re-run reconciles
-- an existing table instead of skipping it via `create table if not exists`.
alter table siteops_v2.project_external_approvals
  drop constraint if exists ck_v2_project_external_approvals_status;
alter table siteops_v2.project_external_approvals
  add constraint ck_v2_project_external_approvals_status
  check (status in ('pending', 'approved', 'rejected'));

-- Pending means undecided, and decided means attributable. Without this a
-- half-written decision would leave readiness and the audit trail
-- disagreeing about whether anyone actually granted anything.
alter table siteops_v2.project_external_approvals
  drop constraint if exists ck_v2_project_external_approvals_decision_completeness;
alter table siteops_v2.project_external_approvals
  add constraint ck_v2_project_external_approvals_decision_completeness
  check (
    (status = 'pending' and decided_by is null and decided_at is null)
    or (status in ('approved', 'rejected') and decided_by is not null and decided_at is not null)
  );

create index if not exists ix_v2_project_external_approvals_project
  on siteops_v2.project_external_approvals(project_id);
-- Readiness sweeps a project's still-pending approvals on every recompute,
-- so status belongs in the lookup rather than in a filter after it.
create index if not exists ix_v2_project_external_approvals_project_status
  on siteops_v2.project_external_approvals(project_id, status);

revoke all on table siteops_v2.project_external_approvals from anon, authenticated;

commit;
