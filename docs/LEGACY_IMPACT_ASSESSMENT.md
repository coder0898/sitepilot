# Legacy Code Impact Assessment
**Purpose:** Read-only assessment before implementing Release 1 Phase 8-13 (Approvals → Reports, per the MVP Scope Phase 2/3 items already gap-mapped in `RELEASE_1_IMPLEMENTATION_AUDIT.md`). Nothing in this document was executed, modified, or refactored — all findings are from static reading of source files, imports, and route registration.

**How this was verified, not assumed:** for every item below, "active" means traced to a route actually registered in `backend/app/main.py`, or a frontend component actually reachable from `frontend/src/main.jsx` → `Dashboard.jsx` → `DashboardTab.jsx`'s `TAB_COMPONENTS` map. "Unused" means grepped for imports/references across the whole codebase and none were found beyond the file's own definition.

---

## A. Legacy Inventory

### Templates domain
- `backend/app/models.py` — `ExecutionTemplate`, `ExecutionTemplateTask` (legacy 3-day template model, plain schema).
- `backend/app/template_models.py` — `V2Template`, `V2TemplateVersion`, `V2TemplateTask`, `V2TemplateTaskDependency`, `V2TemplateExternalGate`, `V2TemplateExternalGateTask` (current, `siteops_v2` schema).
- `backend/app/routes_templates_v2.py` (top-level, 382 lines) — an orphaned duplicate of `backend/app/routes/templates_v2.py` (413 lines). Not imported by `main.py` or anything else.

### Projects domain
- `backend/app/models.py` — `Project`, `ProjectTask`, `TaskTemplate` (an early, simplest-of-all legacy project/task model — predates even `ExecutionProject`).
- `backend/app/models.py` — `ExecutionProject`, `ExecutionDay` (legacy execution-schedule model).
- `backend/app/project_models.py` — `V2Project`, `V2ProjectTask`, `V2ProjectMembership`, `V2AuditEvent` and related (current).
- `backend/app/projects_v2.py` (top-level, 619 lines) — an orphaned, older duplicate of `backend/app/routes/projects_v2.py` (755 lines). Not imported anywhere; missing the gates/dependencies/template-review/manual-task endpoints that exist in the live file, confirming it's a stale snapshot left behind mid-refactor, not a currently-maintained alternative.

### Tasks / execution workflow domain
- `backend/app/models.py` — `ExecutionTask`, `ExecutionTaskStatusHistory`, `ExecutionTaskAssignmentHistory`, `ExecutionTaskDelayReport`, `ExecutionTaskReschedule`, `ExecutionProjectContractor` — the full legacy day-to-day execution engine (status transitions, proof upload, approve/reject, delay, reschedule).
- `backend/app/routes/execution_v2.py` — despite the `_v2` name, this serves the **legacy** models above, not the `siteops_v2` schema. This is currently the only place in the codebase where task execution (status change, evidence, verification, approval) actually works end-to-end.
- No V2 equivalent exists yet (per `RELEASE_1_IMPLEMENTATION_AUDIT.md`, `V2ProjectTask.lifecycle_status` is DB-constrained to `'draft'`).

### Dependencies domain
- No legacy equivalent found anywhere in `models.py`. `backend/app/project_models.py` (`V2ProjectTaskDependency`) and `backend/app/template_models.py` (`V2TemplateTaskDependency`) are the only implementation. This domain has no duplication to manage.

### Users / Roles domain
- Single shared `users` table (`backend/app/models.py::User`) used by both the legacy execution module and the V2 module — this is the one domain that is *not* duplicated. `EmployeeProfile`, `UserAccountEvent`, `AccessRequest`, `AccessRequestEvent` are likewise shared, current, and actively used by both systems.
- `backend/app/models.py::RoleModulePermission` — a table with zero references anywhere outside its own model definition. No route reads or writes it. `backend/app/routes/permissions.py` returns a hardcoded catalog instead and explicitly rejects any write ("Release 1 permissions are fixed").

