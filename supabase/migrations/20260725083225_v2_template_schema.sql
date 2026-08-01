-- Phase 1 V2 template schema.
-- Access decision:
--   * FastAPI is the authoritative application access layer.
--   * RLS is enabled on every table with no browser-client policies.
--   * anon/authenticated privileges are revoked, so draft versions are never
--     exposed directly through Supabase browser clients.

create schema if not exists siteops_v2;

create table if not exists siteops_v2.v2_templates (
    id uuid primary key default gen_random_uuid(),
    code text not null,
    name text not null,
    description text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint uq_v2_templates_code unique (code)
);

create table if not exists siteops_v2.v2_template_versions (
    id uuid primary key default gen_random_uuid(),
    template_id uuid not null references siteops_v2.v2_templates(id) on delete restrict,
    version_no integer not null,
    status text not null default 'draft',
    duration_days integer not null,
    change_note text,
    content_hash text,
    is_current_published boolean not null default false,
    created_by uuid not null references public.users(id) on delete restrict,
    published_by uuid references public.users(id) on delete restrict,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    published_at timestamptz,
    constraint uq_v2_template_versions_template_version unique (template_id, version_no),
    constraint ck_v2_template_versions_version_positive check (version_no > 0),
    constraint ck_v2_template_versions_status check (status in ('draft', 'published', 'archived')),
    constraint ck_v2_template_versions_duration_positive check (duration_days > 0),
    constraint ck_v2_template_versions_published_fields check (
        status <> 'published' or published_at is not null
    ),
    constraint ck_v2_template_versions_current_status check (
        not is_current_published or status = 'published'
    )
);

create unique index if not exists uq_v2_template_versions_current_published
    on siteops_v2.v2_template_versions(template_id)
    where is_current_published;

create index if not exists ix_v2_template_versions_template
    on siteops_v2.v2_template_versions(template_id, version_no desc);

create index if not exists ix_v2_template_versions_status
    on siteops_v2.v2_template_versions(status, updated_at desc);

create table if not exists siteops_v2.v2_template_tasks (
    id uuid primary key default gen_random_uuid(),
    template_version_id uuid not null references siteops_v2.v2_template_versions(id) on delete restrict,
    code text not null,
    sequence_no integer not null,
    title text not null,
    description text,
    schedule_classification text not null,
    planned_start_day smallint,
    planned_end_day smallint,
    phase text,
    category text,
    applicability text not null default 'mandatory',
    task_class text,
    task_kind text,
    evidence_required boolean not null default false,
    duration_days integer,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint uq_v2_template_tasks_version_code unique (template_version_id, code),
    constraint uq_v2_template_tasks_version_sequence unique (template_version_id, sequence_no),
    constraint ck_v2_template_tasks_sequence_positive check (sequence_no > 0),
    constraint ck_v2_template_tasks_schedule_classification check (
        schedule_classification in ('pre_activation', 'execution')
    ),
    constraint ck_v2_template_tasks_applicability check (
        applicability in ('mandatory', 'conditional')
    ),
    constraint ck_v2_template_tasks_duration_positive check (
        duration_days is null or duration_days > 0
    ),
    constraint ck_v2_template_tasks_day_order check (
        planned_start_day is null or planned_end_day is null or planned_start_day <= planned_end_day
    ),
    constraint ck_v2_template_tasks_schedule_days check (
        (
            schedule_classification = 'pre_activation'
            and planned_start_day is null
            and planned_end_day is null
        )
        or
        (
            schedule_classification = 'execution'
            and planned_start_day between 1 and 45
            and planned_end_day between 1 and 45
        )
    )
);

create index if not exists ix_v2_template_tasks_version
    on siteops_v2.v2_template_tasks(template_version_id, sequence_no);

create index if not exists ix_v2_template_tasks_schedule
    on siteops_v2.v2_template_tasks(template_version_id, schedule_classification, planned_start_day);

