-- Phase 3 (3c): external-approval status-check overlay - an advisory,
-- append-only record of the assignee's self-reported health
-- ('on_track'/'blocked'/'need_help') against a `project_external_approvals`
-- row, independent of `ProjectExternalApproval.status`.
--
-- This is the direct structural analog of the BLOCKED-overlay decision
-- already applied to tasks (`siteops_v2.task_blockers`): it must never
-- become a lifecycle status, never touch `EXTERNAL_APPROVAL_STATUSES`, and
-- is never read by the formal assign/submit/decide state machine
-- (`project_gate_assignment.py`, `project_gate_decision.py`).
--
-- Append-only, mirroring `siteops_v2.task_delay_events`: every check is
-- kept as its own row, never overwritten or deleted.

create table if not exists siteops_v2.project_external_approval_status_checks (
  id uuid primary key default gen_random_uuid(),
  approval_id uuid not null references siteops_v2.project_external_approvals(id) on delete restrict,
  project_id uuid not null references siteops_v2.projects(id) on delete restrict,
  health text not null check (health in ('on_track', 'blocked', 'need_help')),
  note text,
  recorded_by uuid not null references users(id) on delete restrict,
  recorded_at timestamptz not null default now()
);
create index if not exists ix_v2_project_external_approval_status_checks_approval_recorded
  on siteops_v2.project_external_approval_status_checks(approval_id, recorded_at desc);
revoke all on table siteops_v2.project_external_approval_status_checks from anon, authenticated;
