-- Permit project-specific tasks without weakening template task provenance.
-- FastAPI remains the authoritative application layer; existing table grants remain unchanged.

alter table siteops_v2.project_tasks
    alter column template_task_id drop not null;

alter table siteops_v2.project_tasks
    drop constraint if exists ck_v2_project_tasks_source_type;

alter table siteops_v2.project_tasks
    add constraint ck_v2_project_tasks_source_type
    check (source_type in ('template', 'project_manual'));

alter table siteops_v2.project_tasks
    add constraint ck_v2_project_tasks_source_reference
    check (
        (source_type = 'template' and template_task_id is not null)
        or
        (source_type = 'project_manual' and template_task_id is null)
    );
