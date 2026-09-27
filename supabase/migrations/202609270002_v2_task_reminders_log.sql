-- Telegram T3-T5: scheduled task reminders on Asia/Kolkata time.
--
-- task_reminders_log is the at-most-once guarantee: the reminder service
-- inserts a row here in the same transaction as the reminder's outbox event,
-- so the unique key refuses (23505) a second send of the same reminder for
-- the same task on the same IST day - whatever the number of scheduler
-- passes or servers. scheduled_for_date is an Asia/Kolkata calendar date.

create table if not exists siteops_v2.task_reminders_log (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references siteops_v2.tasks(id) on delete cascade,
  reminder_type text not null,
  scheduled_for_date date not null,
  created_at timestamptz not null default now(),
  constraint uq_v2_task_reminders_log_once unique (task_id, reminder_type, scheduled_for_date)
);

alter table siteops_v2.task_reminders_log enable row level security;

-- Telegram T3 / T7: the bot's new questions - the note after a readiness
-- "Issue" / "Need Help", and the delay report's impact days and reason.
alter table siteops_v2.telegram_pending_inputs
  drop constraint if exists ck_v2_telegram_pending_inputs_kind;
alter table siteops_v2.telegram_pending_inputs
  add constraint ck_v2_telegram_pending_inputs_kind check (
    kind in ('gate_reject_reason', 'gate_health_note', 'task_early_start_reason',
             'task_verify_reject_reason', 'task_approval_reject_reason', 'task_blocker_type',
             'task_blocker_description', 'task_add_progress', 'task_readiness_note',
             'task_delay_days', 'task_delay_reason')
  );
