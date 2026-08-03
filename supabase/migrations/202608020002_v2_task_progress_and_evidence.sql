-- U3: Progress updates and evidence submission (BR-... / R3).
--
-- task_progress_updates is an append-only log of progress notes against an
-- execution-layer task (siteops_v2.tasks); it never itself changes
-- tasks.lifecycle_status - it's evidence for a later `submitted` transition
-- (U2's TaskLifecycleService) to reference.
--
-- file_objects / task_evidence are a REAL foreign-key link, not a
-- polymorphic entity_type/entity_id reference (see
-- docs/v2/02_V2_DATA_MODEL_SPECIFICATION.md section 5). file_objects only
-- stores metadata (storage_key, mime_type, size_bytes, checksum) - the
-- actual bytes live on disk under a NEW, separate directory
-- (`evidence_storage/`, see backend/app/config.py's `evidence_upload_dir`)
-- that is never passed to FastAPI's StaticFiles and is therefore never
-- publicly reachable at a `/uploads/...` URL. Access is only through the
-- authenticated download route
-- (GET /api/v2/projects/{project_id}/tasks/{task_id}/evidence/{file_id}).

create table if not exists siteops_v2.task_progress_updates (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references siteops_v2.tasks(id) on delete restrict,
  project_id uuid not null references siteops_v2.projects(id) on delete restrict,
  update_type text not null check (update_type in ('note', 'evidence')),
  status_claim text,
  note text,
  submitted_by uuid not null references users(id) on delete restrict,
  source text not null default 'portal' check (source in ('portal', 'whatsapp', 'system')),
  created_at timestamptz not null default now()
);
create index if not exists ix_v2_task_progress_updates_task on siteops_v2.task_progress_updates(task_id);
create index if not exists ix_v2_task_progress_updates_project on siteops_v2.task_progress_updates(project_id);
revoke all on table siteops_v2.task_progress_updates from anon, authenticated;

create table if not exists siteops_v2.file_objects (
  id uuid primary key default gen_random_uuid(),
  storage_key text not null unique,
  original_filename text not null,
  mime_type text not null,
  size_bytes integer not null check (size_bytes > 0),
  checksum text not null,
  uploaded_by uuid not null references users(id) on delete restrict,
  created_at timestamptz not null default now()
);
revoke all on table siteops_v2.file_objects from anon, authenticated;

create table if not exists siteops_v2.task_evidence (
  id uuid primary key default gen_random_uuid(),
  task_progress_update_id uuid not null references siteops_v2.task_progress_updates(id) on delete restrict,
  file_id uuid not null references siteops_v2.file_objects(id) on delete restrict,
  evidence_type text not null default 'photo',
  caption text,
  created_at timestamptz not null default now(),
  constraint uq_v2_task_evidence_update_file unique (task_progress_update_id, file_id)
);
create index if not exists ix_v2_task_evidence_progress_update on siteops_v2.task_evidence(task_progress_update_id);
create index if not exists ix_v2_task_evidence_file on siteops_v2.task_evidence(file_id);
revoke all on table siteops_v2.task_evidence from anon, authenticated;
