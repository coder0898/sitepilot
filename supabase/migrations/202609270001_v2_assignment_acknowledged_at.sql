-- Telegram T2: when someone pressed Acknowledge on an onboarding or
-- assignment message. A receipt only - it grants and changes nothing else.
--   project_memberships       [Acknowledge Assignment]      (internal member)
--   project_vendors           [Acknowledge / स्वीकार करें]   (vendor, project)
--   task_support_assignments  [Acknowledge]                 (internal, task)
-- Vendor task assignments already record acknowledgement through
-- vendor_acknowledgements (same as a typed ACCEPT), so they need no column.
-- Nullable: every existing row simply stays unacknowledged.

alter table siteops_v2.project_memberships
  add column if not exists acknowledged_at timestamptz;

alter table siteops_v2.project_vendors
  add column if not exists acknowledged_at timestamptz;

alter table siteops_v2.task_support_assignments
  add column if not exists acknowledged_at timestamptz;