### Execution workflows (vendor/communication side-modules)
- `backend/app/models.py` — `Vendor`, `VendorCategory`, `ContractorCategory`, `VendorContact`, `ProjectVendor`, `ContractorRelationship`, `VendorStatusHistory`, `VendorParentMigrationCandidate`, `CommunicationLog` — all legacy-schema, all currently active and exercised via `routes/vendors.py` and `routes/communication.py`. `CommunicationLog.execution_project_id` ties communication records to the **legacy** `ExecutionProject`, not any V2 project — so this active module is itself coupled to the system being replaced.

### Frontend
- `frontend/src/features/vendors/VendorsPage.jsx` — a complete vendor-management page, not imported by `DashboardTab.jsx`'s `TAB_COMPONENTS` map or anywhere else in the app. Its API layer (`vendorsApi`) is actively used, but by `CommunicationHubPage.jsx` instead — vendor CRUD now happens inside the Communication Hub tab, which appears to have superseded this standalone page.
- `frontend/src/features/permissions/RolePermissionsPage.jsx` + `components/PermissionMatrix.jsx` — not imported anywhere in the app. Its API layer (`permissionsApi`) is only called from within this same orphaned page — i.e., this is a fully dead vertical slice, frontend and its sole caller both unreachable.
- `frontend/src/features/execution/*` (`ExecutionPage.jsx` and its modal/overview components) — reachable and active (the `execution` tab), but it is the UI for the legacy execution engine, not V2.

---

## B. Active vs Legacy Classification

