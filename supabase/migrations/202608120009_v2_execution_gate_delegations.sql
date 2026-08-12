-- 45-day scheduling POC integration, U13: delegate the chasing of an
-- external approval.
--
-- External approvals are Admin's responsibility - Admin decides whether one
-- applies (202607290006), Admin adds a manual one, and Admin records the
-- outcome. But chasing a landlord or an authority is legwork, and it is not
-- Admin's time. This table is how Admin hands that legwork to an Internal
-- Employee without handing over the decision.
--
-- Deliberately mirrors task_support_assignments (202608020005): same
-- active/ended pair, same one-active-row-per-pair rule, same requirement
-- that the assignee be an active internal_employee member of the project.
-- Delegating an approval and delegating task support are the same act
-- against different objects, and they should not look different.
--
-- Never alters accountability. execution_gates.accountable_pm_user_id
-- stays exactly what it was: the PM whose handover this approval blocks,
-- for escalation and visibility. A delegate chases; they do not own.

BEGIN;

create table if not exists siteops_v2.execution_gate_delegations (
    id uuid primary key default gen_random_uuid(),
    execution_gate_id uuid not null references siteops_v2.execution_gates(id) on delete cascade,
    project_id uuid not null references siteops_v2.projects(id) on delete restrict,
    employee_id uuid not null references public.employee_profiles(id) on delete restrict,
    instruction text not null,
    status text not null default 'active',
    starts_at timestamptz not null default now(),
    ends_at timestamptz,
    assigned_by uuid not null references public.users(id) on delete restrict,
    ended_by uuid references public.users(id) on delete restrict,
    end_reason text,
    created_at timestamptz not null default now(),
    constraint ck_v2_execution_gate_delegations_status
      check (status in ('active', 'ended')),
    constraint ck_v2_execution_gate_delegations_status_ends_at_pair
      check ((status = 'active' and ends_at is null) or (status = 'ended' and ends_at is not null))
);

-- One active delegate per gate/employee pair, enforced here as well as in
-- the service - a duplicate would mean two rows to end when the delegation
-- is handed on, and one of them would be missed.
create unique index if not exists uq_v2_execution_gate_delegations_active_pair
  on siteops_v2.execution_gate_delegations(execution_gate_id, employee_id)
  where status = 'active';

create index if not exists ix_v2_execution_gate_delegations_gate
  on siteops_v2.execution_gate_delegations(execution_gate_id);
create index if not exists ix_v2_execution_gate_delegations_employee
  on siteops_v2.execution_gate_delegations(employee_id);

revoke all on siteops_v2.execution_gate_delegations from anon, authenticated;

COMMIT;
