create schema if not exists siteops_v2;

create table if not exists siteops_v2.projects (
    id uuid primary key default gen_random_uuid(),
    code text not null unique,
    name text not null,
    client_name text not null,
    site_address text not null,
    description text,
    start_date date not null,
    target_handover_date date,
    template_version_id uuid,
    status text not null default 'draft',
    activated_at timestamptz,
    activated_by uuid references public.users(id) on delete restrict,
    created_by uuid not null references public.users(id) on delete restrict,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint ck_v2_project_code_format check (code ~ '^[A-Z0-9][A-Z0-9-]{2,29}$'),
    constraint ck_v2_project_status check (status in ('draft', 'active', 'on_hold', 'completed', 'archived')),
    constraint ck_v2_project_dates check (target_handover_date is null or target_handover_date >= start_date),
    constraint ck_v2_project_activation_fields check (
        status <> 'active' or (
            activated_at is not null and
            activated_by is not null and
            template_version_id is not null and
            target_handover_date is not null
        )
    )
);

create table if not exists siteops_v2.project_memberships (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references siteops_v2.projects(id) on delete restrict,
    employee_id uuid not null references public.employee_profiles(id) on delete restrict,
    project_role text not null,
    starts_at timestamptz not null default now(),
    ends_at timestamptz,
    assigned_by uuid not null references public.users(id) on delete restrict,
    assignment_reason text not null,
    created_at timestamptz not null default now(),
    constraint ck_v2_project_membership_role check (project_role in ('project_manager', 'site_supervisor', 'internal_employee')),
    constraint ck_v2_project_membership_period check (ends_at is null or ends_at > starts_at)
);

create unique index if not exists uq_v2_active_project_manager
    on siteops_v2.project_memberships(project_id)
    where project_role = 'project_manager' and ends_at is null;

create unique index if not exists uq_v2_active_site_supervisor
    on siteops_v2.project_memberships(project_id)
    where project_role = 'site_supervisor' and ends_at is null;

create unique index if not exists uq_v2_active_internal_employee
    on siteops_v2.project_memberships(project_id, employee_id)
    where project_role = 'internal_employee' and ends_at is null;

create table if not exists siteops_v2.audit_events (
    id uuid primary key default gen_random_uuid(),
    actor_user_id uuid references public.users(id) on delete set null,
    action text not null,
    entity_type text not null,
    entity_id uuid not null,
    project_id uuid references siteops_v2.projects(id) on delete set null,
    correlation_id uuid not null default gen_random_uuid(),
    source text not null default 'portal',
    before_json jsonb,
    after_json jsonb,
    reason text not null,
    occurred_at timestamptz not null default now(),
    constraint ck_v2_audit_source check (source in ('portal', 'whatsapp', 'system'))
);

create index if not exists ix_v2_project_memberships_employee on siteops_v2.project_memberships(employee_id, ends_at);
create index if not exists ix_v2_project_audit on siteops_v2.audit_events(project_id, occurred_at desc);
create index if not exists ix_v2_projects_status on siteops_v2.projects(status, updated_at desc);

comment on column siteops_v2.projects.target_handover_date is
    'Optional while draft. Set from the approved template duration when a template is applied, unless already confirmed manually.';

revoke update, delete on siteops_v2.audit_events from anon, authenticated;
