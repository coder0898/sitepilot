-- Phase 3 U3: versioned daily/weekly report snapshots (R5/R6, BR-016).
--
-- payload_json is computed once at generation time and frozen - viewing an
-- older version must show what was true when it was generated, never a
-- live recomputation (see the plan's Key Technical Decisions). Regenerating
-- for an already-generated (project_id, report_type, period_start,
-- period_end) creates a new version_no rather than overwriting, per the
-- append-only modelling principle already used elsewhere in this schema
-- (e.g. ProjectRoleChange, SupportAssignmentChange).

create table if not exists siteops_v2.report_snapshots (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references siteops_v2.projects(id) on delete restrict,
  report_type text not null check (report_type in ('daily', 'weekly')),
  period_start timestamptz not null,
  period_end timestamptz not null,
  version_no integer not null check (version_no > 0),
  payload_json jsonb not null,
  generated_by uuid not null references users(id) on delete restrict,
  generated_at timestamptz not null default now(),
  constraint ck_v2_report_snapshots_period check (period_end > period_start),
  constraint uq_v2_report_snapshots_period_version unique (project_id, report_type, period_start, period_end, version_no)
);
create index if not exists ix_v2_report_snapshots_project on siteops_v2.report_snapshots(project_id, report_type, period_start);
revoke all on table siteops_v2.report_snapshots from anon, authenticated;
