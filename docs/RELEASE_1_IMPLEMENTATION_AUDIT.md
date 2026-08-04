# Release 1 Implementation Audit
**Scope:** V2 system (`siteops_v2` schema — `projects_v2`, `templates_v2`, `dependencies_v2` routes) audited against the MVP Scope Doc's Phase 1/2/3 Development Priority list, cross-checked with the approved PRD and the `docs/v2` business-rules/data-model/permission-matrix package.

**Method:** Verified by reading route handlers, service/repository code, SQLAlchemy models, Supabase migrations, and test files — not by running the app. Frontend claims verified against actual component/API-call wiring, not file names alone. Per your instruction, the legacy `execution_v2` module (old schema) is treated as the system being replaced, not as Release 1 evidence, except where explicitly noted for context.

> **Update (2026-08-03):** The headline fact below and the "Task Management" / "Ownership and Support Assignments" sections predate the Task Execution Engine plan (`docs/plans/2026-08-02-001-feat-task-execution-engine-plan.md`), which has since shipped on `feat/task-execution-engine` — both backend (U1–U6) and, as of this update, the frontend (U2–U6: `TaskExecutionBoard`, `TaskProgressForm`, `TaskDecisionModal`, `TaskBlockerDelayPanel`, `TaskSupportAssignmentPanel`, `PendingRoleChangesPanel`). The `draft`-only constraint described below now applies only to the planning-time `project_tasks` table; a separate execution-layer `tasks` table (instantiated at activation from an immutable baseline snapshot) carries the real lifecycle. See the updated Phase Analysis entries below and the "F. Post-Implementation QA Notes" section for a screenshot-based verification pass against the live app.

**Headline fact that shapes this entire audit (historical — see update note above):** the V2 `project_tasks` table has a database-level constraint `lifecycle_status = 'draft'` — i.e., a V2 project task is *structurally incapable* of reaching any execution state (`ready`, `in_progress`, `submitted`, `verified`, `completed`) in the current schema. Everything built so far on the V2 side is the **pre-activation planning layer** (template authoring → project creation → task/gate generation → applicability review → dependency generation). The **execution layer** (progress updates, evidence, verification, approval decisions, blockers/delays, vendor task assignment, WhatsApp) has no backend tables, no routes, and no tests. This one fact governs the status of most phases below **except Task Management and Ownership/Support Assignments, both superseded by the update note above.**

---

## Phase Analysis

### 1. Phase Name: Login and Roles (Phase 1, item 1)

### 2. Implementation Status
Mostly Complete

### 3. Existing Implementation Evidence
Backend:
- `app/auth.py` — `current_user`, `require_roles`, `can_create_role` dependencies.
- `app/services/supabase_auth.py` — token verification against Supabase Auth, admin user create/update/delete, password recovery, OTP/magic-link verification.
- `app/routes/auth.py`, `app/routes/access_requests.py`, `app/routes/users.py` — login-adjacent flows, self-service access request + email verification + admin approval, user CRUD.
- `UserRole` enum in `app/models.py`: `super_admin, admin, project_manager, supervisor, internal_employee` — five roles, matching BR-003's five portal roles (naming difference: code uses `supervisor`, spec document says `site_supervisor` — label only, not a functional gap).
- `app/services/access_control.py` — `can_create_role` hierarchy (Super Admin creates Admin/PM/Supervisor/Employee; Admin creates PM/Supervisor/Employee), matching the permission matrix's "create/deactivate" rows.

Frontend:
- `features/auth/LoginPage.jsx`, `AccessRequestPages.jsx` — login, forgot/reset password, request-access, verify-access screens, all wired to Supabase JS client + backend endpoints.
- `features/users/UsersPage.jsx`, `AccessRequestQueue.jsx`, `UserModals.jsx` — user administration UI.

Testing:
- No dedicated backend test file targets `auth.py` or `access_requests.py` directly in the `tests/` folder (test files are concentrated on template/project domain logic, not auth). Auth correctness is unverified by automated tests in this codebase, though the code itself is straightforward and was traced end-to-end during this audit.

### 4. Gap Analysis
Already working: login, logout, password reset/forgot flow, self-service access request with email verification, admin approval of access requests, role-gated route access, user activation/deactivation.
Partially working: the `role_module_permissions` table exists but is not read anywhere — module visibility is hardcoded per role in `dashboard.py`, and the Role Permissions screen explicitly rejects edits ("Release 1 permissions are fixed"). This doesn't block login/roles working, but it means "Permission management" (an MVP Scope module 1 bullet) is not truly dynamic.
Missing: no automated test coverage for the auth flow itself.

### 5. Architecture Alignment
Matches PRD workflow. Five-role model lines up with BR-003 and the permission matrix's governance order.

### 6. Recommendation
Keep existing implementation.

### 7. Risk Level
Low — this is the most exercised, most stable part of the codebase (every other feature depends on it working).

---

### 1. Phase Name: Project Creation (Phase 1, item 2)

### 2. Implementation Status
Mostly Complete

### 3. Existing Implementation Evidence
Backend:
- `app/routes/projects_v2.py` — `POST /api/v2/projects` (create draft shell + PM/Supervisor membership), `PATCH /{id}`, `POST /{id}/status` (draft→active→on_hold/completed→archived transitions with role checks), `DELETE /{id}` (draft-only, confirmation-gated), `GET /{id}`, `GET /{id}/activity`.
- `app/project_models.py` — `V2Project`, `V2ProjectMembership` (employee_id, project_role, starts_at/ends_at, assigned_by, assignment_reason).
- Activation validates: exactly one active PM, one active Supervisor, a template version, and a target handover date present before allowing `draft → active` — matches BR-002's activation precondition.
- `app/schemas/projects.py` — request/response contracts.

Frontend:
- `features/projects/ProjectsPage.jsx`, `components/ProjectFormModal.jsx`, `ProjectDetailModal.jsx`, `ProjectTeamReplaceModal.jsx`.
- `api/projectsApi.js` — full CRUD + status + team endpoints wired.

Testing:
- `tests/test_project_create_v2.py` exists and targets this specifically.

### 4. Gap Analysis
Already working: creating a draft project, assigning PM/Supervisor, activating (with precondition checks), changing status through the allowed state machine, soft-deleting an unreferenced draft, viewing a project's audit activity feed.
Partially working: "Activation locks the baseline" (BR-002) is only a status-flag change today — there is no `project_baselines`/`baseline_tasks` snapshot table (per `02_V2_DATA_MODEL_SPECIFICATION.md` §4) capturing an immutable copy of the approved tasks at activation time. Nothing currently prevents the underlying template-derived task list from being informally out of sync with what was "locked," because there is no lock artifact — only a project `status` field.
Missing: no true baseline immutability enforcement (no DB trigger/permission rejecting post-activation task edits).

