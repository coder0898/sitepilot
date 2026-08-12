-- 45-day scheduling POC integration, U4: give an execution task a real
-- planned start date.
--
-- `tasks` already carries planned_start_day/planned_end_day as relative
-- day offsets, and 202608090001 added the nullable due_at that this unit
-- becomes the first writer of (target finish). There was no planned start
-- *date* anywhere, only the offset - so U9's "did this task start before
-- it was meant to?" comparison had nothing to read.
--
-- Nullable on purpose, the same way due_at is: the seven pre-activation
-- tasks in a 45-day project carry no planned day offsets at all, and a
-- null date for them is the correct answer rather than a data gap.

alter table siteops_v2.tasks
  add column if not exists planned_start_at timestamptz;

create index if not exists ix_v2_tasks_planned_start_at
  on siteops_v2.tasks(planned_start_at) where planned_start_at is not null;
