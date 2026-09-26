-- Telegram task-execution plan U2 (KTD2): marks which progress updates a
-- review decision has already covered, so only progress logged after the
-- last decision can satisfy a new submission.
--
-- Before this, "fresh" meant "not named as some verification's
-- submission_update_id". A verification names only the latest update, so
-- the older updates of a rejected cycle (and a rejected file) still counted
-- on resubmission, and PM decisions (class_a and approval_gate tasks)
-- consumed nothing at all. From here on the decision services set
-- reviewed_at on every unreviewed update of the task, for either outcome.
--
-- Backfill: each existing update is marked reviewed at the time of the first
-- verification or approval decision recorded at or after it. Updates logged
-- after a task's latest decision (the cycle currently in progress or
-- awaiting review) stay unreviewed. This is the only place the timestamps
-- are compared; live checks use reviewed_at alone. The statement below is
-- deliberately plain SQL (no update alias) so the regression test can run it
-- as written.

alter table siteops_v2.task_progress_updates
  add column if not exists reviewed_at timestamptz;

update siteops_v2.task_progress_updates
set reviewed_at = (
  select min(decision.decided_at)
  from (
    select task_id, verified_at as decided_at from siteops_v2.task_verifications
    union all
    select task_id, decided_at from siteops_v2.task_approval_decisions
  ) as decision
  where decision.task_id = siteops_v2.task_progress_updates.task_id
    and decision.decided_at >= siteops_v2.task_progress_updates.created_at
)
where reviewed_at is null;
