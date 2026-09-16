-- U3 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md):
-- a one-time token issued to a specific employee or vendor contact, so
-- they can link a Telegram chat to their existing identity by opening the
-- bot's `/start <token>` link (U13). Purely schema at this point - no
-- token-generation or token-consumption logic yet.
--
-- `token` must be generated as a cryptographically random, sufficiently
-- long value by whichever later unit issues one - a security requirement
-- on the data this table holds, not something the schema itself enforces.

create table if not exists siteops_v2.telegram_connect_tokens (
  id uuid primary key default gen_random_uuid(),
  token text not null,
  employee_id uuid references employee_profiles(id) on delete cascade,
  vendor_contact_id uuid references siteops_v2.vendor_contacts(id) on delete cascade,
  expires_at timestamptz not null,
  used_at timestamptz,
  created_at timestamptz not null default now(),
  constraint uq_v2_telegram_connect_tokens_token unique (token),
  constraint ck_v2_telegram_connect_tokens_recipient_exclusive check (
    (employee_id is not null and vendor_contact_id is null) or
    (employee_id is null and vendor_contact_id is not null)
  )
);
revoke all on table siteops_v2.telegram_connect_tokens from anon, authenticated;
