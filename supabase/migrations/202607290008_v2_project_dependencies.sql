create table if not exists siteops_v2.project_task_dependencies (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references siteops_v2.projects(id) on delete cascade,
  template_version_id uuid not null references siteops_v2.v2_template_versions(id) on delete restrict,
  template_dependency_id uuid not null references siteops_v2.v2_template_task_dependencies(id) on delete restrict,
  predecessor_project_task_id uuid not null references siteops_v2.project_tasks(id) on delete restrict,
  successor_project_task_id uuid not null references siteops_v2.project_tasks(id) on delete restrict,
  dependency_type text not null check (dependency_type in ('finish_to_start','start_to_start')),
  blocking boolean not null default true,
  rule_text text,
  template_sequence integer not null check (template_sequence > 0),
  excluded_task_warning boolean not null default false,
  source_type text not null default 'template' check (source_type='template'),
  lifecycle_status text not null default 'draft' check (lifecycle_status='draft'),
  created_at timestamptz not null default now(),
  constraint uq_v2_project_dependencies_project_template unique(project_id,template_dependency_id),
  constraint uq_v2_project_dependencies_edge unique(project_id,predecessor_project_task_id,successor_project_task_id,dependency_type),
  constraint ck_v2_project_dependencies_not_self check(predecessor_project_task_id<>successor_project_task_id)
);
create index if not exists ix_v2_project_dependencies_project_sequence on siteops_v2.project_task_dependencies(project_id,template_sequence);
create index if not exists ix_v2_project_dependencies_predecessor on siteops_v2.project_task_dependencies(predecessor_project_task_id);
create index if not exists ix_v2_project_dependencies_successor on siteops_v2.project_task_dependencies(successor_project_task_id);
revoke all on siteops_v2.project_task_dependencies from anon, authenticated;
