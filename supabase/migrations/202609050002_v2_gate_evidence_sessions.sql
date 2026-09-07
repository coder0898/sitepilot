-- Plan: WhatsApp Gate Workflow (U8, KTD4-KTD9).
--
-- `gate_evidence_sessions` buffers evidence an employee sends over WhatsApp
-- for one `project_external_approvals` gate - opened by `GATEOPEN <ref>` and
-- closed by `GATECLOSE` (`project_gate_evidence_session.py`). Every inbound
-- text/attachment while a session is open appends to it rather than
-- submitting on its own; `close_session` is the only path that ever calls
-- `ProjectGateSubmissionService.submit()`.
--
-- Modeled on `escalation_tracking`'s "one open row, partial unique index on
-- the open state" pattern (KTD4):
-- `uq_v2_gate_evidence_sessions_employee_open` enforces at most one open
-- session (`closed_at is null and expired_at is null`) per employee at the
-- database level, not just in application logic -
-- `GateEvidenceSessionService.open_session`'s own proactive check is the
-- first line of defense, and it treats the `IntegrityError` this index
-- raises on a lost race as a benign rejection rather than a crash, mirroring
-- `EscalationTracking._commit_new_tracking`'s exact precedent.
--
-- A session ends exactly one of two ways, never both: `closed_at` set by a
-- successful `GATECLOSE` (evidence submitted), or `expired_at` set by the
-- 5-day silence-expiry sweep (KTD5/KTD6 - buffered evidence discarded, never
-- submitted).

create table if not exists siteops_v2.gate_evidence_sessions (
  id uuid primary key default gen_random_uuid(),
  approval_id uuid not null references siteops_v2.project_external_approvals(id) on delete restrict,
  employee_id uuid not null references users(id) on delete restrict,
  note text,
  opened_at timestamptz not null default now(),
  last_activity_at timestamptz not null default now(),
  closed_at timestamptz,
  expired_at timestamptz
);
create index if not exists ix_v2_gate_evidence_sessions_approval
  on siteops_v2.gate_evidence_sessions(approval_id);
create unique index if not exists uq_v2_gate_evidence_sessions_employee_open
  on siteops_v2.gate_evidence_sessions(employee_id)
  where closed_at is null and expired_at is null;
revoke all on table siteops_v2.gate_evidence_sessions from anon, authenticated;

-- `gate_evidence_session_attachments`: one attachment buffered against an
-- open session, linking to an already-downloaded-and-stored `file_objects`
-- row (U10) - a real, typed FK, mirroring
-- `project_external_approval_evidence`'s own non-polymorphic shape. CASCADE
-- on session_id (an attachment has no meaning apart from its session,
-- matching `project_external_approval_evidence`'s CASCADE-to-parent-
-- submission convention); RESTRICT on file_id, same as every other
-- file_objects-linking table in this schema.

create table if not exists siteops_v2.gate_evidence_session_attachments (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references siteops_v2.gate_evidence_sessions(id) on delete cascade,
  file_id uuid not null references siteops_v2.file_objects(id) on delete restrict,
  created_at timestamptz not null default now()
);
create index if not exists ix_v2_gate_evidence_session_attachments_session
  on siteops_v2.gate_evidence_session_attachments(session_id);
revoke all on table siteops_v2.gate_evidence_session_attachments from anon, authenticated;
