-- Phase 2 U2: project-vendor mapping and task vendor delegation (R2/R3).
--
-- `project_vendors` records that a vendor is engaged on a project. Mapping
-- eligibility - only an `active` vendor may be mapped, and a `sub_vendor`
-- additionally requires its parent to already have an active mapping to the
-- *same* project - is enforced in `backend/app/services/project_vendor.py`,
-- not here: the sub-vendor rule spans two rows (this vendor's mapping
-- candidacy and its parent's existing mapping row), so it cannot be
-- expressed as a single-row CHECK constraint the way e.g.
-- `task_delay_events`'s responsibility/vendor pairing is. There is no
-- `ended_at`/status column here - this unit only adds mappings, it does not
-- build an unmapping flow, so a row's existence is what "actively mapped"
-- means for now.
--
-- `task_vendor_assignments` records that a vendor has been delegated to
-- work on a specific execution-layer task (R3). This is a pure delegation
-- record: it never transfers or alters Site Supervisor accountability
-- (BR-004's accountability resolution, derived in Phase 1 U6, stays
-- entirely independent of this table) and never itself satisfies or
-- affects a `task_dependencies` blocking check (Phase 1 U1). `status`
-- starts at 'pending_ack' on every insert; 'acknowledged'/'declined' are
-- reserved here for a later unit's vendor-acknowledgement flow - this
-- migration and this unit's service only ever initialize new rows to
-- 'pending_ack'.

create table if not exists siteops_v2.project_vendors (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references siteops_v2.projects(id) on delete restrict,
  vendor_id uuid not null references siteops_v2.vendors(id) on delete restrict,
  mapped_by uuid not null references users(id) on delete restrict,
  created_at timestamptz not null default now(),
  constraint uq_v2_project_vendors_project_vendor unique (project_id, vendor_id)
);
create index if not exists ix_v2_project_vendors_project on siteops_v2.project_vendors(project_id);
create index if not exists ix_v2_project_vendors_vendor on siteops_v2.project_vendors(vendor_id);
revoke all on table siteops_v2.project_vendors from anon, authenticated;

create table if not exists siteops_v2.task_vendor_assignments (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references siteops_v2.tasks(id) on delete restrict,
  project_id uuid not null references siteops_v2.projects(id) on delete restrict,
  vendor_id uuid not null references siteops_v2.vendors(id) on delete restrict,
  status text not null default 'pending_ack' check (status in ('pending_ack', 'acknowledged', 'declined')),
  assigned_by uuid not null references users(id) on delete restrict,
  created_at timestamptz not null default now()
);
create index if not exists ix_v2_task_vendor_assignments_task on siteops_v2.task_vendor_assignments(task_id);
create index if not exists ix_v2_task_vendor_assignments_project on siteops_v2.task_vendor_assignments(project_id);
create index if not exists ix_v2_task_vendor_assignments_vendor on siteops_v2.task_vendor_assignments(vendor_id);
revoke all on table siteops_v2.task_vendor_assignments from anon, authenticated;
