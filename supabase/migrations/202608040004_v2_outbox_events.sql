-- Phase 2 U4: durable outbox event infrastructure (R6/BR-015).
--
-- `outbox_events` is the durable, idempotent record of every
-- business-meaningful mutation event, written in the SAME transaction as
-- the domain mutation that caused it (see backend/app/services/outbox.py's
-- OutboxService.emit - it only ever adds + flushes, NEVER commits, so an
-- outbox-insert failure rolls back the domain mutation with it). This unit
-- only ever writes status='pending' rows; a later dispatch unit reads
-- pending rows and moves them to 'dispatched'/'failed', so `status`'s check
-- constraint already includes those two values even though nothing in this
-- unit writes them yet.
--
-- `idempotency_key` is unique so that retrying the same logical mutation
-- (e.g. a client retry after a timed-out response that actually succeeded
-- server-side) never produces a second outbox row for the same logical
-- event - `OutboxService.emit` checks for an existing row with the same key
-- before inserting and returns a no-op if found.

create table if not exists siteops_v2.outbox_events (
  id uuid primary key default gen_random_uuid(),
  event_type text not null,
  aggregate_type text not null,
  aggregate_id uuid not null,
  payload jsonb not null,
  idempotency_key text not null,
  status text not null default 'pending' check (status in ('pending', 'dispatched', 'failed')),
  created_at timestamptz not null default now(),
  constraint uq_v2_outbox_events_idempotency_key unique (idempotency_key)
);
create index if not exists ix_v2_outbox_events_aggregate on siteops_v2.outbox_events(aggregate_type, aggregate_id);
create index if not exists ix_v2_outbox_events_status on siteops_v2.outbox_events(status);
revoke all on table siteops_v2.outbox_events from anon, authenticated;
