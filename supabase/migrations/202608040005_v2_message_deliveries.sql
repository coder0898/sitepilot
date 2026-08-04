-- Phase 2 U5: message delivery tracking + provider-agnostic dispatch (R7).
--
-- `message_deliveries` is the per-recipient delivery record for a pending
-- `outbox_events` row (see 202608040004_v2_outbox_events.sql). One outbox
-- event can fan out to multiple recipients (e.g. a task event notifies
-- both the project's PM and Supervisor, and sometimes an assigned vendor's
-- primary contact too) - this table is the fan-out target, one row per
-- (event, recipient, template).
--
-- `recipient_phone` is a DENORMALIZED SNAPSHOT of the phone number at
-- dispatch time, not a live join to the employee/vendor-contact record.
-- This is deliberate: the underlying `User.phone` / `vendor_contacts.phone`
-- value could change after a message was sent, and we want a durable record
-- of what number a given message actually went to, independent of later
-- edits to the recipient's contact details.
--
-- Recipient identity uses two nullable real FK columns
-- (`recipient_employee_id` / `recipient_vendor_contact_id`), never a
-- polymorphic entity_type/entity_id pair - this mirrors the established
-- convention elsewhere in this schema (e.g. `siteops_v2.task_evidence`'s
-- real FK link between a progress update and a file, instead of a generic
-- reference). The CHECK constraint below enforces exactly one is set.
--
-- Idempotency: the unique index on
-- (outbox_event_id, recipient_employee_id, recipient_vendor_contact_id,
-- template) means retrying dispatch for the same event+recipient+template
-- never creates a second row - a retry after a prior 'failed' attempt
-- updates the EXISTING row (increments attempt_count, updates status)
-- instead. See backend/app/services/message_dispatch.py's
-- MessageDispatchService.process_pending for the read/update loop that
-- relies on this.
--
-- `status` includes 'delivered'/'read' even though this unit's sandbox
-- adapter never produces them (it only ever resolves to 'sent' or
-- 'failed') - those two values are reserved for a later unit wiring a real
-- provider's delivery/read webhook callbacks, which would update an
-- already-'sent' row in place rather than needing a schema change.

create table if not exists siteops_v2.message_deliveries (
  id uuid primary key default gen_random_uuid(),
  outbox_event_id uuid not null references siteops_v2.outbox_events(id) on delete restrict,
  recipient_employee_id uuid references employee_profiles(id) on delete restrict,
  recipient_vendor_contact_id uuid references siteops_v2.vendor_contacts(id) on delete restrict,
  recipient_phone text not null,
  template text not null,
  provider text not null default 'sandbox',
  provider_message_id text,
  status text not null default 'queued' check (status in ('queued', 'sending', 'sent', 'delivered', 'read', 'failed', 'suppressed')),
  attempt_count integer not null default 0,
  failure_code text,
  failure_reason text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint ck_v2_message_deliveries_recipient_exclusive check (
    (recipient_employee_id is not null and recipient_vendor_contact_id is null) or
    (recipient_employee_id is null and recipient_vendor_contact_id is not null)
  )
);
-- NULLS NOT DISTINCT (PG15+; this project runs PG17 per supabase/config.toml)
-- is required here, not optional: since exactly one of
-- recipient_employee_id/recipient_vendor_contact_id is always null (see the
-- CHECK constraint above), a plain unique index would treat two rows for
-- the SAME employee recipient as non-duplicates (standard SQL NULL <> NULL
-- semantics), silently defeating the one-row-per-event-recipient-template
-- idempotency guarantee this index exists to enforce.
create unique index if not exists uq_v2_message_deliveries_event_recipient_template
  on siteops_v2.message_deliveries(outbox_event_id, recipient_employee_id, recipient_vendor_contact_id, template)
  nulls not distinct;
create unique index if not exists uq_v2_message_deliveries_provider_message_id
  on siteops_v2.message_deliveries(provider_message_id) where provider_message_id is not null;
create index if not exists ix_v2_message_deliveries_outbox_event on siteops_v2.message_deliveries(outbox_event_id);
create index if not exists ix_v2_message_deliveries_status on siteops_v2.message_deliveries(status);
revoke all on table siteops_v2.message_deliveries from anon, authenticated;
