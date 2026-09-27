-- Attendance is removed from SiteOps entirely (product decision, 2026-09-28):
-- no service, API route, Telegram/WhatsApp message or model uses it any more.
--
-- DESTRUCTIVE: this permanently deletes every attendance record. Export the
-- table first if the data may ever be needed:
--   select count(*) from siteops_v2.task_attendance_events;
--   \copy siteops_v2.task_attendance_events to 'task_attendance_events.csv' csv header
--
-- Safe to apply before or after the code that stops using the table: the
-- new code never reads it, and the old code only writes it when someone
-- records attendance through the API (which the Web App never exposed).

drop table if exists siteops_v2.task_attendance_events;
