-- U6 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md):
-- which channel a given delivery actually went out on. Additive, defaults
-- to 'whatsapp' for every existing and new row - nothing writes anything
-- else here yet (U9).

alter table siteops_v2.message_deliveries add column if not exists channel text not null default 'whatsapp';
