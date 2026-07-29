create table if not exists siteops_v2.project_tasks (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references siteops_v2.projects(id) on delete cascade,
    template_version_id uuid not null references siteops_v2.v2_template_versions(id) on delete restrict,
    template_task_id uuid not null references siteops_v2.v2_template_tasks(id) on delete restrict,
    original_code text not null,
    template_sequence integer not null,
    title text not null,
    description text,
    schedule_classification text not null,
    planned_start_day smallint,
    planned_end_day smallint,
    phase text,
    category text,
    applicability text not null,
    task_class text,
    task_kind text,
    evidence_required boolean not null default false,
    duration_days integer,
    source_type text not null default 'template',
    lifecycle_status text not null default 'draft',
    created_at timestamptz not null default now(),
    constraint uq_v2_project_tasks_project_template_task unique (project_id, template_task_id),
    constraint uq_v2_project_tasks_project_code unique (project_id, original_code),
    constraint ck_v2_project_tasks_sequence_positive check (template_sequence > 0),
    constraint ck_v2_project_tasks_source_type check (source_type = 'template'),
    constraint ck_v2_project_tasks_draft_lifecycle check (lifecycle_status = 'draft'),
    constraint ck_v2_project_tasks_applicability check (applicability in ('mandatory', 'conditional')),
    constraint ck_v2_project_tasks_schedule_classification check (schedule_classification in ('pre_activation', 'execution'))
);

create index if not exists ix_v2_project_tasks_project_sequence
    on siteops_v2.project_tasks(project_id, template_sequence);

create index if not exists ix_v2_project_tasks_template_task
    on siteops_v2.project_tasks(template_task_id);

revoke all on table siteops_v2.project_tasks from anon, authenticated;
