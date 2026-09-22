-- U2 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md):
-- raw Telegram Bot API update storage, before any identity matching or
-- command dispatch (U13/U14).
--
-- `update_id` is Telegram's own per-update identifier. Telegram's Bot API
-- redelivers on a slow or failed response - the same at-least-once behavior
-- `inbound_messages.provider_message_id`'s uniqueness guards against for
-- WhatsApp - so its uniqueness here lets a later unit detect and reject a
-- duplicate delivery before executing any state-changing action.

create table if not exists siteops_v2.telegram_inbound_updates (
  id uuid primary key default gen_random_uuid(),
  update_id bigint not null,
  chat_id text not null,
  message_text text,
  callback_data text,
  raw_payload jsonb not null,
  created_at timestamptz not null default now(),
  constraint uq_v2_telegram_inbound_updates_update_id unique (update_id)
);
create index if not exists ix_v2_telegram_inbound_updates_chat_id on siteops_v2.telegram_inbound_updates(chat_id);
revoke all on table siteops_v2.telegram_inbound_updates from anon, authenticated;
