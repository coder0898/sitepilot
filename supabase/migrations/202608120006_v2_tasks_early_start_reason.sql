-- 45-day scheduling POC integration, U9: capture why work started ahead of
-- its planned date.
--
-- Starting early is legitimate and common - a trade turns up, the previous
-- crew finished sooner, material landed. The proof of concept's position is
-- that it should be allowed and recorded, not prevented. So this asks for
-- a reason rather than refusing the start.
--
-- The column stores the reason for display. The V2AuditEvent written by the
-- same transition is its attribution of record, carrying actor and
-- timestamp, so who claimed which early start is answerable without
-- reading this column at all.
--
-- Nullable: most starts are not early, and a task started before U9 shipped
-- has no reason to record.

alter table siteops_v2.tasks
  add column if not exists early_start_reason text;
