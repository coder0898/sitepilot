-- Vendor consolidation: the V2 home for Vendor Hub's "Add note" feature.
--
-- Replaces the legacy `communication_logs` table, which is dropped with the
-- rest of the legacy vendor schema. Two reasons it could not simply be
-- repointed:
--   * `communication_logs.vendor_id` FKs into legacy `public.vendors`, and
--     `execution_project_id` into legacy `public.execution_projects` - both
--     tables go away, so every FK on it had to be rebuilt regardless.
--   * `siteops_v2.vendor_activity_events` is NOT a substitute: it hangs off
--     a `task_vendor_assignments` row and constrains `event_type` to
--     presence/delay/rework/incident, so it cannot hold a free-text note
--     written against a vendor with no task in play.
--
-- `project_id` points at a real `siteops_v2.projects` row - the legacy
-- column pointed at `execution_projects`, which nothing had populated since
-- project creation moved to V2, so note-to-project tagging never actually
-- worked. This closes that gap rather than carrying it forward.
--
-- Nullable `project_id`/`contact_id` mirror the legacy shape: a note may be
-- general to the vendor, or scoped to one project and/or one contact.

create table if not exists siteops_v2.vendor_notes (
  id uuid primary key default gen_random_uuid(),
  vendor_id uuid not null references siteops_v2.vendors(id) on delete cascade,
  project_id uuid references siteops_v2.projects(id) on delete set null,
  contact_id uuid references siteops_v2.vendor_contacts(id) on delete set null,
  channel text not null default 'note',
  note text not null,
  created_by uuid references users(id) on delete restrict,
  created_at timestamptz not null default now(),
  constraint ck_v2_vendor_notes_channel check (channel in ('note', 'call', 'whatsapp', 'email', 'meeting'))
);
create index if not exists ix_v2_vendor_notes_vendor on siteops_v2.vendor_notes(vendor_id);
create index if not exists ix_v2_vendor_notes_project on siteops_v2.vendor_notes(project_id);
create index if not exists ix_v2_vendor_notes_created_at on siteops_v2.vendor_notes(created_at desc);
revoke all on table siteops_v2.vendor_notes from anon, authenticated;
