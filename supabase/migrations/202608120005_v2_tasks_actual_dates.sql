-- 45-day scheduling POC integration, U5: record when work really started
-- and really finished.
--
-- U4 gave every task its planned start and target finish. These are the
-- other half of planned-versus-actual: without them the portal knows what
-- was supposed to happen and has no record of what did.
--
-- Both are written from the task's own lifecycle transitions rather than
-- being entered by anyone - actual_start on the first move into
-- in_progress, actual_finish on the move into completed - so they are
-- observations, not claims.
--
-- Nullable, and deliberately not backfilled. A task that has never started
-- has no actual start, and a task completed before this migration has no
-- recoverable actual finish: the TASK_STATUS_CHANGED audit trail remains
-- the provenance record for those. Nothing downstream treats a null here
-- as "today" - a terminal task with no actual finish has no delay at all.

alter table siteops_v2.tasks
  add column if not exists actual_start_at timestamptz,
  add column if not exists actual_finish_at timestamptz;

create index if not exists ix_v2_tasks_actual_finish_at
  on siteops_v2.tasks(actual_finish_at) where actual_finish_at is not null;
