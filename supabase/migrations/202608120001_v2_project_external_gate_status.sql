-- 45-day scheduling POC integration, U1: let an external gate hold a real
-- approval status instead of the single frozen value it was created with,
-- and close two live constraint-naming defects on the way past.
--
-- WHY THE DROP LIST HAS TWO NAMES FOR ONE RULE
--
-- 202607290005 declared the status and source_type checks *inline and
-- unnamed*:
--
--     status      text not null default 'pending_review' check (status = 'pending_review'),
--     source_type text not null default 'template'       check (source_type = 'template'),
--
-- Postgres auto-names an inline column check `<table>_<column>_check`, so
-- the live database carries `project_external_gates_status_check` and
-- `project_external_gates_source_type_check`. The ORM in
-- backend/app/project_models.py declares the same two rules under
-- `ck_v2_project_external_gates_status` and `..._source` - names Postgres
-- has never held. A database built from these SQL files and a database
-- built from ORM metadata therefore disagree about what the constraints
-- are called, and only the SQL names are real in production.
--
-- 202607290007 tried to relax source_type and dropped only the ORM name.
-- That drop was a no-op against Postgres, so its permissive replacement
-- was added *alongside* the strict original rather than in place of it.
-- Both now sit on the table and the stricter wins, which means
-- `source_type = 'project_manual'` - the insert in
-- backend/app/services/project_manual_gate.py - is rejected in production
-- while passing in the SQLite test harness, because that harness builds
-- its tables from ORM metadata and so only ever sees the permissive rule.
-- 202607290009 repeated the mistake on project_task_dependencies, which
-- breaks manual dependency creation in routes/dependencies_v2.py the same
-- way. Both are fixed below.
--
-- Contrast: 202607290002 and 202607290004 named the equivalent
-- project_tasks constraint explicitly, which is why manual *tasks* work.
--
-- Every drop is `if exists` on purpose. A database not built from these
-- files - including a freshly ORM-built one - has no auto-named
-- constraint, and an unqualified drop would abort the whole transaction.
-- For the same reason this file is wrapped in BEGIN/COMMIT, following
-- 202607290007 rather than the majority style: it drops constraints that
-- guard live rows, so a partial apply must not be possible.

BEGIN;

-- Status: admit the five persisted lifecycle values. `pending` is the API
-- and UI spelling only; it is never stored.
ALTER TABLE siteops_v2.project_external_gates
  DROP CONSTRAINT IF EXISTS project_external_gates_status_check,
  DROP CONSTRAINT IF EXISTS ck_project_external_gates_status,
  DROP CONSTRAINT IF EXISTS ck_v2_project_external_gates_status,
  ADD CONSTRAINT ck_v2_project_external_gates_status
    CHECK (status IN ('not_required', 'pending_review', 'submitted', 'approved', 'rejected'));

-- D1: the strict auto-named survivor that still pins source_type to
-- 'template' and blocks every manual gate. The permissive
-- ck_v2_project_external_gates_source added by 202607290007 is already
-- correct and is deliberately left standing.
ALTER TABLE siteops_v2.project_external_gates
  DROP CONSTRAINT IF EXISTS project_external_gates_source_type_check;

-- D3: the same survivor on the dependency table, blocking manual
-- dependencies. Its permissive ORM-named replacement from 202607290009
-- also stays.
ALTER TABLE siteops_v2.project_task_dependencies
  DROP CONSTRAINT IF EXISTS project_task_dependencies_source_type_check;

-- Who recorded the current status and when. Both nullable: every existing
-- row predates the lifecycle and has no recorder.
ALTER TABLE siteops_v2.project_external_gates
  ADD COLUMN IF NOT EXISTS status_recorded_by_user_id uuid REFERENCES public.users(id) ON DELETE RESTRICT,
  ADD COLUMN IF NOT EXISTS status_recorded_at timestamptz;

COMMIT;
