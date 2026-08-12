-- 45-day scheduling POC integration, U2: readable history for every
-- external approval outcome.
--
-- Keyed on the execution gate row (U3's execution_gates), not the
-- planning-layer gate. Status after activation is only ever written on the
-- execution row - readiness reads execution rows and would never see an
-- approval recorded against planning, so a status written there would
-- release no work at all.
--
-- Its own table rather than reusing
-- project_external_gate_applicability_decisions. Those two histories
-- answer different questions - "does this approval apply to this project?"
-- is a Draft-time scoping decision by an Admin, "has it been granted yet?"
-- is an execution-time outcome owned by the accountable PM. Merging them
-- would put two lifecycles with different actors and different authority
-- rules in one table and force every reader to filter.
--
-- reason is NOT NULL: an approval outcome that does not say why is not an
-- audit record, and the rejection reason is the field site teams actually
-- need to read.

BEGIN;

create table if not exists siteops_v2.execution_gate_status_history (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references siteops_v2.projects(id) on delete cascade,
    execution_gate_id uuid not null references siteops_v2.execution_gates(id) on delete cascade,
    previous_status text not null,
    new_status text not null,
    reason text not null,
    actor_user_id uuid not null references public.users(id) on delete restrict,
    recorded_at timestamptz not null default now(),
    constraint ck_v2_execution_gate_status_history_new_status
      check (new_status in ('not_required', 'pending_review', 'submitted', 'approved', 'rejected')),
    constraint ck_v2_execution_gate_status_history_previous_status
      check (previous_status in ('not_required', 'pending_review', 'submitted', 'approved', 'rejected'))
);

create index if not exists ix_v2_execution_gate_status_history_gate
  on siteops_v2.execution_gate_status_history(execution_gate_id, recorded_at);

revoke all on siteops_v2.execution_gate_status_history from anon, authenticated;

COMMIT;
