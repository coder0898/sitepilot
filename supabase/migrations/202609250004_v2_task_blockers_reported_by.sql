-- Telegram task plan U12 (KTD14): who reported each blocker, so they can be
-- told when it is resolved. Set from the acting user for every channel (Web
-- App and Telegram alike); no channel/source column is added (KTD21).
-- Nullable: blockers logged before this migration keep no reporter and
-- simply notify no one extra when resolved.

alter table siteops_v2.task_blockers
  add column if not exists reported_by uuid references public.users(id) on delete set null;
