BEGIN;

ALTER TABLE siteops_v2.project_external_gates
  ALTER COLUMN template_version_id DROP NOT NULL,
  ALTER COLUMN template_gate_id DROP NOT NULL,
  ADD COLUMN IF NOT EXISTS blocking boolean NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS creation_reason text;

ALTER TABLE siteops_v2.project_external_gates
  DROP CONSTRAINT IF EXISTS ck_v2_project_external_gates_source,
  ADD CONSTRAINT ck_v2_project_external_gates_source
    CHECK (source_type IN ('template', 'project_manual')),
  ADD CONSTRAINT ck_v2_project_external_gates_source_reference
    CHECK (
      (source_type = 'template' AND template_version_id IS NOT NULL AND template_gate_id IS NOT NULL)
      OR
      (source_type = 'project_manual' AND template_version_id IS NULL AND template_gate_id IS NULL)
    );

ALTER TABLE siteops_v2.project_external_gate_tasks
  ALTER COLUMN template_task_id DROP NOT NULL;

COMMIT;
