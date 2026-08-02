-- U4: Supervisor verification and PM approval decisions (BR-008).
--
-- task_verifications applies only to `work` tasks - approval_gate tasks
-- skip Supervisor verification entirely per BR-008 ("For an approval_gate,
-- the PM approves or rejects submitted evidence directly; Supervisor
-- verification is not required"). submission_update_id links the decision
-- back to the task_progress_updates row (U3) that was being verified.
--
-- task_approval_decisions is required for every `class_a` work task (after
-- Supervisor verification) and every `approval_gate` task (directly, no
-- verification prerequisite). verification_id is populated for Class A
-- work, null for gates.

create table if not exists siteops_v2.task_verifications (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references siteops_v2.tasks(id) on delete restrict,
  submission_update_id uuid not null references siteops_v2.task_progress_updates(id) on delete restrict,
  decision text not null check (decision in ('verified', 'rejected')),
  remarks text,
  verified_by uuid not null references users(id) on delete restrict,
  verified_at timestamptz not null default now()
);
create index if not exists ix_v2_task_verifications_task on siteops_v2.task_verifications(task_id);
create index if not exists ix_v2_task_verifications_task_verified_at on siteops_v2.task_verifications(task_id, verified_at);
revoke all on table siteops_v2.task_verifications from anon, authenticated;

create table if not exists siteops_v2.task_approval_decisions (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references siteops_v2.tasks(id) on delete restrict,
  verification_id uuid references siteops_v2.task_verifications(id) on delete restrict,
  decision text not null check (decision in ('approved', 'rejected')),
  remarks text,
  decided_by uuid not null references users(id) on delete restrict,
  decided_at timestamptz not null default now()
);
create index if not exists ix_v2_task_approval_decisions_task on siteops_v2.task_approval_decisions(task_id);
create index if not exists ix_v2_task_approval_decisions_task_decided_at on siteops_v2.task_approval_decisions(task_id, decided_at);
revoke all on table siteops_v2.task_approval_decisions from anon, authenticated;
