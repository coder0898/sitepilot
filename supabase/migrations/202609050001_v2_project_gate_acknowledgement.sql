-- Plan (U5): gate acknowledgement overlay (R3/R5/R6).
--
-- `project_gate_acknowledgements` records an 'accepted'/'declined' response
-- from the employee a `project_external_approvals` gate is assigned to.
-- Append-only, mirroring `siteops_v2.vendor_acknowledgements`'s own
-- precedent exactly: every response is kept as its own row, even a second
-- one against the same gate, and none is ever overwritten or deleted.
--
-- Purely additive - this table stands entirely alongside the formal
-- assign/submit/decide state machine and never writes
-- `project_external_approvals.status`, the same non-lifecycle framing
-- already applied to `siteops_v2.project_external_approval_status_checks`.

create table if not exists siteops_v2.project_gate_acknowledgements (
  id uuid primary key default gen_random_uuid(),
  approval_id uuid not null references siteops_v2.project_external_approvals(id) on delete restrict,
  response text not null check (response in ('accepted', 'declined')),
  note text,
  recorded_by uuid not null references users(id) on delete restrict,
  created_at timestamptz not null default now()
);
create index if not exists ix_v2_project_gate_acknowledgements_approval
  on siteops_v2.project_gate_acknowledgements(approval_id);
revoke all on table siteops_v2.project_gate_acknowledgements from anon, authenticated;