### 5. Architecture Alignment
Partially matches PRD workflow. The visible behavior (draft → review → activate) matches; the "immutable baseline" business rule underneath it is not physically enforced yet.

### 6. Recommendation
Keep existing implementation for the demo — extend later. The gap (no baseline snapshot) is real but not visible in a walkthrough demo unless someone specifically tries to edit a task after activation.

### 7. Risk Level
Low for Tuesday's demo. Medium for Release 1 sign-off against the written business rules, since BR-002's "baseline never overwrites history" guarantee isn't physically enforced yet.

---

### 1. Phase Name: Templates (Phase 1, item 3)

### 2. Implementation Status
Complete (for the planning/authoring workflow described in Release 1 scope)

### 3. Existing Implementation Evidence
Backend:
- `app/template_models.py` — `V2Template`, `V2TemplateVersion` (draft/published/archived, one `is_current_published` enforced via partial unique index), `V2TemplateTask`, `V2TemplateTaskDependency`, `V2TemplateExternalGate`, `V2TemplateExternalGateTask`.
- `app/routes/templates_v2.py` (413 lines) — template/version CRUD, task/dependency/gate authoring, draft validation, publish/archive lifecycle.
- Service layer: `template_commands.py`, `template_task_commands.py`, `template_dependency_commands.py`, `template_gate_commands.py`, `template_draft_validator.py`, `template_publish_service.py`, `template_queries.py`, `template_access.py`, `template_mutation_access.py`, `template_audit.py`, `template_fixture_validator.py` — a genuinely layered implementation, not a stub.
- `app/fixtures/v2_templates/workved_45_day_*.json` — a seedable reference template (explicitly flagged by `docs/v2` as "recovered generic legacy seed, not an approved baseline" — a content/business gap, not a code gap).

Frontend:
- `features/templates/TemplatesPage.jsx` + ~15 supporting components (`TemplateAuthoringModal`, `TemplateTaskEditorModal`, `TemplateDependencyEditorModal`, `TemplateGateEditorModal`, `TemplateValidationPublishPanel`, `TemplateArchiveVersionModal`, etc.) — a full authoring UI, not placeholder screens.

Testing:
- 15 of the 24 backend test files target this domain directly (`test_template_commands_v2`, `test_template_publish_v2`, `test_template_draft_validation_v2`, `test_template_dependencies_v2`, `test_template_gates_v2`, `test_v2_template_schema`, `test_template_security_audit_v2`, etc.) — this is the best-tested area of the entire codebase.
- Frontend: `TemplateAuthoring.test.jsx`, `TemplateDependencies.test.jsx`, `TemplateGates.test.jsx`, `TemplatesPage.test.jsx`, `TemplateValidationPublish.test.jsx`, and others — 10 of 17 frontend test files target this domain.

### 4. Gap Analysis
Already working: creating a template version, authoring tasks/dependencies/gates, running draft validation, publishing a version (which archives the previous one), viewing published versions for project creation.
Partially working: none identified — this module is genuinely solid.
Missing: the *content* of the 45-day template is not the business-approved final version (a content/sign-off gap owned by Product/Operations per `01_BUSINESS_RULES_DECISION_RECORD.md` §4, not an engineering gap).

### 5. Architecture Alignment
Matches PRD workflow (BR-001) precisely, including version locking and "only one active version" semantics.

### 6. Recommendation
Keep existing implementation. This is your strongest asset — lead the demo with it.

### 7. Risk Level
Low, technically. The one real risk is non-technical: if the demo uses the recovered/generic 45-day content, be ready to say explicitly that the *content* is placeholder and the *system* is what's being demonstrated.

---

### 1. Phase Name: Task Management (Phase 1, item 4)

### 2. Implementation Status
Mostly Complete (updated 2026-08-03 — was "Partially Implemented" / "Missing entirely" for the execution half; see note below)

### 3. Existing Implementation Evidence
Backend (planning layer, unchanged from original audit):
- `app/routes/projects_v2.py`: `POST /{id}/generate-tasks`, `GET/POST /{id}/template-review/tasks` and `/template-review/summary`, `POST /{id}/tasks/{task_id}/applicability-decisions`, `POST /{id}/tasks` (manual task creation).
- `app/services/project_task_applicability.py`, `project_manual_task.py`, `project_template_review.py`.
- `app/project_models.py` — `V2ProjectTask` remains planning-only, still `lifecycle_status = 'draft'`-only by design (see Key Technical Decisions in the plan below) — this table was never meant to carry execution state.

Backend (execution layer, new — `docs/plans/2026-08-02-001-feat-task-execution-engine-plan.md`, U1–U6):
- `app/execution_models.py` — `ProjectBaseline`/`BaselineTask` (immutable snapshot locked at activation, DB-trigger-enforced), `Task`/`TaskDependency` (the real execution-layer graph, `lifecycle_status` free to move through `planned → ready → in_progress → submitted → verified/approval_pending → completed`, plus `rejected`/`cancelled`), `TaskProgressUpdate`/`FileObject`/`TaskEvidence` (evidence, privately stored — never under the public `/uploads` static mount), `TaskVerification`, `TaskApprovalDecision`, `TaskBlocker`, `TaskDelayEvent`, `TaskSupportAssignment`/`SupportAssignmentChange`.
- `app/services/project_baseline.py`, `task_lifecycle.py`, `task_progress.py`, `task_verification.py`, `task_approval.py`, `task_blocker.py`, `task_delay.py`, `task_support_assignment.py` — one service per concern, following the codebase's established `_require_access`/audit-event pattern.
- `app/routes/execution_tasks_v2.py` — status transition, progress+evidence submit, authenticated evidence download, verify, approve, blocker create/resolve, delay log, support assign/end, plus `GET /{project_id}/tasks` (list) and `GET /{project_id}/tasks/{task_id}` (detail) — the read endpoints the frontend board needed but the original plan didn't specify; added during frontend implementation.

