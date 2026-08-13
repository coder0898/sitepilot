-- U5: per-task calendar schedule and recorded actuals.
--
-- Adds the columns the date track needs:
--   planned_start_date / planned_end_date  the baseline day offsets resolved
--     against the project's start date (U9 writes them)
--   actual_start_at / actual_finish_at     when work really began and ended
--     (U10 writes them, from the lifecycle transition)
--   early_start_reason                     why a task started ahead of plan
--     (U14 writes it)
--
-- planned_* are `date`, not `timestamptz`. A planned day is a calendar
-- concept with no time-of-day, and it is derived from siteops_v2.projects
-- .start_date, which is itself a bare `date`. Storing it as an instant would
-- invite a timezone shift on every comparison. actual_* are `timestamptz`
-- because an actual start IS an instant, and the lifecycle already writes
-- timezone-aware UTC timestamps everywhere else.
--
-- planned_start_day / planned_end_day are deliberately untouched. They are
-- the immutable baseline; nothing here may rewrite them.
--
-- DRIFT RECONCILIATION. Some developer machines carry leftover columns from
-- reverted work that was never pushed: planned_start_at (timestamptz),
-- actual_start_at, actual_finish_at and early_start_reason. A fresh clone
-- has none of them. This migration must produce an identical schema on
-- both, so it cannot rely on `add column if not exists` alone -- that
-- silently keeps whatever type the leftover column already had.
--
--   * actual_start_at, actual_finish_at, early_start_reason already carry
--     the correct name and type where they exist, so `if not exists` is
--     genuinely a no-op there and adds them on a fresh database.
--   * planned_start_at is the wrong type and has no planned-end counterpart,
--     so it is dropped. The drop is guarded on the column being entirely
--     null, which it is wherever it exists (the reverted work never wrote to
--     it). If any row ever held a value the migration fails loudly rather
--     than discarding it.
--   * The type assertion at the end fails the migration if a pre-existing
--     column has an unexpected type, so a drifted machine can never silently
--     diverge from a fresh one.

begin;

-- 1. Retire the leftover planned_start_at, but never destroy real data.
do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'siteops_v2' and table_name = 'tasks'
      and column_name = 'planned_start_at'
  ) then
    if exists (select 1 from siteops_v2.tasks where planned_start_at is not null) then
      raise exception
        'siteops_v2.tasks.planned_start_at holds data; resolve it before this migration replaces it with planned_start_date';
    end if;
    execute 'drop index if exists siteops_v2.ix_v2_tasks_planned_start_at';
    execute 'alter table siteops_v2.tasks drop column planned_start_at';
  end if;
end $$;

-- 2. Add the schedule and actuals columns. All nullable: a pre-activation
--    task has no execution dates, and a task that has not started has no
--    actuals.
alter table siteops_v2.tasks
  add column if not exists planned_start_date date,
  add column if not exists planned_end_date   date,
  add column if not exists actual_start_at    timestamptz,
  add column if not exists actual_finish_at   timestamptz,
  add column if not exists early_start_reason text;

-- 3. An early-start reason only makes sense once the task actually started.
alter table siteops_v2.tasks
  drop constraint if exists ck_v2_tasks_early_start_reason_requires_start;
alter table siteops_v2.tasks
  add constraint ck_v2_tasks_early_start_reason_requires_start
  check (early_start_reason is null or actual_start_at is not null);

-- 4. A task cannot finish before it started.
alter table siteops_v2.tasks
  drop constraint if exists ck_v2_tasks_actual_finish_after_start;
alter table siteops_v2.tasks
  add constraint ck_v2_tasks_actual_finish_after_start
  check (actual_finish_at is null or actual_start_at is null or actual_finish_at >= actual_start_at);

-- 5. A planned window cannot end before it begins.
alter table siteops_v2.tasks
  drop constraint if exists ck_v2_tasks_planned_end_after_start;
alter table siteops_v2.tasks
  add constraint ck_v2_tasks_planned_end_after_start
  check (planned_end_date is null or planned_start_date is null or planned_end_date >= planned_start_date);

-- 6. Partial indexes for the date-range scans U13 (variance) and U16
--    (timeline) run. Partial because pre-activation tasks stay null.
create index if not exists ix_v2_tasks_planned_start_date
  on siteops_v2.tasks(planned_start_date) where planned_start_date is not null;
create index if not exists ix_v2_tasks_planned_end_date
  on siteops_v2.tasks(planned_end_date) where planned_end_date is not null;
create index if not exists ix_v2_tasks_actual_finish_at
  on siteops_v2.tasks(actual_finish_at) where actual_finish_at is not null;

-- 7. Fail loudly if a drifted machine disagrees with a fresh one on type.
--    This is the check `add column if not exists` cannot make for us.
do $$
declare
  mismatch text;
begin
  select string_agg(format('%s is %s', column_name, data_type), ', ')
    into mismatch
  from information_schema.columns
  where table_schema = 'siteops_v2' and table_name = 'tasks'
    and (
      (column_name in ('planned_start_date', 'planned_end_date') and data_type <> 'date')
      or (column_name in ('actual_start_at', 'actual_finish_at') and data_type <> 'timestamp with time zone')
      or (column_name = 'early_start_reason' and data_type <> 'text')
    );
  if mismatch is not null then
    raise exception 'siteops_v2.tasks schedule column type mismatch: %', mismatch;
  end if;
end $$;

commit;
