-- 45-day scheduling POC integration, U14 (R13): attach documents to an
-- external approval as proof of submission or outcome.
--
-- The status lifecycle records that the landlord approved. This records the
-- signed letter that says so. Without it the portal asserts approvals it
-- cannot evidence, which is exactly the wrong way round for the artefact an
-- external authority issued.
--
-- Bytes live in file_objects, the same private store task evidence uses -
-- under settings.evidence_upload_dir, a directory deliberately never passed
-- to StaticFiles. A signed landlord letter or a fire NOC is not something to
-- leave on a guessable public URL. The only read path is an authenticated
-- route that checks project access first.
--
-- A real foreign key to execution_gates, not a polymorphic
-- entity_type/entity_id pair - the same call task_evidence made, for the
-- same reason: a polymorphic link cannot be enforced by the database and
-- turns every join into a filter somebody can forget.

BEGIN;

create table if not exists siteops_v2.execution_gate_documents (
    id uuid primary key default gen_random_uuid(),
    execution_gate_id uuid not null references siteops_v2.execution_gates(id) on delete cascade,
    project_id uuid not null references siteops_v2.projects(id) on delete restrict,
    file_id uuid not null references siteops_v2.file_objects(id) on delete restrict,
    document_type text not null,
    caption text,
    uploaded_by uuid not null references public.users(id) on delete restrict,
    created_at timestamptz not null default now(),
    constraint uq_v2_execution_gate_documents_gate_file unique (execution_gate_id, file_id),
    -- 'submission' is what was sent to the authority; 'outcome' is what came
    -- back. Which one a file is decides whether it evidences the claim that
    -- the gate was submitted or the claim that it was decided.
    constraint ck_v2_execution_gate_documents_type
      check (document_type in ('submission', 'outcome', 'supporting'))
);

create index if not exists ix_v2_execution_gate_documents_gate
  on siteops_v2.execution_gate_documents(execution_gate_id);
create index if not exists ix_v2_execution_gate_documents_file
  on siteops_v2.execution_gate_documents(file_id);

revoke all on siteops_v2.execution_gate_documents from anon, authenticated;

COMMIT;