Frontend (new, 2026-08-03):
- `features/execution/components/TaskExecutionBoard.jsx` — replaces the old read-only task-baseline table in `ExecutionPage.jsx`; per-task status pills, blocker/support badges, an expandable detail panel, and client-mirrored (not authoritative) status-transition/cancel controls.
- `TaskProgressForm.jsx`, `TaskDecisionModal.jsx`, `TaskBlockerDelayPanel.jsx`, `TaskSupportAssignmentPanel.jsx` — mounted inside the board's task detail.
- `api/taskExecutionApi.js` — client for every `execution_tasks_v2.py` route.

Testing:
- Backend: `test_project_baseline_lock_v2.py`, `test_task_lifecycle_transitions_v2.py`, `test_task_progress_evidence_v2.py`, `test_task_verification_approval_v2.py`, `test_task_blockers_delays_v2.py`, `test_task_support_assignment_v2.py`, `test_execution_tasks_read_v2.py` (306/306 backend tests passing).
- Frontend: one `*.test.jsx` per new component (149/149 non-pre-existing frontend tests passing).

### 4. Gap Analysis
Already working: generating/reviewing a project's planning-time task list (unchanged); baseline lock at activation; full task-status lifecycle with role-gated transitions; progress notes with private evidence upload; Supervisor verification and PM Class-A/gate approval with required-reason rejection; blocker and delay capture (independent of lifecycle status, per BR-010); support-employee assignment; all of it reachable from the portal, not just the API.
Partially working / known limitations (not regressions — disclosed at implementation time):
- The delay form's "Vendor ID" field is a plain UUID input with no picker, since Phase 2 (Vendor Management, MVP module 6) hasn't shipped — a real user has no way to know a vendor's UUID today. Client-side UUID-format validation was added so it fails fast rather than with a confusing backend 422, but the field is not practically usable until Phase 2 lands.
- `docs/RELEASE_1_IMPLEMENTATION_AUDIT.md` itself (this file) and the "Execution" nav item's subtitle in the frontend config were not part of the plan's file list and were found stale during a post-implementation screenshot review (see Section F).
Missing: none of the MVP Scope module 3 bullets ("Track execution progress / Update task status / Upload evidence / Capture blockers and delays") remain unimplemented.

