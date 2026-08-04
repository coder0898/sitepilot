-- Phase 2 U3: vendor acknowledgement and activity/incident capture (R4/R5).
--
-- `vendor_acknowledgements` records a vendor's response - 'accepted',
-- 'declined', or 'clarification_requested' - against a specific
-- `task_vendor_assignments` row. It is append-only: every response is kept
-- (a vendor/PM may request clarification, then later accept - the earlier
-- row is never overwritten or deleted). Only the two terminal responses,
-- 'accepted' and 'declined', update the parent assignment's `status`
-- ('acknowledged'/'declined' respectively); 'clarification_requested' never
-- changes it, so the assignment stays 'pending_ack' and can still receive a
-- later acknowledgement attempt. `channel` defaults to 'portal' (this
-- unit's route is PM-submitted, portal-only) but is not constrained to it -
-- a later unit's WhatsApp inbound-matching flow can append rows with
-- channel = 'whatsapp' without a schema change. Recording (both channels)
-- is done by/on behalf of a human actor tracked in `recorded_by`; there is
-- no vendor-identity auth in this unit (R4 - PM records on the vendor's
-- behalf).
--
-- `vendor_activity_events` logs vendor-attributable activity - 'presence',
-- 'delay', 'rework', or 'incident' - against a specific
-- `task_vendor_assignments` row (so it is always task+vendor scoped), with
-- a required `description` and an optional `responsibility_decision` free
-- text (used mainly for 'delay'-type events per the plan). `presence` and
-- `rework` carry no extra fields beyond description; `incident` never
-- requires evidence (it's always optional, for every event_type).
--
-- `vendor_activity_evidence` is a real FK link between one
-- `vendor_activity_events` row and one `siteops_v2.file_objects` row -
-- deliberately NOT a polymorphic entity_type/entity_id reference, mirroring
-- `siteops_v2.task_evidence`'s link between `task_progress_updates` and
-- `file_objects`. The plan describes "an optional evidence file" (singular)
-- per event; the service layer enforces 0-or-1, not this table's shape.

create table if not exists siteops_v2.vendor_acknowledgements (
  id uuid primary key default gen_random_uuid(),
  task_vendor_assignment_id uuid not null references siteops_v2.task_vendor_assignments(id) on delete restrict,
  response text not null check (response in ('accepted', 'declined', 'clarification_requested')),
  channel text not null default 'portal' check (channel in ('portal', 'whatsapp', 'system')),
  note text,
  recorded_by uuid not null references users(id) on delete restrict,
  created_at timestamptz not null default now()
);
create index if not exists ix_v2_vendor_acknowledgements_assignment on siteops_v2.vendor_acknowledgements(task_vendor_assignment_id);
revoke all on table siteops_v2.vendor_acknowledgements from anon, authenticated;

create table if not exists siteops_v2.vendor_activity_events (
  id uuid primary key default gen_random_uuid(),
  task_vendor_assignment_id uuid not null references siteops_v2.task_vendor_assignments(id) on delete restrict,
  event_type text not null check (event_type in ('presence', 'delay', 'rework', 'incident')),
  description text not null,
  responsibility_decision text,
  recorded_by uuid not null references users(id) on delete restrict,
  created_at timestamptz not null default now()
);
create index if not exists ix_v2_vendor_activity_events_assignment on siteops_v2.vendor_activity_events(task_vendor_assignment_id);
revoke all on table siteops_v2.vendor_activity_events from anon, authenticated;

create table if not exists siteops_v2.vendor_activity_evidence (
  id uuid primary key default gen_random_uuid(),
  vendor_activity_event_id uuid not null references siteops_v2.vendor_activity_events(id) on delete restrict,
  file_id uuid not null references siteops_v2.file_objects(id) on delete restrict,
  created_at timestamptz not null default now(),
  constraint uq_v2_vendor_activity_evidence_event_file unique (vendor_activity_event_id, file_id)
);
create index if not exists ix_v2_vendor_activity_evidence_event on siteops_v2.vendor_activity_evidence(vendor_activity_event_id);
create index if not exists ix_v2_vendor_activity_evidence_file on siteops_v2.vendor_activity_evidence(file_id);
revoke all on table siteops_v2.vendor_activity_evidence from anon, authenticated;
