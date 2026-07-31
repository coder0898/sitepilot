# Technical Understanding Document
**WorkVed / SiteOps MVP — Codebase Analysis**

This document reflects a read-only analysis of the current codebase. Nothing was modified, rewritten, or improved. Where the code's intent could not be confirmed with certainty, it is explicitly marked **unclear**.

---

## A. Architecture Overview

Three-tier web application, containerized with Docker Compose:

- **Frontend**: React (JSX, no TypeScript in practice despite `typescript` being a listed dependency) + Tailwind CSS, built with Vite. Single-page app with no router library — view switching is done with local React state (`useState`) rather than URL-based routing (aside from a `?view=` query param used only for the pre-login auth screens).
- **Backend**: Python FastAPI, using SQLAlchemy 2.0 (typed `Mapped`/`mapped_column` style) as the ORM, served by Uvicorn.
- **Database**: PostgreSQL, provisioned locally via the Supabase CLI (Supabase's local stack provides Postgres + Auth). In production/local Docker, the backend connects to this Postgres instance directly via a SQLAlchemy `DATABASE_URL`.
- **Authentication**: Delegated entirely to Supabase Auth (hosted or local). The backend does not issue or verify its own JWTs from scratch — it forwards bearer tokens to Supabase's `/auth/v1/user` endpoint to validate sessions.
- **Runtime**: `docker-compose.yml` defines two services — `backend` (port 8000) and `frontend` (port 3000) — plus a named volume for uploaded proof files. Supabase itself runs as a separate local stack outside this compose file (started via `npx supabase start`, orchestrated by `tools/start-local.ps1`), not as a service inside `docker-compose.yml`.

**Notable structural characteristic — two parallel "project/task" subsystems coexist in the backend:**

1. A legacy/MVP-style module (models in `app/models.py`: `Project`, `ProjectTask`, `ExecutionTemplate`, `ExecutionProject`, `ExecutionDay`, `ExecutionTask`, status history, delay reports, reschedules) exposed via `app/routes/execution_v2.py` at `/api/v2/execution/*`. Despite the `v2` naming in the route path, this operates on the original/legacy data model (plain "public" schema tables).
2. A newer, more heavily structured module (`app/project_models.py`, `app/template_models.py`) living in a dedicated Postgres schema (`siteops_v2`), exposed via `app/routes/projects_v2.py` and `app/routes/templates_v2.py` at `/api/v2/projects/*` and `/api/v2/templates/*`. This module models template **versioning** (draft/published/archived), project creation from a published template version, per-task/per-gate applicability **review and decision** workflows, and dependency generation.

These two "v2"-labeled systems are **not the same generation of code and do not appear to be connected to each other** (no cross-references were found between `ExecutionProject`/`ExecutionTask` and `V2Project`/`V2ProjectTask` in the modules inspected). This is flagged as a significant point requiring clarification — see Section G.

---

## B. Folder Structure Explanation

```
siteops-mvp/
├── backend/                 FastAPI application
│   ├── app/
│   │   ├── main.py          App factory, router registration, startup seeding
│   │   ├── models.py        Legacy/MVP schema (users, vendors, execution_*, legacy projects)
│   │   ├── project_models.py   V2 project schema (siteops_v2 Postgres schema)
│   │   ├── template_models.py  V2 template schema (siteops_v2 Postgres schema)
│   │   ├── auth.py          Auth dependency functions (current_user, require_roles)
│   │   ├── config.py        Pydantic Settings (env-driven configuration)
│   │   ├── database.py      SQLAlchemy engine/session setup
│   │   ├── seed.py          Startup seed logic (bootstrap Super Admin, default template)
│   │   ├── routes/          FastAPI routers, one file per feature area
│   │   ├── routes_templates_v2.py  A second, unused/dead copy of the templates_v2 router (not imported anywhere — see Section F)
│   │   ├── services/        Business logic layer (one service class/module per capability)
│   │   ├── repositories/    Data-access layer for the V2 template system specifically
│   │   ├── schemas/         Pydantic request/response models for V2 endpoints
│   │   ├── fixtures/        JSON fixtures describing the "45-day" reference template
│   │   └── scripts/         One-off operational scripts (import template, link Supabase users, reset test env)
│   ├── alembic/              Alembic migrations for the legacy/MVP schema (marked "deprecated" in README)
│   ├── tests/                Pytest suite — heavily concentrated on the V2 template/project system
│   └── Dockerfile            Runs `alembic upgrade head` then starts Uvicorn
├── frontend/
│   └── src/
│       ├── api/              One file per backend resource; thin fetch wrappers
│       ├── components/       Shared/reusable UI (layout shell, generic form/table/modal primitives)
│       ├── features/         Feature-based folders (auth, dashboard, projects, templates, execution, communication, users, vendors, permissions, vendorCategoryMapping)
│       ├── config/tabs.js    Central tab registry + role/permission-based visibility logic
│       ├── lib/supabase.js   Supabase JS client (session/auth handling)
│       └── main.jsx          App root: manual view-state routing, auth bootstrapping
├── supabase/
│   ├── migrations/           SQL migrations that own the `siteops_v2` schema (applied via Supabase CLI, not Alembic)
│   └── config.toml, seed.sql
├── docs/                     Project documentation, including a template reference .docx
├── tools/                    PowerShell scripts (start/stop/status local stack) and Python release-check/packaging scripts
└── docker-compose.yml
```

---

## C. Module-by-Module Understanding

Grouped by backend route file, with the frontend feature area it corresponds to.

- **auth** (`routes/auth.py`, frontend `features/auth/`) — Login, logout, password reset/recovery, and account activation, all proxied to/coordinated with Supabase Auth. The backend does not store or check passwords itself (`User.password_hash` is present in the model but the code comment states "Passwords and sessions are owned by Supabase Auth").
- **access_requests** (`routes/access_requests.py`, frontend `AccessRequestPages.jsx`) — A self-service "request access" flow: a prospective user submits a request, verifies their email (magic link via Supabase), and the request then awaits admin/super-admin review. This is a distinct pipeline from `users.py`'s direct user creation.
- **users** (`routes/users.py`, frontend `UsersPage.jsx`) — User CRUD, activation/deactivation, password reset by an admin, and role assignment, gated by the `can_create_role` hierarchy rule in `auth.py`.
- **dashboard** (`routes/dashboard.py`) — Serves `/api/me` (current identity) and `/api/dashboard` (role-scoped user list + which tabs/modules the current role should see). Module visibility here is a **hardcoded list per role group** in Python, not read from the `role_module_permissions` table that exists in the schema (see Section F).
- **permissions** (`routes/permissions.py`, frontend `RolePermissionsPage.jsx`) — Returns a fixed, non-editable "access catalog" describing what each role can do (in prose/label form, from `services/access_control.py`). Both the "save" and "reset" endpoints explicitly return an error stating permissions are fixed for this release. The UI (`PermissionMatrix.jsx`) exists but there is no working mutation behind it.
- **vendors** (`routes/vendors.py`, frontend `VendorsPage.jsx`) — Vendor/contractor CRUD, including a "main vendor" vs. "sub-vendor" hierarchy, status history, and a migration-pending state for vendors lacking a resolved parent relationship.
- **vendor_category_mapping_v2** (`routes/vendor_category_mapping_v2.py`) — Maps free-text task categories to structured vendor categories, with an audit trail table.
- **communication** (`routes/communication.py`, frontend `CommunicationHubPage.jsx`) — A logged communication history (calls/notes) tied to vendors, vendor contacts, and optionally a project.
- **execution_v2** (`routes/execution_v2.py`, frontend `ExecutionPage.jsx`) — The day-to-day task engine on the **legacy** data model: execution projects, day-by-day generated tasks, contractor/sub-contractor assignment, status transitions, proof-of-work upload (`multipart/form-data` to a local `/uploads` volume), supervisor submission, PM review (approve/reject), delay reporting, and rescheduling — each with a history table. This is the closest match to the business-described "Daily Operations" and "Review & Approval" workflows.
- **projects_v2 / templates_v2 / dependencies_v2** (frontend `ProjectsPage.jsx`, `TemplatesPage.jsx`) — The newer template-versioning and project-scaffolding system. Templates go through draft → published → archived states with content hashing; projects are created against a specific published template version; individual template tasks/gates are then reviewed per-project (included/excluded, with a reason) before dependencies and "external gates" (third-party approvals, e.g. landlord/authority sign-offs) are generated. This module is **membership-based** for access (`V2ProjectMembership`), separate from the simpler "assigned PM/Supervisor on the project row" model used by legacy execution.

---

## D. Database Understanding

Two schemas coexist in the same Postgres database:

**Default/`public` schema** (owned by Alembic, `backend/alembic/versions/0001`–`0021`):
- `users` — central identity table, shared by both subsystems; links to Supabase Auth via `supabase_user_id`; carries `role` (enum: `super_admin`, `admin`, `project_manager`, `supervisor`, `internal_employee` — **five** roles, not six; see Section F on "vendor").
- `employee_profiles` — extended profile info (employee code, designation, availability) for internal staff, one-to-one with `users`.
- `access_requests` / `access_request_events` — the self-service onboarding pipeline and its audit trail.
- `role_module_permissions` — exists in the model but, per Section C, is not read by the current permissions logic.
- `vendors`, `vendor_categories`, `vendor_contacts`, `contractor_categories`, `contractor_relationships`, `vendor_status_history`, `vendor_parent_migration_candidates` — the vendor/contractor domain, including a self-referencing main/sub-vendor hierarchy and a migration-state workflow for reconciling legacy vendor records.
- `communication_logs` — vendor-related communication history, optionally linked to either a legacy `projects` row or an `execution_projects` row.
- `projects`, `task_templates`, `project_tasks` — an early/legacy project+task model that appears to predate even the `execution_*` tables (simpler status enum: pending/in_progress/submitted/completed/rejected/delayed/blocked). Its relationship to `execution_projects` is **unclear** — both appear to model "a project with day-based tasks" independently.
- `execution_templates`, `execution_template_tasks`, `execution_projects`, `execution_days`, `execution_project_contractors`, `execution_tasks`, plus `execution_task_status_history`, `execution_task_assignment_history`, `execution_task_delay_reports`, `execution_task_reschedules` — the active day-to-day execution/task-tracking domain described in Section C.
- `task_vendor_category_mappings` / `..._audit` — category-to-vendor-category lookup and its audit log.

**`siteops_v2` schema** (owned by Supabase SQL migrations under `supabase/migrations/`, applied via the Supabase CLI, **not** Alembic):
- `v2_templates` → `v2_template_versions` (draft/published/archived, one "current published" version enforced by a partial unique index) → `v2_template_tasks`, `v2_template_task_dependencies`, `v2_template_external_gates`, `v2_template_external_gate_tasks`.
- `projects` → `project_tasks`, `project_external_gates`, `project_external_gate_tasks`, `project_external_gate_applicability_decisions`, `project_task_dependencies`, `project_memberships`, `audit_events`.
- Foreign keys back to the shared `users` table cross schemas (e.g., `project_memberships.assigned_by → users.id`), confirming `users` is the one identity table both subsystems rely on.

**Key relationships (legacy execution domain, the one matching the business "daily operations" description):**
`ExecutionProject` (1) → (many) `ExecutionDay` → (many) `ExecutionTask`; each `ExecutionTask` optionally references an `ExecutionTemplateTask` (its origin), an `assigned_supervisor` and optionally `assigned_contractor`/`assigned_subcontractor` (both `Vendor` rows), and accumulates status/assignment/delay/reschedule history in separate append-only tables.

**Key relationships (V2 domain):**
`V2Template` (1) → (many) `V2TemplateVersion` → (many) `V2TemplateTask`/`V2TemplateTaskDependency`/`V2TemplateExternalGate`. A `V2Project` references exactly one `V2TemplateVersion`; `V2ProjectTask`, `V2ProjectExternalGate`, and `V2ProjectTaskDependency` are generated *from* that template version into the project, each retaining a link back to its template origin plus a project-specific review/decision state (`included`/`excluded`, `pending_review`, etc.).

**Authorization at the database layer:** no `CREATE POLICY` or Row-Level-Security statements were found in the Supabase migrations. Access control is enforced entirely in the FastAPI application layer (role checks, membership checks) — the backend appears to connect with a role that has full table access, not through Supabase's RLS-protected PostgREST API.

**Migration tooling split is a functional risk, not just a style note:** a fresh environment must run *both* `alembic upgrade head` (automatic, via the backend Docker container) *and* `npx supabase migration up` (manual/separate, via `tools/start-local.ps1`) for both schemas to exist. Someone standing up the stack with `docker compose up` alone, without first running the Supabase CLI step, would get a working legacy schema but a missing/incomplete `siteops_v2` schema. **Unclear** whether this is intentional (Supabase stack assumed already running) or an operational gap.

---

## E. Request/Data Flow

**Authentication flow:**
1. Frontend uses `@supabase/supabase-js` directly for login/session management (PKCE flow), talking to Supabase Auth — not to the FastAPI backend — for sign-in itself.
2. The frontend's API wrapper (`frontend/src/api/client.js`) reads the current Supabase session, attaches `Authorization: Bearer <access_token>` to every request to the FastAPI backend, and on a 401 attempts one silent `supabase.auth.refreshSession()` retry before giving up and firing a `siteops:session-expired` event (which `main.jsx` listens for to force a logout).
3. On the backend, the `current_user` dependency (`app/auth.py`) takes that bearer token and calls Supabase's `/auth/v1/user` endpoint (via `app/services/supabase_auth.py`) to validate it and get the Supabase identity. Successful lookups are cached in-process for 30 seconds to reduce repeated calls to Supabase.
4. The backend then looks up a **local** `users` row by `supabase_user_id`. If no matching row exists, the request is rejected with 403 ("not provisioned in SiteOps") even though the Supabase identity itself is valid — i.e., having a Supabase account is necessary but not sufficient; a corresponding row must exist in the app's own `users` table with a role.
5. Role-based authorization is then a simple allow-list check (`require_roles(...)`) per endpoint, plus, in the V2 project module specifically, an additional project-membership check (`can_view`/`can_edit` in `routes/projects_v2.py`).

**Typical read/write flow (e.g., updating an execution task's status):**
Frontend feature component (`ExecutionPage.jsx`) → `executionApi.js` (thin fetch wrapper) → FastAPI route in `execution_v2.py` → role/ownership check → SQLAlchemy query/mutation against `models.py` tables → a status-history row is appended (`services/history.py`) → response serialized back to JSON → frontend calls a shared `refresh()`/`dashboardApi.get()` to reload state (no client-side cache invalidation library; state is refetched wholesale after most mutations, per the `action()` helper in `Dashboard.jsx`).

**File uploads** (task proof photos) are sent as `multipart/form-data` directly to the FastAPI backend, written to a local/volume-mounted `uploads/` directory, and served back via a static file mount (`/uploads`) — not stored in Supabase Storage.

---

## F. Current Implementation Status

Signals used to assess this: which modules have backend test coverage, which endpoints are wired to real logic vs. hardcoded/stubbed responses, and what the README/stabilization checklist describe as expected-working behavior.

- **Working and test-covered:** the V2 template authoring/versioning/publish lifecycle and the V2 project template-review/dependency-generation flow have the large majority of the 25 backend test files pointed at them (`test_template_*`, `test_project_*_v2`), suggesting this is the area of most recent, active development.
- **Working, described as end-user-ready in project docs, but thinly covered in the backend test suite:** the legacy `execution_v2` day-to-day task module (assignment, status updates, proof submission, approval/rejection, delay/reschedule) — this is what `README.md`'s default-login quickstart and `STABILIZATION_CHECKLIST.md` actually walk through end-to-end (create project → 45-day calendar → supervisor updates → PM approval), meaning it is likely the primary user-facing flow today, even though it sits on the older data model.
- **Present in the UI and data model but not functionally wired:** role/module permission editing. The `role_module_permissions` table and a `PermissionMatrix.jsx` UI exist, but the backend explicitly rejects any attempt to save or reset permissions ("Release 1 permissions are fixed by the approved role matrix"), and module visibility per role is hardcoded in `dashboard.py` rather than read from that table.
- **Ambiguous status:** the legacy `projects`/`project_tasks`/`task_templates` tables (distinct from both `execution_*` and the V2 `siteops_v2.projects`) — no route file was found that clearly serves these specific tables as their primary subject during this pass. **Unclear** whether they are still-active, deprecated-but-not-removed, or mid-migration remnants.
- **Explicitly marked deprecated in project docs:** Alembic migrations, per the README ("Migrations: Alembic (deprecated)"), even though the Dockerfile still runs `alembic upgrade head` on every backend startup and the legacy schema (including the actively-used `execution_*` tables) is entirely Alembic-owned. **This appears to be an internal inconsistency** — the tables most clearly tied to the "working" quickstart flow are managed by a migration tool the README calls deprecated.
- **Dead code found:** `backend/app/routes_templates_v2.py` (382 lines) duplicates `backend/app/routes/templates_v2.py` (413 lines) and is not imported by `main.py` or anything else in the codebase — it appears to be an orphaned earlier version of the same router.

---

## G. Areas Requiring More Information

1. **Relationship between the two "v2" project/task systems.** `execution_v2` (legacy data model) and `projects_v2`/`templates_v2` (siteops_v2 schema) both model "a project made of tasks," both are actively developed, and no code path was found connecting them (e.g., a V2 project's reviewed/generated tasks do not appear to become `ExecutionTask` rows for day-to-day tracking). Is the V2 system intended to *replace* the execution module, feed into it, or serve a different purpose (e.g., planning/scoping vs. daily execution)? This materially affects how "Task Management" and "Daily Operations" from the business overview map onto the code.
2. **Status of the legacy `projects`/`project_tasks`/`task_templates` tables** (in `app/models.py`, separate from `execution_*`). No route file clearly owns them. Are they dead, or served by a route not identified in this pass?
3. **Vendors are not a login-capable role in code.** The business overview lists "Vendor" as one of six user roles with "limited external interaction," but the backend's `UserRole` enum only has five values (no `vendor`), and `Vendor` is modeled purely as a data entity (contact record assigned to tasks), not as an authenticated account type. Clarification needed on whether vendor portal access is simply not yet built, or intentionally out of scope for now.
4. **Migration tooling split** (Alembic for legacy/public schema vs. Supabase CLI for `siteops_v2`) — confirm whether this two-tool setup is a deliberate, permanent choice or a planned consolidation, since it affects how new schema changes should be introduced.
5. **Permission matrix UI vs. hardcoded backend.** Confirm whether the "Release 1 permissions are fixed" response is a known, intentional placeholder (with real dynamic permissions planned later) or an incomplete feature that should be finished.
6. **`routes_templates_v2.py` dead file** — confirm it is safe to disregard (not silently relied upon by a script, test, or deployment step outside `main.py`'s router registration).
7. **RLS/authorization model** — confirm the backend's direct-Postgres-connection approach (bypassing Supabase RLS) is the intended long-term security boundary, given the business rules require that "role permissions must always be respected" — all of that enforcement currently lives in Python code, not the database.
8. **Test coverage gap on the actively-used execution module** — only one execution-related backend test file was found (`test_execution_v2_template_leakage.py`) versus ~20+ for the V2 template/project system. Given `execution_v2` appears to be the flow real users exercise per the stabilization checklist, confirm whether this is a known gap.

---

*This document reflects the state of the codebase as read during this analysis session. No code was modified. Findings are based on static reading of source files, configuration, migrations, and test file names/coverage — not on running the application.*
