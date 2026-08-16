-- U1 (plan: External Approval Gate Assignment & Evidence Lifecycle): widens
-- project_external_approvals from a single-click pending -> approved|rejected
-- decision into a tracked assign -> submit -> decide workflow.
--
-- WHY: `ProjectGateDecisionService.decide()` let a PM (or Admin fallback)
-- flip an approval straight from 'pending' to 'approved'/'rejected' with no
-- assignment step and no evidence attached - the row recorded who clicked,
-- never what proof justified it. This migration adds the columns the new
-- assign/submit/decide lifecycle needs; the ORM CHECK strings and the
-- services that write these columns are updated alongside it (U2-U5).
--
-- STATUS ENUM: widened from ('pending', 'approved', 'rejected') to
-- ('unassigned', 'assigned', 'submitted', 'approved', 'rejected'). Existing
-- 'pending' rows have no assignee under the old model, so they backfill to
-- 'unassigned' rather than inventing a synthetic assignment - they simply
-- re-enter the new flow at its start.
--
-- REJECTION IS A REAL, BRIEFLY-HELD STATE: `rejected` is written and
-- immediately followed by a second transition back to `assigned` within the
-- same `decide()` call (U5), not skipped straight to `assigned`. Without
-- persisting the intermediate row, the CHECK constraint's rejected branch
-- and the rejection_reason it carries would never actually be exercised.
--
-- rejection_reason: persists across the rejected -> assigned transition
-- (unlike decided_by/decided_at, which reset to null) so the assignee and
-- PM/Supervisor can see why a submission was rejected without querying the
-- audit log directly.

begin;

alter table siteops_v2.project_external_approvals
  add column if not exists assigned_to_user_id uuid references users(id) on delete restrict,
  add column if not exists assigned_by uuid references users(id) on delete restrict,
  add column if not exists assigned_at timestamptz,
  add column if not exists rejection_reason text;

-- Both old constraints are dropped BEFORE the backfill UPDATE, and the new
-- (narrower-vocabulary-but-differently-shaped) ones are only added AFTER
-- it. Neither ordering that keeps a CHECK active throughout works: the old
-- pair only permits ('pending', 'approved', 'rejected'), so writing
-- 'unassigned' trips it; the new pair does not permit 'pending' at all, so
-- adding it before the backfill trips it on every still-'pending' row. The
-- backfill therefore runs in the gap where no status CHECK is active.
alter table siteops_v2.project_external_approvals
  drop constraint if exists ck_v2_project_external_approvals_status;
alter table siteops_v2.project_external_approvals
  drop constraint if exists ck_v2_project_external_approvals_decision_completeness;

-- Any row instantiated under the old model is 'pending' with no assignee.
update siteops_v2.project_external_approvals
  set status = 'unassigned'
  where status = 'pending';

alter table siteops_v2.project_external_approvals
  add constraint ck_v2_project_external_approvals_status
  check (status in ('unassigned', 'assigned', 'submitted', 'approved', 'rejected'));

-- Decided means attributable, same rule as before, re-scoped to the wider
-- enum: unassigned/assigned/submitted are all pre-decision states and must
-- carry no decided_by/decided_at; approved/rejected must carry both.
alter table siteops_v2.project_external_approvals
  add constraint ck_v2_project_external_approvals_decision_completeness
  check (
    (status in ('unassigned', 'assigned', 'submitted') and decided_by is null and decided_at is null)
    or (status in ('approved', 'rejected') and decided_by is not null and decided_at is not null)
  );

-- Every state past 'unassigned' names an assignee - assign() sets it,
-- reassign()/unassign() (U3) either replace or clear it together with the
-- status, and it is never left dangling on a status that implies no one is
-- responsible for the gate.
alter table siteops_v2.project_external_approvals
  drop constraint if exists ck_v2_project_external_approvals_assignment_completeness;
alter table siteops_v2.project_external_approvals
  add constraint ck_v2_project_external_approvals_assignment_completeness
  check (
    (status = 'unassigned' and assigned_to_user_id is null)
    or (status <> 'unassigned' and assigned_to_user_id is not null)
  );

create table if not exists siteops_v2.project_external_approval_submissions (
  id uuid primary key default gen_random_uuid(),
  approval_id uuid not null references siteops_v2.project_external_approvals(id) on delete cascade,
  submitted_by uuid not null references users(id) on delete restrict,
  note text,
  submitted_at timestamptz not null default now()
);

create index if not exists ix_v2_project_external_approval_submissions_approval
  on siteops_v2.project_external_approval_submissions(approval_id);

create table if not exists siteops_v2.project_external_approval_evidence (
  id uuid primary key default gen_random_uuid(),
  submission_id uuid not null references siteops_v2.project_external_approval_submissions(id) on delete cascade,
  file_id uuid not null references siteops_v2.file_objects(id) on delete restrict,
  evidence_type text not null default 'photo',
  caption text,
  created_at timestamptz not null default now()
);

create unique index if not exists uq_v2_project_external_approval_evidence_submission_file
  on siteops_v2.project_external_approval_evidence(submission_id, file_id);
create index if not exists ix_v2_project_external_approval_evidence_submission
  on siteops_v2.project_external_approval_evidence(submission_id);
create index if not exists ix_v2_project_external_approval_evidence_file
  on siteops_v2.project_external_approval_evidence(file_id);

revoke all on table siteops_v2.project_external_approval_submissions from anon, authenticated;
revoke all on table siteops_v2.project_external_approval_evidence from anon, authenticated;

commit;
