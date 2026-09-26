-- Gate plan chunk 3: a question the bot is waiting for a typed answer to
-- (the Admin's rejection reason, or an optional note after a health button).
-- At most one per Telegram chat - asking a new question replaces the old
-- one. The next text message from that chat answers it before being treated
-- as a command or evidence text. Rows are deleted once answered, skipped or
-- cancelled; `expires_at` bounds how long an unanswered question can
-- capture the next message.

create table if not exists siteops_v2.telegram_pending_inputs (
  id uuid primary key default gen_random_uuid(),
  chat_id text not null,
  kind text not null,
  approval_id uuid not null references siteops_v2.project_external_approvals(id) on delete cascade,
  health text,
  prompt_message_id bigint,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  constraint uq_v2_telegram_pending_inputs_chat unique (chat_id),
  constraint ck_v2_telegram_pending_inputs_kind check (kind in ('gate_reject_reason', 'gate_health_note')),
  constraint ck_v2_telegram_pending_inputs_health check (
    (kind = 'gate_health_note' and health is not null) or
    (kind = 'gate_reject_reason' and health is null)
  )
);
revoke all on table siteops_v2.telegram_pending_inputs from anon, authenticated;
