-- Punch-list follow-up: a handful of FK/lookup columns added across Phase 3
-- and Phase 6 never got a matching index. None of these are correctness
-- fixes - every query they'd speed up already works today, just via a
-- sequential scan - so this is pure lookup-cost cleanup, not a bugfix.

-- broadcast_recipients: "which broadcasts did this person receive" queries
-- (a user/vendor/vendor-contact's own delivery history) would otherwise
-- scan every recipient row ever created, not just their own.
create index if not exists ix_v2_broadcast_recipients_user on siteops_v2.broadcast_recipients(user_id);
create index if not exists ix_v2_broadcast_recipients_vendor on siteops_v2.broadcast_recipients(vendor_id);
create index if not exists ix_v2_broadcast_recipients_vendor_contact on siteops_v2.broadcast_recipients(vendor_contact_id);

-- The Phase 3 append-only overlay tables already index (entity, timestamp)
-- for their per-entity history views, but a project-wide rollup (e.g. "all
-- readiness declarations on this project this week") has no project_id
-- index to use.
create index if not exists ix_v2_task_readiness_declarations_project on siteops_v2.task_readiness_declarations(project_id);
create index if not exists ix_v2_task_attendance_events_project on siteops_v2.task_attendance_events(project_id);
create index if not exists ix_v2_project_external_approval_status_checks_project on siteops_v2.project_external_approval_status_checks(project_id);