| Component/module | Current usage | References/dependencies | Risk if removed | Recommendation |
|---|---|---|---|---|
| `routes/execution_v2.py` + legacy `Execution*` models | **Active.** Only working end-to-end task-execution flow in the app today (status, proof upload, approve/reject, delay, reschedule). Reachable via the `execution` tab. | Frontend `ExecutionPage.jsx`, `executionApi.js`; `services/history.py`; `CommunicationLog.execution_project_id`; vendor-deletion blocking check in `routes/vendors.py`. | **High.** Removing this today deletes the only demoable execution workflow in the product, and breaks Communication Hub's project linkage. | **Keep** (do not touch while implementing Phase 8-13; it is the reference behavior for the equivalent V2 capability you're about to build). |
| `project_models.py` / `template_models.py` (`siteops_v2` schema) | **Active and required.** This is the Release 1 target architecture; Phase 8-13 work extends it directly. | `routes/projects_v2.py`, `routes/templates_v2.py`, `routes/dependencies_v2.py`, ~20 service modules, 15+ backend tests, `ProjectsPage.jsx`/`TemplatesPage.jsx` and their sub-components. | N/A — this is what you're building on. | **Keep.** |
| `models.py::Project`, `ProjectTask`, `TaskTemplate` | **Legacy, effectively dead.** No route serves them. Only touched by a blocking-deletion count in `routes/vendors.py` and unused serializer functions (`project_row`, `ensure_project_access`, `task_row`, `visible_projects_query` in `services/serializers.py` — none of these four functions are imported anywhere). | Alembic migration `0001_initial.py` created them; nothing else in live code path. | **Low** to leave alone; **Low-Medium** to remove — the vendor-deletion count query would need updating if the table were dropped, and the DB rule says not to touch schema anyway. | **Freeze.** Do not reference from new Phase 8-13 code (there is no reason to). Do not drop yet — out of scope per your no-schema-change rule, and low cost to leave present. |
| `routes_templates_v2.py` (top-level) | **Fully unused.** Not imported by `main.py` or any other module. | None found. | **None** — confirmed unreferenced. | **Safe to remove after Release 1** (not now, per your "do not remove anything" rule this session — flagging for the post-release cleanup pass). |
| `projects_v2.py` (top-level) | **Fully unused.** Older, smaller duplicate of `routes/projects_v2.py`; missing gates/dependencies/template-review endpoints that exist in the live file. | None found. | **None** — confirmed unreferenced. | **Safe to remove after Release 1.** |
| `models.py::RoleModulePermission` | **Dead table.** Zero code references outside its own class definition. | None. | **None.** | **Deprecate later** — leave the table in place (no schema changes now); revisit when/if dynamic permissions are actually built, since at that point this table's shape should be re-validated against the approved `03_RELEASE_1_ROLE_PERMISSION_MATRIX.md` rather than assumed reusable. |
| `frontend/VendorsPage.jsx` | **Unreachable.** Not in `TAB_COMPONENTS`; superseded by vendor management inside `CommunicationHubPage.jsx`, which uses the same `vendorsApi`. | None (no importer found). | **Low** — its logic is duplicated by the still-active Communication Hub vendor UI, so nothing is lost operationally. | **Deprecate later.** Confirm with whoever owns the frontend that Communication Hub is the intended permanent home for vendor management before deleting, since it's possible this was mid-migration in the other direction. |
| `frontend/RolePermissionsPage.jsx` + `permissionsApi.js` + backend `routes/permissions.py` | **Unreachable end-to-end.** Page not rendered anywhere; its only caller of `permissionsApi` is itself; the backend endpoint it calls returns a fixed, non-editable catalog by design. | None (self-contained, isolated vertical slice). | **Low** — nothing else depends on any part of this slice. | **Freeze** through Phase 8-13 (harmless to leave, zero collision risk with new work); **Deprecate later** as a full slice (frontend page + its API file + backend route) once a decision is made on whether dynamic role/permission management is in scope for a future release. |
| `CommunicationLog.execution_project_id` coupling | **Active but coupled to legacy schema.** Communication Hub (active tab) records project-linked notes against `ExecutionProject`, not `V2Project`. | `routes/communication.py`, `CommunicationHubPage.jsx`. | **Medium**, but only *later* — if/when V2 projects become the primary project record and legacy execution projects are retired, Communication Hub's project-linking will break unless it's re-pointed to V2 projects first. Not a Phase 8-13 blocker (Phase 8-13 doesn't require Communication Hub), but worth flagging now since it's an early sign of what "cutting over" will require touching. | **Keep** for now; note as a required follow-up before any legacy-execution retirement. |
| Alembic (`backend/alembic/`) vs Supabase SQL migrations (`supabase/migrations/`) | **Both active**, in parallel, by design per `00_ARCHITECTURE_PACKAGE_INDEX.md` ("Supabase SQL migrations are the sole V2 migration history; Alembic is legacy-only"). Not a code duplication problem — a two-toolchain operational reality. | Alembic owns the plain/legacy schema (including the still-active `execution_v2` tables); Supabase CLI owns `siteops_v2`. | **N/A** for this assessment (not a removal candidate — it's current operating procedure, both toolchains are needed for different live tables). | **Keep.** Out of scope for cleanup; just be aware Phase 8-13 schema work must go through Supabase migrations only, never Alembic. |
| Dependencies domain (`V2ProjectTaskDependency`, `V2TemplateTaskDependency`) | **Active, no legacy counterpart.** | `routes/dependencies_v2.py`, `services/project_dependency_generation.py`, tests. | N/A. | **Keep.** No legacy-impact risk in this domain at all — safe to build on without any collision analysis needed. |

---

## C. Removal Risk Assessment

Ranked by what would actually break if each item were removed *today* (informational only — nothing is being removed this session):

1. **`routes/execution_v2.py` + legacy `Execution*` models — highest risk if removed.** This is load-bearing: it's the only functioning task-execution demo path, and `CommunicationLog` has a live foreign key into `ExecutionProject`. Removing it would break Communication Hub immediately and remove the only reference implementation of the exact status/verify/approve workflow that Phase 8's "Verification, Class A approval and dependency-controlled approval gates" needs to reproduce in V2. **Do not touch during Phase 8-13** — if anything, keep it open in a second window while building the V2 equivalent, since its transition logic (`services/history.py`, status/assignment/delay/reschedule handling) is the closest working reference for what V2 needs to build.
2. **`CommunicationLog.execution_project_id` legacy coupling — real but deferred risk.** Not a Phase 8-13 blocker, but it means Communication Hub cannot simply be "kept as-is forever" once legacy execution is retired; it will need a schema/FK change at that point (out of scope now, flagged for later).
3. **`models.py::Project` / `ProjectTask` / `TaskTemplate` — near-zero risk if removed, but out of scope this session.** Confirmed dead beyond one blocking-check query and unused serializer helpers. Even the blocking-check in `routes/vendors.py` degrades gracefully (it would just stop counting a number that's presumably always 0 in practice on any V2-only deployment) rather than erroring. No schema change is being proposed here regardless, per your rule.
4. **`RoleModulePermission` table — zero risk if removed, but leave as-is.** No code path touches it.
5. **Two orphaned top-level duplicate route files (`routes_templates_v2.py`, `projects_v2.py`) — zero risk, but flagged as a possible confusion source for whoever implements Phase 8-13.** If a developer greps for `projects_v2` and lands in the wrong (dead) file, they could waste time editing code that is never executed. Worth a team heads-up even though no removal is happening now.
6. **`frontend/VendorsPage.jsx`, `frontend/RolePermissionsPage.jsx` — zero risk, zero collision with Phase 8-13 work.** Neither is on any code path that Approvals/Vendors/WhatsApp/Dashboard/Reports work would touch, except that Phase 9's "Vendors" work will very likely need to decide whether to extend `CommunicationHubPage.jsx`'s vendor UI (the active one) or resurrect `VendorsPage.jsx` — worth a deliberate decision before Phase 9 starts, not an accidental one.

**No finding in this assessment implies any database table is unsafe to keep as-is, and no finding requires a schema change to proceed with Phase 8-13.**

---

## D. Recommended Cleanup Plan After Release 1

Sequenced by safety, not urgency — none of this should happen before Release 1 ships:

1. **Remove the two confirmed-orphaned top-level duplicate files** (`backend/app/routes_templates_v2.py`, `backend/app/projects_v2.py`). Zero references found; safest possible removal candidates in the entire codebase. Do this first as a low-risk warm-up once Release 1 is stable.
2. **Decide the vendor-UI ownership question** (`VendorsPage.jsx` vs. the vendor UI embedded in `CommunicationHubPage.jsx`) and remove whichever loses. This should happen *before or during* Phase 9 (Vendors) design, not strictly "after Release 1" — flagging it here because it's a decision point, not a cleanup task, but the actual file deletion should wait until Phase 9's direction is locked in.
3. **Retire `RolePermissionsPage.jsx` + `permissionsApi.js` + `routes/permissions.py`** as one slice, once a real decision is made on whether dynamic role/permission management is in scope for any future release. If it's never planned, remove all three together (they have no other dependents). If it is planned, this becomes the starting point for that work instead of a removal candidate.
4. **Archive/retire the legacy execution engine** (`routes/execution_v2.py`, `ExecutionProject`/`ExecutionTask`/-history tables) — but only after the V2 system has a working, tested equivalent for status/verification/approval (i.e., after Phase 8-13-equivalent work lands in V2) *and* `CommunicationLog` has been re-pointed to `V2Project`. This is the highest-effort, highest-care item on this list and should not be rushed — per `01_BUSINESS_RULES_DECISION_RECORD.md` BR-019, legacy projects/tasks must be archived, not migrated as active V2 records, and any legacy-project migration requires explicit project-by-project validation.
5. **Retire `models.py::Project`/`ProjectTask`/`TaskTemplate`/`RoleModulePermission` tables** via a proper Supabase-migration-style deprecation (archive, don't hard-delete, per BR-018) — lowest priority since they cost nothing to leave in place, but cleanest to fold into whatever migration eventually formalizes item 4 above, rather than doing it separately.
6. **Re-evaluate `TaskTemplate`/`ExecutionTemplate` vs. `V2Template`** at the same time as item 4 — once legacy execution is retired, the legacy 3-day template model becomes fully redundant with the V2 template system and can be archived alongside it.

---

*This assessment is read-only. No files, schemas, or behavior were changed. All "unused"/"orphaned" findings were verified by tracing imports and route registration, not inferred from file or function names.*
