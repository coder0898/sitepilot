-- U6: Task-level accountability, support assignment, and controlled
-- reassignment (BR-004 through BR-007 / R6, R7).
--
-- task_support_assignments / support_assignment_changes: Supervisor
-- controls support for `work` tasks, PM controls follow-up support for
-- `approval_gate` tasks (BR-005). Accountability itself is never stored
-- here or anywhere new - it stays derived from siteops_v2.project_memberships
-- per BR-004/Key Technical Decisions.
--
-- project_role_changes: the two-step (request + approval) PM/Supervisor
-- reassignment flow (BR-007), replacing today's immediate
-- assign_membership() change for those two accountable roles.
--
-- Also closes a document-review-flagged gap: a DB-level partial unique
-- index directly on project_memberships enforcing at most one active
-- ('ends_at is null') project_manager and one active site_supervisor per
-- project. NOTE: 202607240001_v2_project_management.sql already created
-- two equivalent partial unique indexes (uq_v2_active_project_manager,
-- uq_v2_active_site_supervisor) that enforce this exact invariant at the
-- DB level today. This migration additionally creates the single combined
-- index named/shaped exactly as specified by the U6 plan/todo
-- (uq_v2_project_memberships_one_active_role) so the invariant is also
-- expressed in the form the plan calls for; both sets of indexes are
-- harmless to have simultaneously (`if not exists`, and Postgres allows
-- redundant partial unique indexes on the same columns/predicate shape).

create table if not exists siteops_v2.task_support_assignments (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references siteops_v2.tasks(id) on delete restrict,
  project_id uuid not null references siteops_v2.projects(id) on delete restrict,
  employee_id uuid not null references employee_profiles(id) on delete restrict,
  responsibility text not null,
  status text not null default 'active',
  starts_at timestamptz not null default now(),
  ends_at timestamptz,
  assigned_by uuid not null references users(id) on delete restrict,
  created_at timestamptz not null default now(),
  constraint ck_v2_task_support_assignments_status check (status in ('active', 'ended')),
  constraint ck_v2_task_support_assignments_status_ends_at_pair check (
    (status = 'active' and ends_at is null) or (status = 'ended' and ends_at is not null)
  )
);
create index if not exists ix_v2_task_support_assignments_task on siteops_v2.task_support_assignments(task_id);
create index if not exists ix_v2_task_support_assignments_project on siteops_v2.task_support_assignments(project_id);
create index if not exists ix_v2_task_support_assignments_employee on siteops_v2.task_support_assignments(employee_id);
-- BR-005 "unique active assignment per task/employee": an employee cannot
-- hold a second concurrently-active (ends_at is null) support assignment
-- on the same task.
create unique index if not exists uq_v2_task_support_assignments_active_task_employee
  on siteops_v2.task_support_assignments(task_id, employee_id)
  where ends_at is null;
revoke all on table siteops_v2.task_support_assignments from anon, authenticated;

create table if not exists siteops_v2.support_assignment_changes (
  id uuid primary key default gen_random_uuid(),
  task_support_assignment_id uuid not null references siteops_v2.task_support_assignments(id) on delete restrict,
  previous_employee_id uuid references employee_profiles(id) on delete restrict,
  replacement_employee_id uuid references employee_profiles(id) on delete restrict,
  reason_code text not null,
  reason_detail text,
  changed_by uuid not null references users(id) on delete restrict,
  created_at timestamptz not null default now()
);
create index if not exists ix_v2_support_assignment_changes_assignment on siteops_v2.support_assignment_changes(task_support_assignment_id);
revoke all on table siteops_v2.support_assignment_changes from anon, authenticated;

create table if not exists siteops_v2.project_role_changes (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references siteops_v2.projects(id) on delete restrict,
  role_type text not null check (role_type in ('project_manager', 'site_supervisor')),
  previous_membership_id uuid references siteops_v2.project_memberships(id) on delete restrict,
  replacement_employee_id uuid not null references employee_profiles(id) on delete restrict,
  change_type text not null default 'replacement' check (change_type in ('replacement', 'temporary')),
  reason_code text not null,
  reason_detail text,
  status text not null default 'pending' check (status in ('pending', 'approved', 'rejected')),
  requested_by uuid not null references users(id) on delete restrict,
  requested_at timestamptz not null default now(),
  decided_by uuid references users(id) on delete restrict,
  decided_at timestamptz,
  effective_from timestamptz,
  effective_to timestamptz,
  created_at timestamptz not null default now(),
  constraint ck_v2_project_role_changes_decision_pair check (
    (status = 'pending' and decided_by is null and decided_at is null)
    or (status in ('approved', 'rejected') and decided_by is not null and decided_at is not null)
  )
);
create index if not exists ix_v2_project_role_changes_project on siteops_v2.project_role_changes(project_id);
create index if not exists ix_v2_project_role_changes_project_status on siteops_v2.project_role_changes(project_id, status);
-- At most one pending role-change request per project/role at a time -
-- prevents two conflicting in-flight replacement requests for the same
-- accountable role.
create unique index if not exists uq_v2_project_role_changes_one_pending_per_role
  on siteops_v2.project_role_changes(project_id, role_type)
  where status = 'pending';
revoke all on table siteops_v2.project_role_changes from anon, authenticated;

-- Document-review-flagged gap: express "at most one active PM and one
-- active Supervisor per project" as a single combined partial unique
-- index on project_memberships, matching the exact shape the U6 plan
-- specifies. See note above - this is in addition to, not a replacement
-- for, the two indexes already created in
-- 202607240001_v2_project_management.sql.
create unique index if not exists uq_v2_project_memberships_one_active_role
  on siteops_v2.project_memberships(project_id, project_role)
  where ends_at is null and project_role in ('project_manager', 'site_supervisor');
