-- Fixes the Sept 16 telegram-channel enum widening
-- (202609160006_v2_telegram_channel_enum_widening.sql), discovered live
-- during Telegram manual testing on 2026-09-21.
--
-- Two real bugs, both traced to actual failed Telegram commands:
--
-- 1. That migration tried to `drop constraint if exists
--    ck_v2_task_progress_updates_source` / `ck_v2_vendor_acknowledgements_channel`
--    before adding the widened replacement - but those names were never the
--    live constraints. Both tables' `check(...)` clauses were written
--    inline, with no explicit constraint name, in their original CREATE
--    TABLE statements (202608020002_v2_task_progress_and_evidence.sql,
--    202608040003_v2_vendor_acknowledgements_activity.sql), so Postgres
--    auto-named them `task_progress_updates_source_check` /
--    `vendor_acknowledgements_channel_check`. The DROP silently no-opped
--    against a name that never existed, so the widened constraint was
--    ADDED alongside the original narrow one rather than replacing it -
--    Postgres enforces every CHECK constraint on a column together, so the
--    original narrow one alone still blocks 'telegram' regardless of the
--    new one's existence. This is why
--    `VendorAcknowledgementService.record_acknowledgement(...,
--    channel="telegram")` (the Telegram ACCEPT/DECLINE/CLARIFY path) would
--    still fail today despite that Sept 16 migration having run.
--
-- 2. `audit_events.source` (`ck_v2_audit_source`,
--    202607240001_v2_project_management.sql) was never touched by the
--    Sept 16 migration at all - an outright omission. Every
--    TaskLifecycleService.transition() call writes a V2AuditEvent with
--    `source` set to whatever channel drove it; a real Telegram STATUS
--    command (STATUS T001 in_progress, manual test 2026-09-21) hit this
--    directly - the transition logic itself succeeded (ready -> in_progress,
--    role check passed), then the audit_events insert was rejected by this
--    constraint, rolling back the entire transition with no reply sent.

alter table siteops_v2.task_progress_updates drop constraint if exists task_progress_updates_source_check;
alter table siteops_v2.vendor_acknowledgements drop constraint if exists vendor_acknowledgements_channel_check;

alter table siteops_v2.audit_events drop constraint if exists ck_v2_audit_source;
alter table siteops_v2.audit_events add constraint ck_v2_audit_source
  check (source in ('portal', 'whatsapp', 'telegram', 'system'));
