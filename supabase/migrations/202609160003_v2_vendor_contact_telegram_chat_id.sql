-- U4 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md):
-- the vendor-contact half of the Telegram identity field. The
-- `employee_profiles` half is added by a separate alembic migration
-- (backend/alembic/versions/0023_telegram_identity_field.py), since that
-- table lives in the `public` baseline schema alembic owns, not this
-- domain schema.

alter table siteops_v2.vendor_contacts add column if not exists telegram_chat_id text;
create unique index if not exists uq_v2_vendor_contacts_telegram_chat_id
  on siteops_v2.vendor_contacts(telegram_chat_id) where telegram_chat_id is not null;
