-- Phase 3 (3b): task attendance/presence events - an advisory, append-only
-- record of an internal employee's presence ('present'/'absent') against a
-- task, recorded either by the employee themselves or by a Supervisor/PM/
-- Admin on their behalf. Independent of `Task.lifecycle_status`.
--
-- Append-only, mirroring `siteops_v2.task_delay_events`: every record is
-- kept as its own row, never overwritten or deleted.

create table if not exists siteops_v2.task_attendance_events (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references siteops_v2.tasks(id) on delete restrict,
  project_id uuid not null references siteops_v2.projects(id) on delete restrict,
  employee_id uuid not null references employee_profiles(id) on delete restrict,
  status text not null check (status in ('present', 'absent')),
  note text,
  recorded_by uuid not null references users(id) on delete restrict,
  recorded_at timestamptz not null default now()
);
create index if not exists ix_v2_task_attendance_events_task_recorded
  on siteops_v2.task_attendance_events(task_id, recorded_at desc);
revoke all on table siteops_v2.task_attendance_events from anon, authenticated;