### 5. Architecture Alignment
Now matches PRD workflow for both halves. Task-level "ownership" is implemented as **derived** accountability (the project's active Supervisor for `work` tasks, PM for `approval_gate` tasks), not a stored per-task assignee field — a deliberate Key Technical Decision in the plan, not a gap, though it reads differently from the PRD's literal "assign tasks" wording.

**Duplicate-system note (unchanged):** the legacy `execution_v2` module still exists on the old schema and should continue to be treated as the system being replaced, not as Release 1 evidence.

### 6. Recommendation
Keep existing implementation. Track Phase 2 (Vendor Management) as the item that unblocks the one remaining known-limitation (vendor delay attribution).

### 7. Risk Level
Low — the largest gap this audit originally flagged is closed and tested.

---

### 1. Phase Name: Ownership and Support Assignments (Phase 1, item 5)

### 2. Implementation Status
Mostly Complete (updated 2026-08-03 — was "Partially Implemented"; see note below)

### 3. Existing Implementation Evidence
Backend (project-level, unchanged from original audit):
- `app/routes/projects_v2.py`: `assign_membership()` creates a `V2ProjectMembership` and ends the prior active membership's `ends_at` in the same transaction. `POST /{id}/memberships/{membership_id}/end` ends a membership with a required reason. Every change writes a `V2AuditEvent`.

Backend (task-level support + reassignment approval, new — plan U6):
- `app/execution_models.py` — `TaskSupportAssignment`/`SupportAssignmentChange` (a delegated Internal Employee's support role on a specific execution-layer task; never alters task accountability, which stays derived from `V2ProjectMembership`).
- `app/project_models.py` — `ProjectRoleChange` — the two-step request/approval flow BR-007 calls for: on an **active** project, PM/Supervisor replacement now creates a `pending` request (`POST /{id}/role-changes`) that a separate authorized actor must approve (`POST /{id}/role-changes/{change_id}/approve`) before the membership actually changes; a partial unique DB index enforces at most one active PM and one active Supervisor per project as a backstop beyond the service-layer check. Draft-phase projects keep the original immediate-effect path (BR-007 governs live execution, not initial setup).
- `app/services/task_support_assignment.py`, `project_role_change.py`.
- `GET /{id}/role-changes/reassignment-required` — surfaces active PM/Supervisor memberships whose holder is marked `unavailable`, per BR-007's "no silent auto-replacement."

Frontend:
- `TaskSupportAssignmentPanel.jsx` (assign/end task-level support, in the execution board's task detail).
- `PendingRoleChangesPanel.jsx` (new) — wires `roleChanges`/`approveRoleChange`/`rejectRoleChange`/`reassignmentRequired`, previously exported by `projectsApi.js` but called from no component, into an approve/reject UI plus a "Reassignment Required" alert, rendered on `ProjectDetailModal`'s Team tab.
- `ProjectDetailModal.jsx` — the "Change" control that opens `ProjectTeamReplaceModal` was gated to `project.status === "draft"` only; fixed to also render on `active` projects, since the two-step flow specifically governs live execution and had no UI entry point there before.

Testing:
- `test_project_role_change_approval_v2.py`, `test_task_support_assignment_v2.py` (backend); `TaskSupportAssignmentPanel.test.jsx`, `PendingRoleChangesPanel.test.jsx` (frontend), plus role-scoped approve/reject coverage added during code review (a PM can act on a Supervisor-replacement request but not a PM-replacement request, per BR-007's hierarchy).

### 4. Gap Analysis
Already working: project-level PM/Supervisor assignment/replacement (unchanged); task-level support-employee assignment; two-step approval-gated reassignment for PM/Supervisor on active projects; "Reassignment Required" surfacing for an unavailable accountable role.
Missing: none of the items this section previously flagged as missing.

### 5. Architecture Alignment
Now matches PRD workflow, including PG-04's "trigger mandatory, visible reassignment when an owner is absent" and BR-007's approval-before-active requirement.

### 6. Recommendation
Keep existing implementation.

### 7. Risk Level
Low.

---

### 1. Phase Name: Basic Employee Availability Status (Phase 1, item 6)

### 2. Implementation Status
Partially Implemented

### 3. Existing Implementation Evidence
Backend:
- `app/models.py` — `EmployeeProfile.availability` (Text, default `"available"`, `CheckConstraint` restricting to `available|restricted|unavailable`) — matches BR-006's three-state model.
- `app/routes/projects_v2.py` — both `assign_membership()` and `create_project()`'s `resolve_accountable_user()` check `employee.availability == "unavailable"` and block new assignment with a 409 error.

Frontend:
- Availability is surfaced in reference-data payloads consumed by `ProjectFormModal.jsx`/`ProjectTeamReplaceModal.jsx` (used to filter/label selectable employees), per `routes/projects_v2.py` reference-data serialization.

Testing:
- No dedicated test file found for availability-gated assignment specifically.

### 4. Gap Analysis
Already working: a single current-availability field per employee, enforced as a hard gate when assigning PM/Supervisor to a project.
Partially working: this is a static field, not an event log — `employee_availability_events` (spec §3, with `starts_at`/`ends_at`/`reason`/`recorded_by`) does not exist, so there's no history of *when* someone became unavailable, why, or for how long, and no UI found for an Admin/Supervisor to actually change this status (no route for updating `EmployeeProfile.availability` was located in this pass — it may only be settable via direct user-management update; **unclear**, needs a quick grep/verification before the demo if you intend to show this live).
Missing: availability event history; a clearly-identified UI action to toggle availability.

### 5. Architecture Alignment
Partially matches PRD workflow — the enforcement point (block assignment when unavailable) matches intent, but the "event" concept behind BR-006 is reduced to a plain status field.

### 6. Recommendation
Keep existing implementation as-is for the demo. Confirm (quickly, not as new work) that there is a working way to flip an employee's availability before relying on this in a live walkthrough.

### 7. Risk Level
Medium — mostly because it's unverified whether the toggle is reachable from the UI, not because the underlying logic is broken.

---

### 1. Phase Name: Controlled Task Reassignment (Phase 1, item 7)

### 2. Implementation Status
Partially Implemented

### 3. Existing Implementation Evidence
Backend: same evidence as "Ownership and Support Assignments" above — `assign_membership()`'s ends-previous/creates-new pattern with mandatory `assignment_reason` and audit logging.
Frontend: `ProjectTeamReplaceModal.jsx`.
Testing: none specifically named for reassignment.

### 4. Gap Analysis
Already working: controlled reassignment at the **project PM/Supervisor** level — reason required, previous owner's membership closed, new owner's membership opened, both facts audited.
Partially working: no separate "approval before the new owner becomes active" step (BR-007/MVP Scope module 4 both describe reassignment as something that should be approved, not just recorded) — today's flow is: actor changes it, reason is required, change is immediate and audited. This is defensible as "controlled" but not "approval-gated."
Missing: task-level reassignment (doesn't exist, since task execution doesn't exist); a distinct approval step for reassignment; the dedicated `project_role_changes`/`support_assignment_changes` tables from the spec (the current implementation achieves a similar audit outcome through `V2ProjectMembership.ends_at` + `V2AuditEvent`, which is a reasonable simplification, not a broken implementation).

### 5. Architecture Alignment
Partially matches PRD workflow. The audit/history guarantee is met; the "approval before active" nuance is not, at least not as a separate explicit step.

### 6. Recommendation
Keep existing implementation. The gap (no separate approval step) is a business-rule nuance that is unlikely to be noticed in a demo narrative of "we reassigned the Supervisor and it's fully audited."

### 7. Risk Level
Low for the demo; Medium against the literal written business rule.

---

### 1. Phase Name: Assignment and Reassignment Audit Capture (Phase 1, item 8)

### 2. Implementation Status
Mostly Complete

### 3. Existing Implementation Evidence
Backend:
- `app/project_models.py` — `V2AuditEvent` (actor, action, entity_type/id, project_id, correlation_id, before/after JSON, reason, occurred_at) — append-only, matches BR-017's audit-record shape closely.
- `add_audit()` helper called consistently across membership assign/end, project status change, draft deletion in `routes/projects_v2.py`; equivalent audit calls exist in the template and gate/dependency services.
- `GET /{project_id}/activity` — serves the last 100 audit events for a project, joined with actor name.

Frontend: activity feed is consumed somewhere in the project detail UI (via `projectsApi.activity`) — **not individually confirmed which component renders it in this pass; likely `ProjectDetailModal.jsx` given its role, but treat as unconfirmed until visually checked.**

Testing: audit assertions are likely embedded within the various `test_project_*_v2.py` and `test_template_*_v2.py` files (these test business operations that call `add_audit`), rather than as a standalone audit test suite. Not independently confirmed as a dedicated audit-correctness test file.

### 4. Gap Analysis
Already working: every membership/status/template/gate/dependency mutation captured in this pass writes a structured, reason-required, before/after audit event; a project-scoped activity feed endpoint exists.
Partially working: whether the frontend actually renders this feed prominently and legibly is unconfirmed — worth a 2-minute visual check before demoing "full audit trail" as a feature.
Missing: no separate correlation-ID propagation confirmed across a multi-step operation (the field exists on `V2AuditEvent`; whether it's populated meaningfully rather than defaulted was not traced in depth).

### 5. Architecture Alignment
Matches PRD workflow (BR-017) well.

### 6. Recommendation
Keep existing implementation.

### 7. Risk Level
Low.

---

### 1. Phase Name: Approvals (Phase 2, item 9)

### 2. Implementation Status
Partially Implemented

### 3. Existing Implementation Evidence
Backend:
- `app/project_models.py` — `V2ProjectExternalGate`, `V2ProjectExternalGateTask`, `V2ProjectExternalGateApplicabilityDecision`.
- `app/routes/projects_v2.py` — `POST /{id}/generate-gates`, `GET /{id}/external-gates`, `POST /{id}/gates/{gate_id}/applicability-decisions` (applicable/not_applicable, with reason), `POST /{id}/gates` (manual gate creation).
- `app/services/project_gate_generation.py`, `project_gate_applicability.py`, `project_manual_gate.py`.

Frontend: `ProjectExternalGates.jsx`, `GateApplicabilityDecisionModal.jsx`, `ProjectManualGateModal.jsx`.

Testing: `test_project_gate_generation_v2.py`, `test_project_gate_applicability_v2.py`, `test_project_manual_gate_v2.py`.

### 4. Gap Analysis
Already working: generating external/approval-gate items from the template into a project, and deciding whether each is applicable to this specific project (with a reason) — this is real, tested functionality.
Partially working: per `02_V2_DATA_MODEL_SPECIFICATION.md` §7, in the target architecture an "approval gate" is meant to ultimately be a `task_kind = approval_gate` task that a PM formally approves/rejects via `task_approval_decisions`, blocking dependent work. That decision step doesn't exist yet, for the same root reason as Task Management: no task execution layer. What exists today only decides *whether a gate applies to this project*, not *whether the gate has been granted*.
Missing: the actual PM approve/reject decision on a live approval gate; blocking-dependency enforcement tied to gate status during execution.

### 5. Architecture Alignment
Partially matches PRD workflow — good foundation, missing the operational decision step that gives "Approvals" its practical value (PG-05, BR-011).

### 6. Recommendation
Extend existing module if time allows (see Section D); otherwise defer the decision step to a later release and demo only the "applicability review" as planning functionality.

### 7. Risk Level
Medium — demoable as "we've scaffolded and reviewed the approval gates for this project," not demoable as "here's how a landlord approval gets tracked to completion."

---

### 1. Phase Name: Vendors (Phase 2, item 10)

### 2. Implementation Status
Implemented (per `docs/plans/2026-08-02-002-feat-control-layer-vendor-whatsapp-plan.md`, Implementation Units U1-U3)

### 3. Existing Implementation Evidence
Backend:
- `app/vendor_models.py` — new `siteops_v2` tables: `vendors`, `capability_categories`, `vendor_capabilities`, `vendor_contacts`, `project_vendors`, `task_vendor_assignments`, `vendor_acknowledgements`, `vendor_activity_events`, `vendor_activity_evidence`.
- `app/services/vendor_import.py` — one-time, idempotent, dry-run-first import from the legacy `app.models.Vendor` table (BR-019). `Vendor.parent_vendor_id` is authoritative for sub-vendor relationships; `ContractorRelationship` disagreements are flagged for manual review, not migrated. `migration_pending` vendors are excluded pending legacy-side resolution.
- `app/services/project_vendor.py`, `task_vendor_assignment.py` — map an active vendor to a project (sub-vendor requires its parent's active mapping to the same project, BR-012); delegate a mapped, capability-matched vendor to a task without transferring Site Supervisor accountability (BR-013). Neither service imports Phase 1's `task_lifecycle`/`task_verification` — proven structurally via `ast`-based import inspection in `test_task_vendor_assignment_v2.py`.
- `app/services/vendor_acknowledgement.py`, `vendor_activity.py` — PM-submitted, portal-channel acknowledgement (`accepted`/`declined`/`clarification_requested`, append-only); vendor-attributable activity/incident capture (`presence`/`delay`/`rework`/`incident`) with optional evidence, reusing Phase 1's `file_objects` pattern via a dedicated link table (no polymorphic entity references). No endpoint in either service can mutate task lifecycle/verification/approval state — a vendor cannot start/complete/verify/approve/close a task through this mechanism (BR-013).
- `app/routes/project_vendors_v2.py`, `vendors_router` — full read/write surface: `GET /api/v2/vendors` (active vendors + capabilities), `POST/GET /api/v2/projects/{id}/vendors` (mapping), `POST/GET /api/v2/projects/{id}/tasks/{task_id}/vendor-assignment(s)` (delegation), `.../acknowledge`, `.../activity`, and an evidence download route mirroring Phase 1's task-evidence pattern.

Frontend: `ProjectVendorPanel.jsx` (map a vendor, list current mappings — new "Vendors" tab on `ProjectDetailModal.jsx`), `TaskVendorDelegationForm.jsx` (delegate a mapped vendor to a task, rendered inside `TaskExecutionBoard`'s task detail), `VendorAcknowledgementForm.jsx`, `VendorActivityForm.jsx` (with evidence upload/download) — all PM/Admin-gated for write actions, visible read-only to other project members. `vendorAssignmentApi.js` is the flat API client. The legacy `features/vendors/VendorsPage.jsx` remains the standalone legacy-schema vendor master-data UI and is unchanged.

Testing: `test_vendor_import_v2.py`, `test_project_vendor_mapping_v2.py`, `test_task_vendor_assignment_v2.py`, `test_vendor_acknowledgement_v2.py`, `test_vendor_activity_v2.py` — 38 tests total, covering happy paths, sub-vendor/parent-mapping edge cases, capability-mismatch rejection, evidence upload/download, and the no-vendor-identity-can-mutate-lifecycle structural proof.

### 4. Gap Analysis
Already working: the full vendor lifecycle on the new schema — import from legacy, project mapping, task delegation, acknowledgement, and activity/incident capture with evidence — end to end from backend service through a PM-facing portal UI.
Partially working: nothing — this plan's scope (R1-R5) is complete.
Missing: nothing in scope. Deliberately out of scope per the plan: vendor self-service login/UI (vendor interaction stays WhatsApp-and-PM-managed, per PRD §11), automated vendor scoring/ranking (explicitly excluded from Release 1 by BR-014), an Admin-facing dashboard aggregating vendor data (Phase 3's job).

### 5. Architecture Alignment
Now matches the data-model spec's intent: legacy vendor tables are not carried forward as parallel models for new V2 work — `siteops_v2.vendors` is the new authoritative table for project/task-facing vendor operations, populated via the one-time import. The legacy module continues to exist as its own standalone master-data UI (unchanged), which is the intended cutover boundary, not a lingering duplicate-system conflict.

### 6. Recommendation
Complete for this release. Follow-up (not blocking): confirm the one-time import's operational cutover point with Product/Ops (freezing legacy vendor edits during the actual import window), and consider an Admin-facing outbox/delivery monitoring view as a Phase 3 candidate.

### 7. Risk Level
Low — vendor mapping, delegation, acknowledgement, and activity capture are demoable end-to-end through the portal UI, with Supervisor accountability provably unaffected.

---

### 1. Phase Name: WhatsApp Notifications and Reassignment Alerts (Phase 2, item 11)

### 2. Implementation Status
Infrastructure Implemented; Live Sending Externally Gated (per `docs/plans/2026-08-02-002-feat-control-layer-vendor-whatsapp-plan.md`, Implementation Units U4-U6)

### 3. Existing Implementation Evidence
Backend:
- `app/execution_models.py` (`OutboxEvent`) + `app/services/outbox.py` — every BR-015-mandated mutation point (status transition, verification, approval, blocker, delay, support assignment, role change, evidence submission, vendor assignment) writes a durable `outbox_events` row in the same DB transaction as the domain mutation, with a deterministic idempotency key. Instrumented across every Phase 1 mutation service plus this plan's `task_vendor_assignment.py`.
- `app/services/message_dispatch.py` — `MessageDispatchService.process_pending()` resolves recipients from the event's aggregate plus current approved assignments (PM/Supervisor/vendor contact; `super_admin` is structurally never a queryable recipient role) and dispatches through a `WhatsAppProviderAdapter` interface. `SandboxProviderAdapter` simulates provider responses for testing — swapping in a real Meta/WABA client is a configuration change, not a schema change.
- `app/routes/whatsapp_webhook_v2.py`, `app/services/inbound_message.py` — `POST /api/v2/whatsapp/inbound` verifies `X-Hub-Signature-256` (HMAC-SHA256, constant-time compare) before any parsing or matching. A verified sender phone matches against active employees (`user_profiles.phone_e164`) or vendor contacts (`vendor_contacts.phone_e164`/`whatsapp_e164`); zero or multiple matches is always logged `unmatched`, never auto-resolved. A matched, authorized command calls the identical Phase 1/U3 service a portal action would (`TaskLifecycleService.transition`, `VendorAcknowledgementService.record_acknowledgement`) — no parallel WhatsApp-only business logic exists.

Frontend: none for U4-U6 by design (Scope Boundaries: no natural end-user screen — outcomes surface indirectly once a recipient acts on a message via U2/U3's UI). A dedicated Admin monitoring dashboard for failed sends/retry queues is a reasonable Phase 3 follow-up, not required here.

Testing: `test_outbox_emission_v2.py` (parametrized across every mandatory event type), `test_message_delivery_dispatch_v2.py`, `test_inbound_message_matching_v2.py` — covering idempotency/duplicate-delivery safety, signature-verification rejection, ambiguous/offboarded-identity handling, and the "same service call a portal action uses" structural proof.

### 4. Gap Analysis
Already working: the full outbox → delivery-tracking → inbound-matching *infrastructure*, exercisable end-to-end against the sandbox provider adapter, with idempotency and signature verification enforced as hard gates.
Partially working: nothing — this plan's infrastructure scope (R6-R9) is complete.
Missing: **live WhatsApp sending.** This was never an engineering deliverable for this plan (see Scope Boundaries) — it requires Meta/WABA business approval, approved message-template wording, and a recipient/consent matrix that Product/Ops must supply. The `WhatsAppProviderAdapter` interface is ready to receive a real client once that approval lands.

### 5. Architecture Alignment
Matches the data-model spec's outbox pattern (§1, §9) precisely: domain mutation and outbox insert share a transaction, delivery is fire-and-forget from the domain's perspective, and the provider is a swappable adapter rather than a hardcoded assumption. The PRD's "WhatsApp-first platform" positioning (PG-06) is now backed by real infrastructure — what remains is exclusively the external business-approval dependency, not an engineering gap.

### 6. Recommendation
Coordinate with Product/Ops now on Meta/WABA business approval and template wording approval — this has its own external lead time independent of engineering readiness. Wiring a real provider client behind `WhatsAppProviderAdapter` once approval lands is a configuration-level follow-up, not a re-architecture.

### 7. Risk Level
Low as an engineering risk (infrastructure is built, tested, and demoable via the sandbox adapter); the remaining risk is entirely external-approval timeline, outside engineering's control.

---

### 1. Phase Name: Dashboard (Phase 3, item 12)

### 2. Implementation Status
Not Implemented

### 3. Existing Implementation Evidence
Backend: `app/routes/dashboard.py` exists but serves only `/api/me` and `/api/dashboard` (a role-scoped user list plus a hardcoded module-visibility list) — this is navigation/identity plumbing, not a project-progress or execution dashboard. No route was found returning aggregated project status, delay counts, blocker counts, or approval-gate-at-risk data for the V2 system. The closest analog is the per-project `GET /{id}/activity` audit feed (a list of raw events, not a dashboard).
Frontend: `features/dashboard/Dashboard.jsx` and `DashboardTab.jsx` render the tab shell and route to feature pages — they are not themselves a metrics dashboard.
Testing: none found (nothing to test).

### 4. Gap Analysis
Already working: nothing that matches "dashboard" as described in PG-01/BR-016 (planned/active/completed/delayed/blocked/overdue/unreported work at a glance).
Partially working: the per-project audit activity feed is the nearest existing building block, but it's a raw event log, not a summarized dashboard.
Missing: everything — project progress view, delay/blocker aggregation, pending-approvals view, reassignment-pending view, vendor-risk view (all PRD §8 bullets).

### 5. Architecture Alignment
Cannot meaningfully compare — there is no implementation to check against the workflow. This is also structurally blocked: a dashboard summarizing delayed/blocked/overdue work requires the execution layer (Task Management gap above) to exist first, since those states don't exist yet.

### 6. Recommendation
Defer for later release, with one narrow exception worth considering for the demo: a lightweight, read-only "project list with status/team/template" view is realistically achievable by Monday, since all the underlying data already exists (`GET /api/v2/projects` list endpoint already returns this). See Section D.

### 7. Risk Level
High if framed as "the management dashboard"; Low if scoped down to "a project list view" for the demo, since the data already exists behind the list endpoint.

---

### 1. Phase Name: Reports (Phase 3, item 13)

### 2. Implementation Status
Not Implemented

### 3. Existing Implementation Evidence
Backend: no `report_snapshots` table (spec §9), no daily/weekly report generation route or service found anywhere in `backend/app`.
Frontend: no report-viewing screen found.
Testing: none.

### 4. Gap Analysis
Already working: nothing.
Missing: everything (BR-016's daily/weekly report generation and versioned snapshot storage).

### 5. Architecture Alignment
Cannot meaningfully compare — no implementation exists. Also structurally blocked on the execution layer, same as Dashboard.

### 6. Recommendation
Defer for later release.

### 7. Risk Level
High if expected Tuesday; recommend explicitly setting the expectation now that this is out of scope for the demo.

---

### 1. Phase Name: Audit History View (Phase 3, item 14)

### 2. Implementation Status
Mostly Complete

### 3. Existing Implementation Evidence
Backend: `GET /api/v2/projects/{id}/activity` (covered above under Phase 1 item 8) — this is functionally the audit history view for a project.
Frontend: consumed via `projectsApi.activity` — rendering location not independently confirmed in this pass (see note under item 8).
Testing: implicit via the various `_v2` test files that assert audit events are written; no dedicated "view" test.

### 4. Gap Analysis
Already working: the underlying audit data and retrieval endpoint.
Partially working: whether it's presented as a clean, demo-ready "history" screen versus a raw list needs a quick visual check.
Missing: no cross-project or Admin-level audit view was found — only per-project.

### 5. Architecture Alignment
Matches PRD workflow at the project level; no broader (cross-project) audit view exists, which BR-016 implies for Admin-level cross-project visibility.

### 6. Recommendation
Keep existing implementation; verify the frontend rendering visually before the demo.

### 7. Risk Level
Low.

---

# A. Executive Summary

1. **Estimated Release 1 completion percentage: roughly 40-45%.** This is deliberately not a single precise number because completion is uneven by design: the pre-activation planning layer (auth, templates, project setup, task/gate generation and review, dependencies) is close to 90% complete and well tested. The post-activation execution layer (task status/evidence/verification/approval, blockers/delays, vendor task assignment, WhatsApp, dashboards, reports) is close to 0% complete in the V2 system. Averaged across all 14 MVP Scope Phase 1-3 items, roughly 40-45% reflects "fully or mostly working" weighted against "not started."
2. **Strongest completed areas:** the Template authoring/versioning/publish system and Project creation/template-review/dependency/gate-generation workflow. These are genuinely production-quality — layered services, real validation, real test coverage (15 of 24 backend test files, 10 of 17 frontend test files target this area alone).
3. **Biggest blockers:** (a) the V2 task model cannot leave `draft` status — there is no execution engine at all, which cascades into blocking Task Management, real Approvals, Dashboard, and Reports; (b) Vendor management works but is completely disconnected from V2 projects; (c) WhatsApp — the PRD's headline differentiator — has zero implementation and cannot be started without external (Meta/WABA) approvals outside engineering's control.
4. **Main reasons preventing full PRD completion by Monday:** the missing pieces are not small bugs to fix — they are entire unbuilt subsystems (task execution state machine, evidence/verification/approval chain, vendor-task bridge, notification infrastructure, reporting/dashboard aggregation) that the architecture docs themselves describe as requiring dedicated migrations, services, and content sign-off (45-day template content, role-matrix approval) that were still pending at the time these docs were written.

---

# B. Tuesday Demo Readiness

**"If the demo is on Tuesday, what can confidently be shown?"**

## Demo Ready:
- Login, role-based access, user administration, self-service access request flow.
- Template authoring end-to-end: create a version, add tasks/dependencies/gates, validate, publish (watch the previous version archive automatically).
- Create a project from a published template, assign PM and Supervisor, see activation preconditions enforced (try activating without a Supervisor — it correctly rejects).
- Generate the project's task list and external gates from the template; walk through the applicability review (include/exclude a task or gate with a reason).
- Generate task dependencies from the template.
- Reassign the project's PM or Supervisor and show the resulting audit trail on the project activity feed.
- Vendor master-data management (create vendor, create sub-vendor under a parent, see status history) — as a standalone module, not connected to the project above.

## Demo Risk:
- Employee availability gating — the block-on-unavailable logic works, but it's unverified whether there's a working UI path to actually mark someone unavailable; test this specific click-path beforehand, don't discover it live.
- The project activity/audit feed's frontend presentation — the data and endpoint are solid, but how it renders on screen wasn't visually confirmed in this pass; check it looks presentable before relying on it.
- Anything implying task-level ownership ("assign this task to this employee") — the underlying data model has no field for this; don't improvise it live.

## Avoid Showing:
- Any task status change, evidence upload, verification, or approval decision on a V2 project task — none of this exists; do not attempt to demo it and do not let the demo narrative imply it's coming "later this week."
- WhatsApp notifications of any kind.
- A management/progress dashboard with delay/blocker/overdue counts.
- Daily or weekly report generation.
- Vendor assigned to a specific project task (the connection doesn't exist).
- The legacy `execution_v2` module's working proof-upload/approve-reject flow **as if it were the V2/Release-1 system** — it is a different, older schema; showing it may create a false impression of V2 completeness. If you do want to show it (since it's arguably your most polished *end-to-end* demo today), be explicit that it's the outgoing system being replaced, not Release 1.

---

# C. Minimum Work Required Before Demo

**Priority 1 — Must complete before Tuesday:**
- Verify (don't build — just click through) the full "Demo Ready" list above actually works on current `main`/staging, including error states (e.g., activating without a Supervisor). Impact: prevents live demo failure. Complexity: Small.
- Confirm the project activity/audit feed renders legibly in the UI. Impact: this is your best "auditability" selling point (PG-10) — make sure it looks like one. Complexity: Small.
- Confirm whether/how an employee's availability status can actually be changed via the UI; if there's no path, either add a minimal one or plan to demo availability-gating using seed data instead of a live toggle. Impact: avoids an on-the-spot gap during the demo. Complexity: Small–Medium depending on what's found.
- Prepare a clear, one-slide "what's built vs. what's next" narrative using this audit, so the Tuesday conversation is proactive rather than reactive when Task Management/Dashboard/WhatsApp inevitably come up. Impact: highest-leverage single action available before Tuesday — manages expectations instead of hiding gaps. Complexity: Small.

**Priority 2 — Useful if time permits:**
- A minimal, read-only project list view showing status/team/template per project (data already exists behind `GET /api/v2/projects`) — gives a "dashboard-shaped" artifact without building real aggregation logic. Impact: partially answers "where's the dashboard" without overcommitting. Complexity: Small.
- A minimal manual "mark task as done" toggle on `V2ProjectTask` (bypassing the full lifecycle state machine) purely to make the demo narrative feel end-to-end. **Caution:** this would violate the `lifecycle_status = 'draft'` database constraint as currently written and would require either a migration or a workaround — treat this as a judgment call given how thin your margin is; it is not free. Impact: Medium (narrative completeness) if done cleanly; High risk of introducing a rushed, untested change to a core constraint if done carelessly. Complexity: Medium–Large.

**Priority 3 — Do not touch before demo:**
- WhatsApp integration of any kind.
- Any change to the template content/seed data (this is a Product/Operations sign-off item, not an engineering task, and touching it late risks destabilizing the best-tested part of the system).
- Any schema migration to relax `lifecycle_status = 'draft'` unless Priority 2's manual toggle is deliberately chosen and scoped tightly.
- Dashboard/reporting aggregation logic.
- Vendor-to-V2-project integration.

---

# D. Recommended Implementation Sequence Until Monday

This is the shortest path to a credible Tuesday demo, not the PRD's full sequence.

**Step 1:**
Objective: Confirm current state actually runs, end to end, on the environment you'll demo from.
Existing support: All of "Demo Ready" list above is implemented in code.
Missing: Nothing code-wise; this is a verification pass, not a build task.
Expected outcome: A known-good, rehearsed click-path from login → template → project → task/gate review → reassignment → audit feed, with no surprises.

**Step 2:**
Objective: Close the two small, genuinely uncertain gaps identified in Priority 1 (availability toggle reachability; audit feed rendering quality).
Existing support: Backend logic for both already works.
Missing: Possibly a small UI affordance for availability, and/or minor styling on the activity feed if it looks raw.
Expected outcome: No live gaps discovered mid-demo on features you're already claiming are "done."

**Step 3 (optional, only if Steps 1-2 finish with time to spare):**
Objective: Give the demo a "dashboard-shaped" moment without building real aggregation.
Existing support: `GET /api/v2/projects` already returns status/team/template per project.
Missing: A simple list/table screen (or reuse of `ProjectsPage.jsx`'s existing list rendering) framed explicitly as "project visibility," not "the management dashboard."
Expected outcome: Answers the inevitable "where's the dashboard" question with something real, honestly scoped.

**Step 4:**
Objective: Prepare the honest management narrative — this is as important as any code work this week.
Existing support: This audit document.
Missing: A short internal summary (5-10 lines) translating this audit into: "Planning/setup layer: done and tested. Execution layer (day-to-day task tracking, approvals, WhatsApp, dashboards, reports): scoped, architecturally specified, not yet built — next sprint." 
Expected outcome: Tuesday's conversation is about a credible plan, not a surprise gap.

**Do not attempt this week:** building any part of the task execution engine, vendor-V2 integration, or WhatsApp — each is a multi-day subsystem per the architecture docs' own delivery-sequence guidance (`03_RELEASE_1_ROLE_PERMISSION_MATRIX.md` §5 lists nine ordered backend-implementation steps, of which the planning layer covers roughly the first five; verification/approval/WhatsApp are steps 8-9).

---

# E. High Risk Areas

- **Architecture conflict — two disconnected project/task systems in one codebase.** The legacy `execution_v2` module (old schema) is functionally further along for day-to-day execution than V2, which is architecturally further along for planning. Anyone browsing the codebase without this context could easily misjudge overall progress in either direction. Recommendation: keep this distinction explicit in any technical conversation this week.
- ~~**Database risk — `lifecycle_status = 'draft'` constraint.**~~ **Resolved (2026-08-03).** `V2ProjectTask.lifecycle_status` is still `draft`-only by design (it's the planning table), but a separate execution-layer `tasks` table now carries the real lifecycle, instantiated from an immutable baseline snapshot at activation. See the updated "Task Management" section.
- ~~**Broken/incomplete workflow — approval gates without a decision step.**~~ **Resolved (2026-08-03) for Class A work and approval gates.** `TaskVerificationService`/`TaskApprovalService` (backend) and `TaskDecisionModal` (frontend) now implement the Supervisor-verify / PM-approve decision, including required-reason rejection. Still open: this closes Task Management's decision step, not a dedicated "Approvals" (Phase 2, item 9) dashboard/summary view — that phase's own gap analysis is otherwise unchanged.
- **Missing integration — Vendor ↔ V2 Project.** Vendor management is solid in isolation; do not let the demo imply a vendor can be assigned to a V2 project task today. Now directly visible in the execution board's delay form (see Section F) — logging a vendor-responsibility delay requires a UUID with no picker to supply one.
- **Missing integration — WhatsApp.** Zero implementation, and it cannot be meaningfully started this week regardless of engineering effort, since it depends on external approvals (Meta/WABA access, message template approval) outside the team's control per the architecture docs.
- **Feature that may consume too much time if attempted — Dashboard/Reports.** Both require the execution layer to exist first — that blocker is now cleared (see "Task Management"), so this is no longer foundation-less; Phase 3 (Visibility) is next in the plan sequence, not blocked.
- **Content risk, not code risk — 45-day template content.** The architecture docs explicitly flag the current template content as a "recovered generic legacy seed," not the approved baseline. If the demo uses this content, be ready to name that distinction proactively rather than have it surface as a question.

---

# F. Post-Implementation QA Notes (2026-08-03)

A screenshot-based review of the live Execution tab (Admin, Project Manager, and Supervisor views, same task expanded in each) against the plan and this audit surfaced three findings — none are regressions in the shipped code, but all are worth acting on:

1. **Stale nav copy.** The "Execution" sidebar item's subtitle still reads *"Read-only task baseline for a..."* in all three screenshots — a Phase 9 description that predates U2–U6 and is no longer accurate now that the tab is a live, writable board (status transitions, evidence, verification/approval, blockers/delays, support assignment). This text lives outside the Task Execution Engine plan's file list (likely a tabs/nav config, not `ExecutionPage.jsx` itself) and was never updated. **Action:** update the nav subtitle; small, low-risk copy fix.
2. **Screenshots likely predate the latest push.** All three show the delay form's Vendor ID hint as *"...enter the vendor's ID for now."* — the pre-code-review wording. The code-review fix pushed in commit `adcdea1` changed this to *"...enter the vendor's V2 record UUID for now."* and added client-side UUID-format validation (rejecting non-UUID input before submit with an inline error). If a fresh reload of the running app still shows the old hint or still lets a non-UUID value reach submission, the frontend build/dev-server needs restarting to pick up `adcdea1`. **Action:** rebuild/restart and re-verify before further QA.
3. **Reconfirmed, already-disclosed limitation.** The Vendor ID field is a required plain-UUID input with no picker, since Phase 2 (Vendor Management) hasn't shipped — a real user logging a vendor-responsibility delay has no way to know a vendor's UUID today. This was already flagged as an accepted interim gap in the U5 commit message and in the "Task Management" section above; the screenshot review confirms it's the first thing a Supervisor would hit trying to use that specific field. Not a bug to fix now — tracked against Phase 2 (Control Layer — Vendor Integration).

No other discrepancies were found: role-gating (Supervisor lacking the Cancel control that Admin/PM have), the status/blocker/delay/support-assignment panel set, and required-field validation all matched the plan and the shipped code exactly.

---

*This audit reflects static code, schema, and test-file analysis performed on this date. Nothing in the codebase was modified, run, or executed as part of this review. Items marked "unconfirmed" or "unclear" should be spot-checked by actually opening the running application before Tuesday, since this audit could not execute the app to observe runtime behavior directly.*

*Section F (2026-08-03) is the exception — it reflects an actual screenshot-based review of the running application's Execution tab, not static analysis.*
