-- Punch-list follow-up: `20260725083225_v2_template_schema.sql` explicitly
-- enables row-level security on the six v2_template_* tables. Every
-- siteops_v2 table added since only does `revoke all ... from anon,
-- authenticated`, which already blocks the PostgREST path entirely - this
-- migration adds no new protection, it just makes every siteops_v2 table
-- state its RLS posture the same explicit way, instead of half the schema
-- relying on "REVOKE ALL implies it doesn't matter".

alter table siteops_v2.projects enable row level security;
alter table siteops_v2.project_memberships enable row level security;
alter table siteops_v2.project_role_changes enable row level security;
alter table siteops_v2.project_baselines enable row level security;
alter table siteops_v2.baseline_tasks enable row level security;
alter table siteops_v2.tasks enable row level security;
alter table siteops_v2.project_tasks enable row level security;
alter table siteops_v2.task_dependencies enable row level security;
alter table siteops_v2.project_task_dependencies enable row level security;
alter table siteops_v2.project_external_gates enable row level security;
alter table siteops_v2.project_external_gate_tasks enable row level security;
alter table siteops_v2.project_external_gate_applicability_decisions enable row level security;
alter table siteops_v2.task_evidence enable row level security;
alter table siteops_v2.task_verifications enable row level security;
alter table siteops_v2.task_approval_decisions enable row level security;
alter table siteops_v2.task_blockers enable row level security;
alter table siteops_v2.task_delay_events enable row level security;
alter table siteops_v2.task_progress_updates enable row level security;
alter table siteops_v2.task_support_assignments enable row level security;
alter table siteops_v2.support_assignment_changes enable row level security;
alter table siteops_v2.vendors enable row level security;
alter table siteops_v2.vendor_contacts enable row level security;
alter table siteops_v2.vendor_capabilities enable row level security;
alter table siteops_v2.capability_categories enable row level security;
alter table siteops_v2.vendor_acknowledgements enable row level security;
alter table siteops_v2.vendor_activity_events enable row level security;
alter table siteops_v2.vendor_activity_evidence enable row level security;
alter table siteops_v2.vendor_notes enable row level security;
alter table siteops_v2.project_vendors enable row level security;
alter table siteops_v2.task_vendor_assignments enable row level security;
alter table siteops_v2.outbox_events enable row level security;
alter table siteops_v2.message_deliveries enable row level security;
alter table siteops_v2.inbound_messages enable row level security;
alter table siteops_v2.file_objects enable row level security;
alter table siteops_v2.audit_events enable row level security;
alter table siteops_v2.report_snapshots enable row level security;
alter table siteops_v2.project_external_approvals enable row level security;
alter table siteops_v2.project_external_approval_tasks enable row level security;
alter table siteops_v2.project_external_approval_submissions enable row level security;
alter table siteops_v2.project_external_approval_evidence enable row level security;
alter table siteops_v2.project_external_approval_status_checks enable row level security;
alter table siteops_v2.task_readiness_declarations enable row level security;
alter table siteops_v2.task_attendance_events enable row level security;
alter table siteops_v2.broadcasts enable row level security;
alter table siteops_v2.broadcast_recipients enable row level security;
alter table siteops_v2.broadcast_templates enable row level security;
alter table siteops_v2.escalation_tracking enable row level security;
