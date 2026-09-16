-- U5 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md,
-- KTD1): the vendor-contact half of the active-channel field. The
-- `employee_profiles` half is added by a separate alembic migration
-- (backend/alembic/versions/0024_active_channel_field.py), since that
-- table lives in the `public` baseline schema alembic owns, not this
-- domain schema.
--
-- Defaults to 'whatsapp' for every existing and new row so behavior is
-- unchanged until an Admin/Super-Admin explicitly toggles someone (U15).

alter table siteops_v2.vendor_contacts add column if not exists active_channel text not null default 'whatsapp';
alter table siteops_v2.vendor_contacts add constraint ck_v2_vendor_contacts_active_channel
  check (active_channel in ('whatsapp', 'telegram'));
