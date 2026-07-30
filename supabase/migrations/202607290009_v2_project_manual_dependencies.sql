alter table siteops_v2.project_task_dependencies
  drop constraint if exists ck_v2_project_dependencies_source;
alter table siteops_v2.project_task_dependencies
  alter column template_dependency_id drop not null,
  alter column template_version_id drop not null,
  add column if not exists reason text;
alter table siteops_v2.project_task_dependencies
  add constraint ck_v2_project_dependencies_source check(source_type in ('template','project_manual'));
