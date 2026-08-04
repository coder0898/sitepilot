-- Phase 2 U6: inbound WhatsApp message matching (R8/R9).
--
-- `inbound_messages` is the retained record of every webhook delivery that
-- passed HMAC signature verification at
-- `backend/app/routes/whatsapp_webhook_v2.py` - an invalid/missing
-- signature is rejected before any query or write against this table (or
-- any other table), so every row here, whatever its `processing_status`,
-- represents an authentic provider delivery. `processing_status='unmatched'`
-- or `'rejected'` rows never mutate any other domain state - matching and
-- command parsing failures are recorded here only, never surfaced as a
-- retryable webhook error to the provider.
--
-- `provider_message_id` is UNIQUE so a provider's retried webhook delivery
-- (WhatsApp/Meta-style providers retry on non-2xx, and sometimes even on a
-- slow 2xx) never creates a second row or re-executes the command a first
-- delivery already acted on - see `InboundMessageService.process`'s
-- duplicate check, which returns the existing row unchanged instead of
-- reprocessing.
--
-- `matched_identity_type`/`matched_identity_id` is a polymorphic pair
-- (rather than the two-nullable-real-FK-columns "exactly one set" shape
-- used by `siteops_v2.message_deliveries`) because a message resolves to
-- at most one of two genuinely different identity tables
-- (`employee_profiles` or `siteops_v2.vendor_contacts`), and on
-- 'unmatched'/'rejected' rows BOTH stay null rather than one-of-two being
-- required - so the AND/OR "exactly one" CHECK shape used elsewhere
-- doesn't apply the same way here. No FK constraint is placed on
-- `matched_identity_id` since which table it references depends on
-- `matched_identity_type`; the CHECK below only constrains the type
-- column's value when it is set.
--
-- No normalization is applied to `sender_phone` - this codebase has no
-- phone-number normalization mechanism anywhere yet (see the Phase 2 U6
-- plan's own gap note), so matching is raw string equality against
-- `users.phone` / `siteops_v2.vendor_contacts.phone` /
-- `siteops_v2.vendor_contacts.whatsapp`, exactly as stored.

create table if not exists siteops_v2.inbound_messages (
  id uuid primary key default gen_random_uuid(),
  provider_message_id text not null,
  sender_phone text not null,
  raw_body text not null,
  matched_identity_type text,
  matched_identity_id uuid,
  processing_status text not null default 'unmatched',
  rejection_reason text,
  created_at timestamptz not null default now(),
  constraint uq_v2_inbound_messages_provider_message_id unique (provider_message_id),
  constraint ck_v2_inbound_messages_identity_type check (
    matched_identity_type is null or matched_identity_type in ('employee', 'vendor_contact')
  ),
  constraint ck_v2_inbound_messages_processing_status check (
    processing_status in ('processed', 'unmatched', 'rejected')
  )
);
create index if not exists ix_v2_inbound_messages_sender_phone on siteops_v2.inbound_messages(sender_phone);
create index if not exists ix_v2_inbound_messages_processing_status on siteops_v2.inbound_messages(processing_status);
revoke all on table siteops_v2.inbound_messages from anon, authenticated;
