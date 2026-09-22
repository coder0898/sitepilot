-- Vendor unassignment/removal (soft removal), mirroring the ends_at
-- pattern already used by project_memberships / task_support_assignments.
--
-- ProjectVendor and TaskVendorAssignment rows are never deleted once a
-- vendor is unassigned/removed - ends_at marks when the mapping/assignment
-- stopped being active, and the row (plus every acknowledgement/evidence
-- record hanging off it) stays exactly as it was for history. See
-- ProjectVendorService.remove_vendor / TaskVendorAssignmentService.unassign_vendor.

alter table siteops_v2.project_vendors add column if not exists ends_at timestamptz;
alter table siteops_v2.task_vendor_assignments add column if not exists ends_at timestamptz;

-- Replaces the old always-on uniqueness: a vendor removed from a project
-- (ends_at set) can be re-mapped to it later - only one ACTIVE mapping per
-- project/vendor is enforced, not one ever.
alter table siteops_v2.project_vendors drop constraint if exists uq_v2_project_vendors_project_vendor;
create unique index if not exists uq_v2_project_vendors_active_project_vendor
  on siteops_v2.project_vendors(project_id, vendor_id)
  where ends_at is null;