create table if not exists siteops_v2.v2_template_task_dependencies (
    id uuid primary key default gen_random_uuid(),
    template_version_id uuid not null references siteops_v2.v2_template_versions(id) on delete restrict,
    predecessor_task_id uuid not null references siteops_v2.v2_template_tasks(id) on delete restrict,
    successor_task_id uuid not null references siteops_v2.v2_template_tasks(id) on delete restrict,
    dependency_type text not null,
    blocking boolean not null default true,
    rule_text text,
    sequence_no integer not null,
    created_at timestamptz not null default now(),
    constraint uq_v2_template_task_dependency_edge unique (
        predecessor_task_id,
        successor_task_id,
        dependency_type
    ),
    constraint ck_v2_template_task_dependencies_not_self check (
        predecessor_task_id <> successor_task_id
    ),
    constraint ck_v2_template_task_dependencies_type check (
        dependency_type in ('finish_to_start', 'start_to_start')
    ),
    constraint ck_v2_template_task_dependencies_sequence_positive check (sequence_no > 0)
);

create index if not exists ix_v2_template_task_dependencies_version
    on siteops_v2.v2_template_task_dependencies(template_version_id, sequence_no);

create index if not exists ix_v2_template_task_dependencies_predecessor
    on siteops_v2.v2_template_task_dependencies(predecessor_task_id);

create index if not exists ix_v2_template_task_dependencies_successor
    on siteops_v2.v2_template_task_dependencies(successor_task_id);

create table if not exists siteops_v2.v2_template_external_gates (
    id uuid primary key default gen_random_uuid(),
    template_version_id uuid not null references siteops_v2.v2_template_versions(id) on delete restrict,
    code text not null,
    approval_name text not null,
    description text,
    external_party text,
    required_by_type text,
    required_by_value text,
    impact text,
    mapping_classification text not null,
    broad_mapping_text text,
    requires_configuration boolean not null default false,
    sequence_no integer not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint uq_v2_template_external_gates_version_code unique (template_version_id, code),
    constraint ck_v2_template_external_gates_mapping check (
        mapping_classification in ('exact', 'broad_text', 'unmapped')
    ),
    constraint ck_v2_template_external_gates_sequence_positive check (sequence_no > 0),
    constraint ck_v2_template_external_gates_configuration check (
        mapping_classification = 'exact' or requires_configuration
    ),
    constraint ck_v2_template_external_gates_broad_text check (
        (mapping_classification = 'broad_text' and nullif(btrim(broad_mapping_text), '') is not null)
        or
        (mapping_classification <> 'broad_text' and broad_mapping_text is null)
    )
);

create index if not exists ix_v2_template_external_gates_version
    on siteops_v2.v2_template_external_gates(template_version_id, sequence_no);

create index if not exists ix_v2_template_external_gates_mapping
    on siteops_v2.v2_template_external_gates(mapping_classification, requires_configuration);

create table if not exists siteops_v2.v2_template_external_gate_tasks (
    id uuid primary key default gen_random_uuid(),
    gate_id uuid not null references siteops_v2.v2_template_external_gates(id) on delete restrict,
    template_task_id uuid not null references siteops_v2.v2_template_tasks(id) on delete restrict,
    created_at timestamptz not null default now(),
    constraint uq_v2_template_external_gate_tasks_pair unique (gate_id, template_task_id)
);

create index if not exists ix_v2_template_external_gate_tasks_gate
    on siteops_v2.v2_template_external_gate_tasks(gate_id);

create index if not exists ix_v2_template_external_gate_tasks_task
    on siteops_v2.v2_template_external_gate_tasks(template_task_id);

comment on table siteops_v2.v2_templates is
    'Stable V2 template identity. Versioned content is stored in v2_template_versions and child tables.';
comment on table siteops_v2.v2_template_task_dependencies is
    'Service/import validation must ensure predecessor and successor tasks belong to template_version_id.';
comment on table siteops_v2.v2_template_external_gate_tasks is
    'Service/import validation must ensure gate and task share a template version. Broad-text mappings must not create rows.';

alter table siteops_v2.v2_templates enable row level security;
alter table siteops_v2.v2_template_versions enable row level security;
alter table siteops_v2.v2_template_tasks enable row level security;
alter table siteops_v2.v2_template_task_dependencies enable row level security;
alter table siteops_v2.v2_template_external_gates enable row level security;
alter table siteops_v2.v2_template_external_gate_tasks enable row level security;

revoke all on table siteops_v2.v2_templates from anon, authenticated;
revoke all on table siteops_v2.v2_template_versions from anon, authenticated;
revoke all on table siteops_v2.v2_template_tasks from anon, authenticated;
revoke all on table siteops_v2.v2_template_task_dependencies from anon, authenticated;
revoke all on table siteops_v2.v2_template_external_gates from anon, authenticated;
revoke all on table siteops_v2.v2_template_external_gate_tasks from anon, authenticated;
