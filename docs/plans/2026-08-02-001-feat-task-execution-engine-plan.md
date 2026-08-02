---
title: Task Execution Engine (Release 1, Phase 1 completion)
type: feat
status: active
date: 2026-08-02
origin: docs/brainstorms/release-1-completion-requirements.md
---

# Task Execution Engine (Release 1, Phase 1 completion)

## Summary

Build the missing execution half of the V2 project/task system: a real baseline lock, a task lifecycle state machine, evidence upload, Supervisor verification + PM approval, blocker/delay capture, and task-level accountability with a controlled reassignment/support workflow. The approach adds a new `tasks` execution model (baseline-derived, per `docs/v2/02_V2_DATA_MODEL_SPECIFICATION.md` §5) alongside the existing planning-time `V2ProjectTask` model, rather than relaxing the `lifecycle_status = 'draft'` CheckConstraint on the existing table — this avoids destabilizing the best-tested part of the codebase and matches the architecture package's "baseline instantiates tasks" data flow.

---

## Problem Frame

`V2ProjectTask.lifecycle_status` is hard-constrained to `'draft'` at the database level (`backend/app/project_models.py`, `ck_v2_project_tasks_draft_lifecycle`) — a V2 project task cannot structurally reach any execution state. Everything built so far (templates, project setup, task/gate generation, applicability review, dependency generation) is the pre-activation planning layer; the execution layer (status, evidence, verification, approval, blockers, delays, task-level accountability) has zero backend tables, routes, or tests (see origin doc and `docs/RELEASE_1_IMPLEMENTATION_AUDIT.md`).

---

## Requirements

- R1. A project's baseline (approved task/dependency/gate set) is locked immutably at activation, replacing today's status-flag-only "lock."
- R2. A task instantiated from the baseline can move through a controlled lifecycle: `planned -> ready -> in_progress -> submitted -> verified -> completed`, with rejection and Class A/approval-gate branches per BR-008/BR-009.
- R3. Supervisor or delegated support can submit progress with evidence (photo/file); evidence storage is private with authorized/time-limited access, not the legacy pattern's public static URL.
- R4. Supervisor verifies/rejects `work` tasks; PM approves/rejects `class_a` work and all `approval_gate` tasks; a task cannot complete without the required decisions.
- R5. Blockers and delay events can be recorded against a task, independent of and combinable with lifecycle status (BR-010).
- R6. Task accountability is derived from the active project Supervisor (for `work`) / PM (for `approval_gate`) membership — not a separate stored owner field — with `task_support_assignments` covering delegated Internal Employee help.
- R7. PM/Supervisor replacement and support-employee replacement go through an explicit, reason-required, audited change record (`project_role_changes` / `support_assignment_changes`), closing the gap where today's reassignment is immediate with only a reason string.
- R8. A dependent task cannot enter `in_progress` while a blocking predecessor is unsatisfied (one dependency engine, per BR-011), extended from planning-time dependency generation into a live runtime check.

**Origin flows:** Task Execution Engine (origin doc §5, Phase 1 tracks 1A–1F, excluding the PRD-language "primary owner" framing which R6 supersedes per the signed-off architecture spec).

---

## Scope Boundaries

