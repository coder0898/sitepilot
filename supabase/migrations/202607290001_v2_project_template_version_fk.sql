-- Phase 3.1A: make the persisted project -> published template-version reference relational.
-- No project task-generation tables are introduced by this migration.

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'fk_v2_projects_template_version'
          and conrelid = 'siteops_v2.projects'::regclass
    ) then
        alter table siteops_v2.projects
            add constraint fk_v2_projects_template_version
            foreign key (template_version_id)
            references siteops_v2.v2_template_versions(id)
            on delete restrict;
    end if;
end
$$;

create index if not exists ix_v2_projects_template_version
    on siteops_v2.projects(template_version_id);
