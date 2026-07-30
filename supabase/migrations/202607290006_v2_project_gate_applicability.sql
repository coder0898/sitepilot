alter table siteops_v2.project_external_gates
  add column if not exists applicability_state text not null default 'pending_review';

alter table siteops_v2.project_external_gates
  drop constraint if exists ck_project_external_gates_applicability_state;

alter table siteops_v2.project_external_gates
  add constraint ck_project_external_gates_applicability_state
  check (applicability_state in ('pending_review', 'applicable', 'not_applicable'));

create table if not exists siteops_v2.project_external_gate_applicability_decisions (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references siteops_v2.projects(id) on delete cascade,
    project_gate_id uuid not null references siteops_v2.project_external_gates(id) on delete cascade,
    previous_state text not null check (previous_state in ('pending_review', 'applicable', 'not_applicable')),
    decision text not null check (decision in ('applicable', 'not_applicable')),
    reason text not null,
    actor_user_id uuid not null references public.users(id) on delete restrict,
    decided_at timestamptz not null default now()
);

create index if not exists ix_project_gate_applicability_history
  on siteops_v2.project_external_gate_applicability_decisions(project_gate_id, decided_at desc);