- No changes to template authoring, project creation, or the planning-time applicability/dependency-generation flow (`templates_v2.py`, `project_task_applicability.py`, etc.) beyond what's needed to read from them at baseline-lock time.
- No approval-gate *scaffolding* changes — `V2ProjectExternalGate`/applicability decisions stay as-is; this plan adds the *decision* step (verification/approval) on top, not a rebuild of gate generation.
- No vendor↔project/task integration (`task_vendor_assignments`) — vendor delegation is out of scope for this plan; a task's accountable owner (Supervisor/PM) stays accountable regardless of vendor execution, per BR-013.
- No WhatsApp, outbox events, or notification delivery — `task_progress_updates.source` supports a future `whatsapp` value, but no provider integration is built here.
- No dashboards or report generation — this plan produces the state and audit data those features will later aggregate.
- No RLS policy authoring beyond what's minimally needed for the new tables' FastAPI-mediated access pattern already used by other V2 tables (Supabase Auth is used for identity only; mutations go through FastAPI per `docs/v2/00_ARCHITECTURE_PACKAGE_INDEX.md`).
- No baseline amendment / mid-project change-order workflow. Once a project activates and its baseline locks (U1), there is no path in this plan to add, remove, or modify a task, gate, or dependency on that active project — the DB-level immutability trigger rejects any such attempt by design. Construction execution commonly requires scope changes mid-project (a new gate required, a task split, a vendor substitution changing dependencies); this plan does not solve that. A future "baseline revision" capability (the data-model spec's `baseline_task_id` nullable-for-approved-exception-tasks allowance in §5 is a plausible seed for it) is explicitly out of scope here and should be scoped as its own follow-up unit once Phase 1 core lands.

### Deferred to Follow-Up Work

- Employee availability event history (`employee_availability_events`) and a dedicated UI toggle for availability — this plan's reassignment flow consumes the existing static `EmployeeProfile.availability` field as-is; upgrading it to an event log is separate work.
- `outbox_events` / `message_deliveries` — flagged in BR-015 as required for every mutation this plan introduces, but building the full outbox pattern is Control Layer (Phase 2) scope per the origin doc.

---

## Context & Research

### Relevant Code and Patterns

- `backend/app/project_models.py` — `V2Project`, `V2ProjectTask` (with the `draft`-only CheckConstraint), `V2ProjectMembership`, `V2AuditEvent`, `V2ProjectExternalGate`. New models join this file (or a new `execution_models.py` in the same schema) following the existing `V2_SCHEMA` table-args convention.
- `backend/app/services/project_task_applicability.py`, `backend/app/services/project_manual_task.py` — the established service-layer pattern: `_require_access`/`_require_draft_access` role+membership check, `with_for_update()` row locking, `V2AuditEvent` write with `before_json`/`after_json`, try/except with rollback on `IntegrityError` → HTTP 409.
- `backend/app/routes/projects_v2.py` — houses the local `add_audit()` helper (line ~69) and the access-control pattern (admin/super_admin bypass, else active `V2ProjectMembership` lookup). New execution routes should either extend this file's helper or promote `add_audit` into a shared module — see Key Technical Decisions.
- `backend/app/routes/projects_v2.py` `project_execution_tasks` endpoint (~line 847) — an existing intentional read-only placeholder with a docstring stating no write path is exposed; this plan's task-status routes are the real implementation this placeholder anticipates.
- `backend/tests/test_project_*_v2.py` — established test pattern: in-memory SQLite with an ATTACHed `siteops_v2` schema, `JSONB` compiled to `JSON`, tables created individually via `Table.create(engine)`, FastAPI router mounted with `get_db`/`current_user` overridden, fixed UUID role constants. New execution tests follow this pattern in a new `test_project_task_execution_v2.py`-style file.
- `frontend/src/features/projects/components/TaskApplicabilityDecisionModal.jsx`, `ProjectTemplateReview.jsx` — modal-with-history UI pattern (local state + on-demand history fetch + `onDecided?.()` callback) to mirror for status/verification/approval UI.
- `frontend/src/api/projectsApi.js` — flat function-per-route API client pattern; already has a stub `executionTasks(projectId)` call wired to the read-only placeholder.

### Pattern Reference Only (legacy `execution_v2`, old schema — not reused directly)

- `backend/app/routes/execution_v2.py` — implements status transition, proof submission (`multipart/form-data`, MIME allowlist, 10MB cap), review (approve/reject), delay-report, and reschedule against the *old* schema. Useful for validation/UX shape, **not** for its evidence-storage approach (writes to public static `/uploads/...` URLs with no auth check — an explicit gap this plan must not repeat, per spec §5 "files are private; access uses authorization and time-limited URLs") or its monolithic single-route-file structure (the new work follows the `services/` split instead).
- `backend/app/services/history.py` (`record_task_assignment`, `set_task_status`) — conceptual analog for `support_assignment_changes`/`project_role_changes`, but assigns *vendors*, not employees; not directly reusable.

### Institutional Learnings

- No `docs/solutions/` learnings exist yet in this repo. Recommend running `/ce-compound` after this plan ships to seed that knowledge base with the migration/constraint/audit patterns established here, since this is a large, precedent-setting subsystem for the rest of Release 1.

---

## Key Technical Decisions

- **New `tasks`/`project_baselines`/`baseline_tasks` tables instead of relaxing the `draft` CheckConstraint on `V2ProjectTask`**: The architecture spec's ER model shows `PROJECT_BASELINE ||--o{ BASELINE_TASK` instantiating `TASK` as a distinct entity from the planning-time `project_tasks`. Relaxing the existing constraint would let planning-time and execution-time task semantics leak into one table and risks a rushed migration on the codebase's best-tested surface. Building new tables keeps `V2ProjectTask` purely a planning/authoring artifact and `tasks` purely an execution artifact, matching principle "lifecycle status and operational conditions are separate."
- **Baseline lock happens at project activation, synchronously, in the same transaction as the `draft -> active` status change**: `project_baselines`/`baseline_tasks` snapshot the then-current `V2ProjectTask`/dependency/gate rows (only `included`/`decision_state=included` rows), then `tasks`/`task_dependencies` are instantiated from `baseline_tasks`. This closes the "Activation locks the baseline" gap (BR-002) the audit flagged as unenforced.
- **Task accountability is derived, not stored** (R6): no `owner_employee_id` column on `tasks`. Verification/approval/status-mutation endpoints resolve the accountable Supervisor/PM by querying the active `V2ProjectMembership` for the project at call time, matching BR-004's "derived from dated project-membership history, not an arbitrary task-owner dropdown."
- **Audit helper consolidation**: promote `projects_v2.py`'s local `add_audit()` into a shared `backend/app/services/audit.py` used by all new execution services, since the codebase currently has two inconsistent audit-write conventions (inline `V2AuditEvent` writes vs. the local helper) — this plan is a natural point to standardize before adding several more mutation services.
- **Evidence storage uses the backend file adapter, privately served**: per `docs/v2/00_ARCHITECTURE_PACKAGE_INDEX.md` §6, Supabase Storage is not yet the selected production evidence store, and local/internal testing may use the backend file adapter but "must not be treated as production durability." This plan implements `file_objects` + an authenticated download route (not `StaticFiles` public mount) as the Release 1 internal-testing-appropriate choice, explicitly flagged as not production-final.
- **PM/Supervisor reassignment becomes two-step (request + approval) rather than today's immediate change**: implements BR-007's "Admin/PM approves replacement" hierarchy via `project_role_changes` records with a `pending`/`approved`/`rejected` status, replacing `assign_membership()`'s current immediate-effect behavior.

---

## Open Questions

### Resolved During Planning

- Whether to reuse `V2ProjectTask` for execution state: resolved — no, new `tasks` table (see Key Technical Decisions).
- Whether evidence needs production-grade private storage now: resolved — no, backend file adapter with authenticated access is sufficient for Release 1, explicitly flagged as an internal-testing choice per architecture doc §6.

### Deferred to Implementation

- Exact Postgres RLS policy shape for the new tables (deny-by-default per architecture package §3 item 5) — depends on how Supabase RLS is currently structured for `V2Project`/`V2ProjectTask`, which needs to be inspected directly during implementation, not assumed here. Minimal deny-by-default RLS should land in the **same migration/unit that creates each table** (not as a later follow-up), since until RLS exists, FastAPI-mediated access is the *only* enforced boundary — any direct Supabase access path (service-role key reuse, a future debugging script) would otherwise bypass every role/membership check this plan designs into the service layer.
- Whether `update_sla_hours`-driven `no_update` detection is computed on read (a query) or via a scheduled job — both are valid; the choice affects whether a background worker is introduced in this plan or deferred. Default to compute-on-read unless implementation finds a strong reason otherwise (keeps this plan free of new infrastructure).

---

## Implementation Units

- U1. **Baseline lock and task/dependency/gate instantiation**

**Goal:** Replace the status-flag-only baseline lock with a real immutable snapshot (`project_baselines`, `baseline_tasks`) captured at activation, and instantiate the new execution-layer `tasks`/`task_dependencies` tables from it.

**Requirements:** R1, R8

**Dependencies:** None

**Files:**
- Create: `supabase/migrations/<timestamp>_v2_project_baseline_and_tasks.sql` (new tables: `project_baselines`, `baseline_tasks`, `tasks`, `task_dependencies`, plus enums for `task_class`/`task_kind`/`lifecycle_status`)
- Create: `backend/app/execution_models.py` (SQLAlchemy models mirroring the new tables, `V2_SCHEMA`-scoped)
- Create: `backend/app/services/project_baseline.py` (`ProjectBaselineService.lock_and_instantiate(project_id)`)
- Modify: `backend/app/routes/projects_v2.py` (both `POST /{id}/status`'s activation branch **and** `POST /{id}/activate` — the codebase has two independent `draft -> active` code paths today; `/activate`'s own docstring currently states `/status` is left unmodified so its draft-to-active path is unaffected, meaning both must call the same baseline-lock service or `/activate` will silently produce an active project with no baseline/tasks)
- Test: `backend/tests/test_project_baseline_lock_v2.py`

**Approach:**
- Snapshot only `V2ProjectTask`/gate/dependency rows with `decision_state = 'included'` at the moment of activation.
- `baseline_tasks` immutability is enforced at the database level (a trigger or REVOKE'd UPDATE/DELETE privilege) — this is the actual enforcement mechanism, not merely a convention. `content_hash` is stored alongside it purely as a cheap cross-environment integrity check (e.g. comparing staging vs. production baselines without a full row diff), mirroring the `template_versions.content_hash` pattern; it is not what prevents tampering.
- `tasks` rows are created in `lifecycle_status = 'planned'`; `task_dependencies` are copied 1:1 from the baseline's dependency graph with `created_from_baseline = true`.
- Reject activation (same as today) if there is no active PM/Supervisor; additionally reject if there are zero `included` tasks (nothing to execute).

**Test scenarios:**
- Happy path: activating a project with N included tasks and M dependencies creates one `project_baselines` row, N `baseline_tasks` rows, N `tasks` rows in `planned` state, and M `task_dependencies` rows.
- Happy path: excluded (`decision_state != 'included'`) tasks are not copied into the baseline.
- Edge case: activating a project with zero included tasks is rejected with a clear error.
- Edge case: re-activating an already-active project does not create a second baseline (idempotency / already-locked check).
- Error path: activation without an active PM or Supervisor is rejected (existing behavior — verify it still holds with the new baseline step inserted into the same transaction).
- Integration: a DB-level attempt to update or delete a `baseline_tasks` row after lock fails (permission/trigger-level immutability, not just service-layer refusal).

**Verification:**
- Activating a project through the existing `POST /{id}/status` endpoint produces a locked baseline and a populated `tasks` table in one atomic transaction; no code path can activate without both succeeding together.

---

- U2. **Task lifecycle state machine**

**Goal:** Implement the controlled status transitions from BR-009 as an enforced state machine on the new `tasks` table, gated by role and by predecessor dependency state (R8).

**Requirements:** R2, R8

**Dependencies:** U1

**Files:**
- Modify: `backend/app/execution_models.py` (lifecycle_status enum/constraint reflecting only the transitions in BR-009)
- Create: `backend/app/services/task_lifecycle.py` (`TaskLifecycleService.transition(task_id, target_status, actor, reason=None)`)
- Create: `backend/app/routes/execution_tasks_v2.py` (`POST /api/v2/projects/{id}/tasks/{task_id}/status`)
- Create: `backend/app/schemas/execution_tasks.py`
- Test: `backend/tests/test_task_lifecycle_transitions_v2.py`

**Approach:**
- Encode the exact transition table from BR-009 (`planned->ready->in_progress->submitted->verified->completed`, `submitted->rejected->in_progress`, `verified->approval_pending->completed`, `submitted->approval_pending->completed` for gates, `approval_pending->rejected->in_progress`, `planned->completed` for milestones, any non-terminal `->cancelled` with reason) as an explicit allow-list, not inferred from surrounding code.
- Before allowing `ready`/`in_progress`, check the project has an active Supervisor (BR-004) and that all blocking `task_dependencies` predecessors are satisfied (BR-011) — the predecessor "satisfied" condition varies by predecessor `task_kind`/`task_class` per BR-008 (verified/completed standard work, PM-approved Class A or gate, completed milestone).
- Milestones transition automatically (`planned -> completed`) when their predecessors become satisfied — implemented as a check triggered inside the same service call that satisfies a predecessor, not a separate polling job.
- Every transition writes a `V2AuditEvent` (via the consolidated `audit.py` helper from Key Technical Decisions) with before/after status.

**Test scenarios:**
- Happy path: a `work` task moves `planned -> ready -> in_progress -> submitted` when called by an authorized actor in sequence.
- Happy path: a `milestone` task auto-completes once its last blocking predecessor is satisfied.
- Edge case: attempting a transition not in the allow-list (e.g., `planned -> submitted`) is rejected.
- Edge case: `in_progress` is rejected when the project has no active Supervisor.
- Edge case: `in_progress` is rejected while a blocking predecessor is unsatisfied; succeeds once the predecessor reaches its required state.
- Error path: `cancelled` transition without a reason is rejected.
- Integration: satisfying a predecessor task (via U4's verification/approval) triggers a dependent milestone's auto-completion in the same request.

**Verification:**
- Every transition in BR-009's table is reachable via the service under the correct role/dependency conditions, and every transition outside that table is rejected.

---

- U3. **Progress updates and evidence submission**

**Goal:** Let the Supervisor or a delegated support employee submit a progress update with optional evidence files, replacing the legacy module's public-URL upload pattern with private, authorized access.

**Requirements:** R3

**Dependencies:** U1, U2

**Files:**
- Create: `supabase/migrations/<timestamp>_v2_task_progress_and_evidence.sql` (`task_progress_updates`, `file_objects`, `task_evidence`)
- Modify: `backend/app/execution_models.py`
- Create: `backend/app/services/task_progress.py`
- Modify: `backend/app/routes/execution_tasks_v2.py` (`POST /{task_id}/progress`, `GET /{task_id}/evidence/{file_id}` — authenticated download)
- Test: `backend/tests/test_task_progress_evidence_v2.py`

**Approach:**
- `file_objects` stores `storage_key`, `mime_type`, `size_bytes`, `checksum`; actual bytes live in a **new, separate Docker volume/directory (e.g. `evidence_uploads`) that is never passed to `StaticFiles`** — `backend/app/main.py` currently mounts the entire `uploads/` tree publicly (`app.mount("/uploads", StaticFiles(directory="uploads"))`), so evidence must not live anywhere under that directory or it is trivially reachable at a public `/uploads/...` URL regardless of the intended access route. Access is only through the authenticated download route, which checks the requester has an active membership on the task's project.
- The download route serves files with `Content-Disposition: attachment` and `X-Content-Type-Options: nosniff`, and validates that the declared `mime_type` matches the allowlist at upload time — evidence must never be served in a browser-renderable way that could enable stored-content attacks against a viewing PM/Admin/Supervisor.
- Reuse the legacy module's MIME allowlist and size-cap validation as a pattern (not its storage/URL approach).
- A progress update is append-only and does not itself change `lifecycle_status` — it's evidence for a later `submitted` transition (U2) to reference.

**Test scenarios:**
- Happy path: an authorized Supervisor/support employee submits a progress update with an evidence file; `task_progress_updates` and `file_objects`/`task_evidence` rows are created.
- Happy path: submitting without evidence (text-only progress note) succeeds.
- Edge case: disallowed MIME type or oversized file is rejected with a clear error.
- Error path: an actor with no active project membership cannot submit progress or download evidence for that project's tasks.
- Integration: the authenticated download route returns the file for an authorized requester and 403/404s for an unauthorized one.

**Verification:**
- Evidence files are never reachable via a public/static URL; every access path requires the authenticated download route.

---

- U4. **Supervisor verification and PM approval decisions**

**Goal:** Implement the verification/approval branch of BR-008: Supervisor verifies `work`, PM approves `class_a` work and every `approval_gate`, with rejection reopening under the correct accountable role.

**Requirements:** R2, R4

**Dependencies:** U1, U2, U3

**Files:**
- Create: `supabase/migrations/<timestamp>_v2_task_verification_approval.sql` (`task_verifications`, `task_approval_decisions`)
- Modify: `backend/app/execution_models.py`
- Create: `backend/app/services/task_verification.py`, `backend/app/services/task_approval.py`
- Modify: `backend/app/routes/execution_tasks_v2.py` (`POST /{task_id}/verify`, `POST /{task_id}/approve`)
- Test: `backend/tests/test_task_verification_approval_v2.py`

**Approach:**
- `task_verifications` applies only to `work` tasks (BR-008: approval gates skip Supervisor verification). Verifier must resolve to the project's active Supervisor (or an audited PM/Admin fallback per the role-permission matrix).
- `task_approval_decisions` is required for every `class_a` work task and every `approval_gate`; `verification_id` is populated for Class A work, null for gates.
- On `verified`/`approved`, call U2's `TaskLifecycleService.transition` to advance status (`verified -> completed` for standard, `verified -> approval_pending` for Class A pending PM, `approval_pending -> completed` on PM approval).
- On `rejected`, transition to `in_progress` in both cases — work rejection (`submitted -> rejected -> in_progress`) and Class A/gate rejection (`approval_pending -> rejected -> in_progress`), per BR-009's transition table exactly; the difference between the two is *which role* the reopened task is accountable to next (Supervisor for work, PM for gate), not a different target status. A correction reason is required in both cases (BR-008).
- The fallback verifier (PM/Admin acting in place of an unavailable Supervisor) may not also be the approver of record for the same task's same decision cycle — if a PM verifies as fallback, a different authorized actor (Admin) must record the subsequent Class A approval, preserving BR-008's two-checkpoint intent instead of collapsing it to one actor.

**Test scenarios:**
- Happy path: Supervisor verifies a `standard` work task; task completes.
- Happy path: Supervisor verifies a `class_a` work task; task enters `approval_pending`; PM then approves; task completes.
- Happy path: PM approves an `approval_gate` task directly (no verification step).
- Edge case: a non-Supervisor cannot verify; a non-PM cannot approve Class A/gate decisions.
- Edge case: verifying a task with no pending progress submission is rejected.
- Error path: rejection without a reason is rejected; rejection with a reason correctly reopens the task under the right accountable role (Supervisor for work, PM for gate).
- Integration: an approval/verification decision on a predecessor correctly unblocks a dependent successor task's `in_progress` transition (ties to U2's dependency check).

**Verification:**
- No task can reach `completed` without the decision(s) BR-008 requires for its `task_kind`/`task_class` combination.

---

- U5. **Blocker and delay capture**

**Goal:** Let blockers and delays be recorded against a task as conditions independent of (and combinable with) lifecycle status, per BR-010.

**Requirements:** R5

**Dependencies:** U1, U2

**Files:**
- Create: `supabase/migrations/<timestamp>_v2_task_blockers_delays.sql` (`task_blockers`, `task_delay_events`)
- Modify: `backend/app/execution_models.py`
- Create: `backend/app/services/task_blocker.py`, `backend/app/services/task_delay.py`
- Modify: `backend/app/routes/execution_tasks_v2.py` (`POST /{task_id}/blockers`, `POST /{task_id}/blockers/{blocker_id}/resolve`, `POST /{task_id}/delays`)
- Test: `backend/tests/test_task_blockers_delays_v2.py`

**Approach:**
- Blocker and delay creation do not themselves change `lifecycle_status` — they are independently queryable conditions, matching BR-010's "blocked/delayed/overdue/no_update are separate conditions, not mutually exclusive lifecycle states."
- `overdue` and `no_update` remain derived (computed from `due_at`/`update_sla_hours` at query time per the Open Questions resolution), not stored — no migration needed for those two.
- Any active project member with support/accountable access to the task can log a blocker; only the accountable Supervisor/PM (or authorized fallback) can resolve one.

**Test scenarios:**
- Happy path: logging a blocker with type/description/owner creates a `task_blockers` row; resolving it sets `resolved_at`/`resolved_by`.
- Happy path: logging a delay with `responsibility_type`/`reason`/`impact_days` creates a `task_delay_events` row.
- Edge case: a task can simultaneously be `blocked` and `delayed` and `in_progress` — verify no mutual-exclusion constraint accidentally prevents this.
- Edge case: `responsible_vendor_id` is required when `responsibility_type = 'vendor'`, otherwise null.
- Error path: an actor without project membership cannot log a blocker/delay for that project's task.

**Verification:**
- Blocker/delay state never gates or is gated by `lifecycle_status` transitions — the two systems are queryable independently.

---

- U6. **Task-level accountability, support assignment, and controlled reassignment**

**Goal:** Formalize derived task accountability (R6), implement `task_support_assignments`, and upgrade PM/Supervisor/support reassignment from today's immediate change into a reason-required, approval-gated, fully audited flow (R7).

**Requirements:** R6, R7

**Dependencies:** U1 (needs `tasks` to exist for support assignment scoping); independent of U2–U5's internals otherwise

**Files:**
- Create: `supabase/migrations/<timestamp>_v2_support_assignments_role_changes.sql` (`task_support_assignments`, `support_assignment_changes`, `project_role_changes`, **plus a partial unique index on `V2ProjectMembership` enforcing at most one active (`ends_at IS NULL`) `project_manager` and one active `site_supervisor` per project** — currently this invariant is enforced only in application code (`assign_membership()`), which every accountability-resolution query in U2–U4 silently depends on)
- Modify: `backend/app/execution_models.py`
- Create: `backend/app/services/task_support_assignment.py`, `backend/app/services/project_role_change.py`
- Modify: `backend/app/routes/projects_v2.py` (`assign_membership()` — replace immediate-effect change with a `project_role_changes` request/approval flow for accountable roles; support-assignment endpoints live in `execution_tasks_v2.py`)
- Modify: `frontend/src/features/projects/components/ProjectTeamReplaceModal.jsx` (surface pending-approval state instead of assuming immediate effect)
- Test: `backend/tests/test_task_support_assignment_v2.py`, `backend/tests/test_project_role_change_approval_v2.py`

**Approach:**
- Accountability resolution (which Supervisor/PM is accountable for a given task at a given time) is a read-side query against `V2ProjectMembership`'s dated rows — no new storage, per Key Technical Decisions.
- `task_support_assignments`: Supervisor controls support for `work` tasks, PM controls follow-up support for `approval_gate` tasks (BR §5); assignee must be an active `internal_employee` project member; unique active assignment per task/employee.
- `project_role_changes`: Admin requests/approves PM replacement; the active PM requests/approves Supervisor replacement (Admin as audited fallback) — per BR-007's hierarchy. A `pending` record does not affect who is currently accountable; approval atomically ends the previous membership and starts the replacement (same transactional pattern `assign_membership()` already uses today, just gated behind the new approval step).
- `EmployeeProfile.availability == 'unavailable'` triggers a "Reassignment Required" surfaced state (queryable, not a new column) rather than blocking new assignment silently — mirrors BR-007's "automatic skill-based or silent replacement is prohibited."

**Test scenarios:**
- Integration: the DB-level partial unique index rejects an attempt to create a second concurrent active PM (or Supervisor) membership on the same project, independent of and in addition to `assign_membership()`'s own application-level check.
- Happy path: Supervisor assigns a support employee to a `work` task; PM assigns follow-up support to an `approval_gate` task.
- Happy path: Admin requests a PM replacement; a second authorized actor approves it; the previous PM membership ends and the new one starts atomically, both audited.
- Edge case: an `internal_employee` cannot be assigned as task support twice for overlapping periods.
- Edge case: a non-`internal_employee` project member cannot be assigned as support.
- Error path: requesting a role change without a reason is rejected.
- Error path: an actor outside the BR-007 hierarchy (e.g., Supervisor requesting their own replacement) is rejected.
- Integration: marking an employee `unavailable` who currently holds the active Supervisor membership surfaces a "Reassignment Required" condition queryable from the project, without silently reassigning anyone.

**Verification:**
- No PM/Supervisor membership changes without going through the two-step (request + approval) flow; support assignment changes never alter the accountable PM/Supervisor membership (BR §6 invariant).

---

## System-Wide Impact

- **Interaction graph:** U2's lifecycle transitions call into U4's verification/approval outcomes and U1's dependency graph; U6's role-change approval affects who U2/U4 will authorize for future transitions on the same project. These units share one project's data but are otherwise not entangled with templates/gates/dependency-generation (planning layer) beyond reading already-`included` rows at baseline lock.
- **Error propagation:** All new services follow the existing pattern — service raises a domain error, route translates to the appropriate HTTP status (403/404/409), `IntegrityError` caught and translated, no unhandled 500s expected for validation failures.
- **State lifecycle risks:** Baseline lock (U1) and role-change approval (U6) both require the "end previous / start replacement" atomic pattern already used by `assign_membership()` — reuse that transactional shape rather than reinventing it, to avoid a partial-write risk (e.g., new PM active while old PM's membership row not yet closed).
- **API surface parity:** The frontend gains new screens/actions for status changes, evidence upload, verification/approval, blocker/delay logging, and support assignment — none of these have any existing UI today, so this is net-new surface, not a parity change.
- **Integration coverage:** The cross-unit scenario most likely to hide a bug is U2 ↔ U4 ↔ U1's dependency check — a predecessor's verification/approval must correctly unblock a successor's `in_progress` transition in the same request chain; this needs an explicit integration test beyond each unit's own unit tests (called out in U2 and U4's test scenarios).
- **Unchanged invariants:** `V2ProjectTask`'s `draft`-only constraint remains untouched; template authoring, applicability review, and dependency/gate generation continue to operate exactly as today — this plan only reads their `included` output at the moment of baseline lock (U1).

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Introducing a parallel `tasks` table alongside `V2ProjectTask` could confuse future contributors about which table is authoritative for what | Document the split explicitly in code comments on both models and in this plan's Key Technical Decisions; `V2ProjectTask` = planning, `tasks` = execution, never conflated |
| RLS policy shape for six-plus new tables is unresolved at planning time | Deferred to Implementation (Open Questions) — inspect existing `V2Project`/`V2ProjectTask` RLS during U1 before writing new policies, so the pattern is consistent |
| Two-step role-change approval (U6) changes existing `assign_membership()` behavior that the frontend and any current users may depend on being immediate | `ProjectTeamReplaceModal.jsx` is explicitly included in U6's file list to update the UX; flag this as a behavior change in the PR description when implemented |
| Six new migrations touching a live-ish schema increase the chance of a sequencing mistake (e.g., FK to a table created in a later migration) | Units are ordered by dependency (U1 first); each migration's FK targets are checked against tables created in the same or earlier units before merging |
| Evidence storage choice (backend file adapter) is explicitly non-production-durable per architecture doc §6 | Documented as a known, intentional limitation in Key Technical Decisions — not silently presented as production-ready |
| This plan ships mutations (status change, verification, approval, blocker/delay, reassignment) without the `outbox_events` infrastructure BR-015 requires for every one of them | Explicit, acknowledged gap (see Scope Boundaries → Deferred to Follow-Up Work) — Control Layer (Phase 2) owns outbox/WhatsApp; Release 1's Phase 1 completion is not fully BR-015-compliant until Phase 2 lands |
| No malware/content-integrity scanning on uploaded evidence beyond MIME allowlist and size cap | Accepted for Release 1 given no scanning infrastructure exists yet; flagged as a follow-up hardening item, not solved by this plan |
| No retention/deletion policy defined for evidence files (site photos may contain identifiable people or sensitive site conditions) | Deferred — evidence lifecycle/deletion policy should be defined before production rollout, tracked as follow-up work rather than solved here |

---

## Documentation / Operational Notes

- Update `docs/RELEASE_1_IMPLEMENTATION_AUDIT.md`'s "Task Management" and "Ownership and Support Assignments" sections once this plan lands, since both currently describe the exact gap this plan closes.
- Consider running `/ce-compound` after implementation to seed `docs/solutions/` with the baseline-lock and audit-consolidation patterns established here — no prior institutional learnings exist yet for this codebase.

---

## Sources & References

- **Origin document:** [docs/brainstorms/release-1-completion-requirements.md](docs/brainstorms/release-1-completion-requirements.md)
- Architecture baseline: `docs/v2/02_V2_DATA_MODEL_SPECIFICATION.md` (§4–§10), `docs/v2/01_BUSINESS_RULES_DECISION_RECORD.md` (BR-002, BR-004 through BR-011)
- Role authority reference: `docs/v2/03_RELEASE_1_ROLE_PERMISSION_MATRIX.md`
- Existing gap analysis: `docs/RELEASE_1_IMPLEMENTATION_AUDIT.md` ("Task Management," "Ownership and Support Assignments," "Controlled Task Reassignment" sections)
- Pattern reference (not reused): `backend/app/routes/execution_v2.py`, `backend/app/services/history.py`
