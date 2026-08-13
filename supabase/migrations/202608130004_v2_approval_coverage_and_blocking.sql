-- U8: the coverage and blocking facts an approval carries from its gate.
--
-- U4 created project_external_approvals with the decision itself - status,
-- decided_by, decided_at. Instantiation needs three more, copied from the
-- planning-layer gate at activation so readiness never has to read the
-- planning tables to answer a question about an approval (KTD8).
--
-- blocking: the PM's decision about whether this approval actually gates
--   work. A non-blocking gate arriving here as blocking would stop every task
--   it covers, which is the opposite of what was set. Defaults true because
--   an approval whose intent is unknown must not silently stop gating.
--
-- coverage_state: whether the gate named its tasks explicitly ('exact') or
--   described them in prose / not at all ('unresolved'). Stored rather than
--   inferred from the absence of coverage links: "no links" is ambiguous
--   between "covers nothing" and "we could not tell what it covers", and
--   R10 forbids collapsing the second into the first.
--
-- coverage_text: the gate's original prose, carried so a human scoping an
--   unresolved approval sees what the template actually said.
--
-- Defaults are set so the columns can be added to a table that may already
-- hold rows from an earlier partial run without inventing a coverage claim
-- for them.

begin;

alter table siteops_v2.project_external_approvals
  add column if not exists blocking boolean not null default true,
  add column if not exists coverage_state text not null default 'unresolved',
  add column if not exists coverage_text text;

alter table siteops_v2.project_external_approvals
  drop constraint if exists ck_v2_project_external_approvals_coverage_state;
alter table siteops_v2.project_external_approvals
  add constraint ck_v2_project_external_approvals_coverage_state
  check (coverage_state in ('exact', 'unresolved'));

-- Prose belongs to an unresolved approval only. An 'exact' approval names its
-- tasks in the coverage table, so carrying prose beside them would leave two
-- descriptions of the same scope free to disagree.
alter table siteops_v2.project_external_approvals
  drop constraint if exists ck_v2_project_external_approvals_coverage_text;
alter table siteops_v2.project_external_approvals
  add constraint ck_v2_project_external_approvals_coverage_text
  check (coverage_state = 'unresolved' or coverage_text is null);

-- Readiness asks "which pending, blocking approvals cover this project?" on
-- every recompute, so blocking joins status in the lookup rather than being
-- filtered afterwards.
create index if not exists ix_v2_project_external_approvals_project_blocking
  on siteops_v2.project_external_approvals(project_id, status)
  where blocking;

commit;
