-- Template Builder Phase 2: reference material and "what proof is needed?"
-- instructions, authored on template tasks and prerequisite approvals.
--
-- Additive only: two nullable columns and two new link tables. No existing
-- row is changed, so every template and project keeps its current behaviour.
--
-- Projects read these through the template version they are pinned to
-- (task -> baseline task -> project task -> template task, and
-- approval -> project gate -> template gate). A published version is never
-- edited, so a later version can never change an existing project's
-- reference material or instructions.
--
-- Reference files reuse siteops_v2.file_objects and the private `evidence`
-- storage bucket under a `template-references/` key prefix. Evidence
-- retention only follows task_evidence / project_external_approval_evidence,
-- so it never purges reference files. A cloned version links the SAME
-- file_objects rows (no byte copy), which is safe because a file is never
-- modified in place.

alter table siteops_v2.v2_template_tasks
  add column if not exists evidence_instructions text;

alter table siteops_v2.v2_template_external_gates
  add column if not exists evidence_instructions text;

create table if not exists siteops_v2.v2_template_task_reference_files (
  id uuid primary key default gen_random_uuid(),
  template_task_id uuid not null references siteops_v2.v2_template_tasks(id) on delete restrict,
  file_id uuid not null references siteops_v2.file_objects(id) on delete restrict,
  description text,
  created_by uuid not null references users(id) on delete restrict,
  created_at timestamptz not null default now(),
  constraint uq_v2_template_task_reference_files_task_file unique (template_task_id, file_id)
);
create index if not exists ix_v2_template_task_reference_files_task
  on siteops_v2.v2_template_task_reference_files(template_task_id);
create index if not exists ix_v2_template_task_reference_files_file
  on siteops_v2.v2_template_task_reference_files(file_id);

create table if not exists siteops_v2.v2_template_gate_reference_files (
  id uuid primary key default gen_random_uuid(),
  gate_id uuid not null references siteops_v2.v2_template_external_gates(id) on delete restrict,
  file_id uuid not null references siteops_v2.file_objects(id) on delete restrict,
  description text,
  created_by uuid not null references users(id) on delete restrict,
  created_at timestamptz not null default now(),
  constraint uq_v2_template_gate_reference_files_gate_file unique (gate_id, file_id)
);
create index if not exists ix_v2_template_gate_reference_files_gate
  on siteops_v2.v2_template_gate_reference_files(gate_id);
create index if not exists ix_v2_template_gate_reference_files_file
  on siteops_v2.v2_template_gate_reference_files(file_id);

comment on table siteops_v2.v2_template_task_reference_files is
  'Admin-provided reference material for a template task (not execution evidence). Only draft versions may change.';
comment on table siteops_v2.v2_template_gate_reference_files is
  'Admin-provided reference material for a template prerequisite approval (not execution evidence). Only draft versions may change.';

alter table siteops_v2.v2_template_task_reference_files enable row level security;
alter table siteops_v2.v2_template_gate_reference_files enable row level security;
revoke all on table siteops_v2.v2_template_task_reference_files from anon, authenticated;
revoke all on table siteops_v2.v2_template_gate_reference_files from anon, authenticated;
