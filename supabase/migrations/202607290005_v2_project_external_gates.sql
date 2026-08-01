create table if not exists siteops_v2.project_external_gates (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references siteops_v2.projects(id) on delete cascade,
    template_version_id uuid not null references siteops_v2.v2_template_versions(id) on delete restrict,
    template_gate_id uuid not null references siteops_v2.v2_template_external_gates(id) on delete restrict,
    original_code text not null,
    template_sequence integer not null check (template_sequence > 0),
    approval_name text not null,
    description text,
    external_party text,
    required_by_type text,
    required_by_value text,
    impact text,
    mapping_classification text not null check (mapping_classification in ('exact','broad_text','unmapped')),
    broad_mapping_text text,
    requires_configuration boolean not null default false,
    status text not null default 'pending_review' check (status = 'pending_review'),
    source_type text not null default 'template' check (source_type = 'template'),
    accountable_pm_user_id uuid not null references public.users(id) on delete restrict,
    created_at timestamptz not null default now(),
    constraint uq_project_external_gates_project_template_gate unique (project_id, template_gate_id),
    constraint uq_project_external_gates_project_code unique (project_id, original_code),
    constraint ck_project_external_gates_broad_text check (
      (mapping_classification = 'broad_text' and nullif(btrim(broad_mapping_text), '') is not null)
      or (mapping_classification <> 'broad_text' and broad_mapping_text is null)
    )
);

create index if not exists ix_project_external_gates_project_sequence
  on siteops_v2.project_external_gates(project_id, template_sequence);

create table if not exists siteops_v2.project_external_gate_tasks (
    id uuid primary key default gen_random_uuid(),
    project_gate_id uuid not null references siteops_v2.project_external_gates(id) on delete cascade,
    project_task_id uuid not null references siteops_v2.project_tasks(id) on delete restrict,
    template_task_id uuid not null references siteops_v2.v2_template_tasks(id) on delete restrict,
    created_at timestamptz not null default now(),
    constraint uq_project_external_gate_tasks_pair unique (project_gate_id, project_task_id)
);

create index if not exists ix_project_external_gate_tasks_gate
  on siteops_v2.project_external_gate_tasks(project_gate_id);
create index if not exists ix_project_external_gate_tasks_task
  on siteops_v2.project_external_gate_tasks(project_task_id);
