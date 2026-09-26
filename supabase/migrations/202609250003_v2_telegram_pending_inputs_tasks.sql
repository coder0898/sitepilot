-- Telegram task plan U6 (KTD7): the bot's pending-question table, built for
-- External Approval Gate questions (202609240001), now also holds questions
-- about internal tasks: the early-start reason (U6), and - so later units
-- need no further migration - the verification/approval reject reasons
-- (U9/U10), the blocker type and description (U12) and the Add Progress
-- mode (U7).
--
-- - task_id: the task a task question is about (a gate question keeps using
--   approval_id). Exactly one of the two is set, matching the kind.
-- - draft_text: an earlier answer carried into the next question of the same
--   flow (the blocker type, while asking for the description).
-- - review_token: which submission a review question belongs to, so an
--   answer to an outdated review is refused (KTD19).
-- - health stays set only for gate health notes.
--
-- Gate questions are unaffected: every existing row has a gate kind, an
-- approval_id and (for health notes only) a health value, which the new
-- checks accept as they are.

alter table siteops_v2.telegram_pending_inputs
  add column if not exists task_id uuid references siteops_v2.tasks(id) on delete cascade,
  add column if not exists draft_text text,
  add column if not exists review_token text;

alter table siteops_v2.telegram_pending_inputs
  alter column approval_id drop not null;

alter table siteops_v2.telegram_pending_inputs
  drop constraint if exists ck_v2_telegram_pending_inputs_kind;
alter table siteops_v2.telegram_pending_inputs
  add constraint ck_v2_telegram_pending_inputs_kind check (kind in (
    'gate_reject_reason', 'gate_health_note',
    'task_early_start_reason', 'task_verify_reject_reason', 'task_approval_reject_reason',
    'task_blocker_type', 'task_blocker_description', 'task_add_progress'
  ));

alter table siteops_v2.telegram_pending_inputs
  drop constraint if exists ck_v2_telegram_pending_inputs_target;
alter table siteops_v2.telegram_pending_inputs
  add constraint ck_v2_telegram_pending_inputs_target check (
    (kind in ('gate_reject_reason', 'gate_health_note') and approval_id is not null and task_id is null) or
    (kind not in ('gate_reject_reason', 'gate_health_note') and task_id is not null and approval_id is null)
  );

alter table siteops_v2.telegram_pending_inputs
  drop constraint if exists ck_v2_telegram_pending_inputs_health;
alter table siteops_v2.telegram_pending_inputs
  add constraint ck_v2_telegram_pending_inputs_health check (
    (kind = 'gate_health_note' and health is not null) or
    (kind <> 'gate_health_note' and health is null)
  );
