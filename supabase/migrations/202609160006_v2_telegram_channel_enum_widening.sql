-- U7 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md):
-- widens two live CHECK constraints to accept 'telegram' alongside the
-- existing 'portal'/'whatsapp'/'system' values. No code path emits
-- 'telegram' yet - this only widens what's accepted. Editing the
-- CheckConstraint string in the SQLAlchemy model (app/execution_models.py,
-- app/vendor_models.py) does not alter an already-live Postgres
-- constraint - that needs this explicit DROP/ADD.

alter table siteops_v2.task_progress_updates drop constraint if exists ck_v2_task_progress_updates_source;
alter table siteops_v2.task_progress_updates add constraint ck_v2_task_progress_updates_source
  check (source in ('portal', 'whatsapp', 'telegram', 'system'));

alter table siteops_v2.vendor_acknowledgements drop constraint if exists ck_v2_vendor_acknowledgements_channel;
alter table siteops_v2.vendor_acknowledgements add constraint ck_v2_vendor_acknowledgements_channel
  check (channel in ('portal', 'whatsapp', 'telegram', 'system'));
