-- Phase 3 U1: adds the due_at/update_sla_hours columns that Phase 1's U5
-- plan (task_blockers/delays) anticipated but deferred to implementation -
-- see supabase/migrations/202608020004_v2_task_blockers_delays.sql's own
-- comment: "overdue and no_update remain derived at query time from
-- due_at/update_sla_hours - no storage here for those two." Phase 3 is the
-- first consumer that actually needs them, so they land here.
--
-- Both columns are nullable: a task with no due_at never counts as
-- overdue, and a task with no update_sla_hours never counts as no_update -
-- this is deliberate (not every task requires either check), not a data
-- migration gap.

alter table siteops_v2.tasks
  add column if not exists due_at timestamptz,
  add column if not exists update_sla_hours integer;

alter table siteops_v2.tasks
  add constraint ck_v2_tasks_update_sla_hours_positive check (update_sla_hours is null or update_sla_hours > 0);

create index if not exists ix_v2_tasks_due_at on siteops_v2.tasks(due_at) where due_at is not null;
