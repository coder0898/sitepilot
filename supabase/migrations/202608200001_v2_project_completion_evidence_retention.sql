-- Evidence retention: completed_at anchors the 6-month retention clock to
-- when a project was ACTUALLY marked complete, never to
-- target_handover_date - a delayed project must never have live evidence
-- swept while it is still active. evidence_purged_at marks a project the
-- retention sweep has already processed, so a daily sweep never rescans
-- (and re-no-ops against) the same completed project forever.
alter table siteops_v2.projects add column if not exists completed_at timestamptz;
alter table siteops_v2.projects add column if not exists evidence_purged_at timestamptz;

create index if not exists ix_v2_projects_evidence_retention_due
  on siteops_v2.projects (completed_at)
  where completed_at is not null and evidence_purged_at is null;
