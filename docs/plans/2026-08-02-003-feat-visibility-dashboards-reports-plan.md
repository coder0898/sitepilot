---
title: Visibility — Dashboards and Reports (Release 1, Phase 3)
type: feat
status: active
date: 2026-08-02
origin: docs/brainstorms/release-1-completion-requirements.md
---

# Visibility — Dashboards and Reports (Release 1, Phase 3)

## Summary

Build a read-side aggregation layer over Phase 1's task/blocker/delay/reassignment data (and Phase 2's vendor activity data) and expose it as a per-project management dashboard, versioned daily/weekly report snapshots, and a cross-project Admin rollup view. This is predominantly read/query work — no new mutation semantics are introduced; the aggregation queries are the design surface.

---

## Problem Frame

Per `docs/RELEASE_1_IMPLEMENTATION_AUDIT.md`, there is currently nothing matching "dashboard" as described in PG-01/BR-016 — the closest existing artifact is a per-project raw audit-event feed, not a summarized view. No report generation exists at all. Both are structurally blocked on Phase 1's execution-layer data existing, since there is nothing to aggregate (no delayed/blocked/overdue states, no pending verifications/approvals) until tasks can actually move through a lifecycle.

**Depends on:** `docs/plans/2026-08-02-001-feat-task-execution-engine-plan.md` (Phase 1, for all task-state data) and, for the vendor-risk widget only, `docs/plans/2026-08-02-002-feat-control-layer-vendor-whatsapp-plan.md` (Phase 2 U3).

---

## Requirements

- R1. A per-project dashboard shows planned/active/completed work counts plus derived `delayed`, `blocked`, `overdue`, and `no_update` counts (PG-01, BR-016).
- R2. The dashboard shows pending verification/approval items and approval gates at risk (approaching or past their due date without a decision).
- R3. The dashboard shows responsibilities awaiting reassignment (Phase 1 U6's "Reassignment Required" condition) and current support-employee allocation.
- R4. The dashboard shows vendor risks/incidents for the project (Phase 2 U3's `vendor_activity_events`), when Phase 2 has shipped; the widget degrades gracefully (empty state, not an error) if Phase 2 data doesn't exist yet.
- R5. A daily report is generated from recorded system data, containing the same categories as the dashboard (planned/completed/delayed/blocked/overdue/no-update, pending decisions, approval gates at risk, and role/support changes required — i.e. Phase 1 U6's `project_role_changes`/`support_assignment_changes` data) and stored as a versioned snapshot (BR-016).
- R6. A weekly report is generated showing milestone progress, schedule movement (from Phase 1's `task_schedule_revisions`), vendor concerns, role/support changes (the same `project_role_changes`/`support_assignment_changes` data as R5, over the week's window), and management decisions required (BR-016).
- R7. Authorized Admin users can view an aggregated cross-project rollup, not just single-project detail (BR-016's "Release 1 cross-project visibility is available to authorized Admin users").

**Origin flows:** Visibility (origin doc §5, Phase 3 tracks 3A "Dashboards," 3B "Reports," 3C "Cross-project/Admin-level audit view"). Track 3C's per-project audit view already exists per the Release 1 audit (`GET /api/v2/projects/{id}/activity`) and is "Mostly Complete" — this plan's U4 extends it to a cross-project rollup rather than building it from scratch.

---

## Scope Boundaries

- No Management-role portal or separate Management experience — BR-003 explicitly confirms Management follows a separate product direction outside Release 1; this plan's cross-project view (R7) is scoped to **Admin**, not a new Management role.
- No AI-driven delay prediction, forecasting, or critical-path analysis — PRD §11 exclusion; all figures here are counts/aggregates of recorded data, not predictions.
- No real-time push/websocket updates — dashboard and report data are computed on request (or on a scheduled snapshot for reports); polling/refresh-on-navigate is sufficient for Release 1.
- No report *distribution* (email/WhatsApp delivery of report snapshots) — that's a Phase 2 outbox consumer, not part of this plan; this plan only generates and stores the snapshot, viewable in the portal.

### Deferred to Follow-Up Work

- Report distribution via WhatsApp/email once Phase 2's outbox infrastructure exists — noted as a natural follow-up, not built here.
- Historical trend charts (e.g., delay trend over time) beyond the current-state dashboard and point-in-time report snapshots — Release 1 scope is current-state visibility, not analytics.

---

## Context & Research

### Relevant Code and Patterns

- `backend/app/routes/dashboard.py` — existing `/api/me` and `/api/dashboard` routes serve identity/navigation data (role-scoped module visibility), not metrics; this plan adds new routes rather than repurposing these, to avoid overloading an identity-purposed endpoint with aggregation logic.
- `GET /api/v2/projects/{id}/activity` (`backend/app/routes/projects_v2.py`) — existing per-project audit feed, the closest existing "visibility" artifact; U5 extends this pattern to cross-project scope for Admin.
- `frontend/src/features/dashboard/Dashboard.jsx`, `DashboardTab.jsx` — existing tab-shell/routing components; this plan's dashboard UI is new content rendered inside this existing shell, not a shell replacement.
- `GET /api/v2/projects` (`backend/app/routes/projects_v2.py`) — already returns status/team/template per project; the audit specifically noted this as a realistic "project list" foundation, reusable as a building block for R7's rollup rather than rebuilt.
- Phase 1's `tasks`, `task_blockers`, `task_delay_events`, `task_verifications`, `task_approval_decisions` tables and Phase 1 U6's "Reassignment Required" derived condition — the primary data sources for R1–R3.
- Phase 2's `vendor_activity_events` (if shipped) — data source for R4.

### Institutional Learnings

- None in `docs/solutions/` yet. This plan is a good candidate to document aggregation-query patterns (derived-condition computation, snapshot versioning) once implemented, since Phase 2 also touches similar "compute from recorded events" territory.

---

## Key Technical Decisions

- **Dashboard is a read-side query service, not a materialized/cached table**: given Release 1's expected data volume (one 45-day project's worth of tasks at a time, not millions of rows), computing counts on request from `tasks`/`task_blockers`/`task_delay_events` directly is simpler and avoids a cache-invalidation problem. Revisit only if a real project's query proves too slow — not assumed here.
- **`overdue`/`no_update`/`blocked`/`delayed` counts reuse Phase 1's derived-condition logic exactly**: rather than reimplementing "what counts as overdue" in the dashboard layer, this plan calls the same query helpers Phase 1 U5 established (per that plan's Open Questions resolution: computed on read from `due_at`/`update_sla_hours`), so the dashboard and any future WhatsApp reminder (Phase 2) never disagree about what "overdue" means.
- **Report snapshots are computed once and frozen, not live-recomputed on view**: `report_snapshots.payload_json` captures the aggregation result at generation time; viewing a past daily report always shows what was true when it was generated, not today's live numbers — this is the point of BR-016's "versioned snapshot" language, and prevents a report from silently changing after the fact.
- **Cross-project rollup (R7) is Admin-only, reusing existing role-check patterns**: no new "Management" concept is introduced; access control mirrors the existing admin/super_admin bypass pattern already used throughout `projects_v2.py`.

---

## Open Questions

### Resolved During Planning

- Whether dashboard data is cached/materialized: resolved — no, compute-on-request for Release 1 scale (see Key Technical Decisions).
- Whether report snapshots recompute on view: resolved — no, frozen at generation time.

### Deferred to Implementation

- Exact scheduling mechanism for automatic daily/weekly report generation (cron-style scheduled job vs. on-demand "Generate Report" button that also auto-runs daily) — both satisfy BR-016's "generated from recorded system data" requirement; the choice is an operational detail, not a design decision this plan needs to lock down. Default to an on-demand generation endpoint with a note that automatic scheduling can wrap it later without a schema change.
- Whether the vendor-risk widget (R4) should visibly indicate "Phase 2 not yet deployed" versus simply showing empty — a UX polish decision better made when Phase 2's actual ship date is known.

---

## Implementation Units

- U1. **Per-project aggregation query service**

**Goal:** Build the shared read-side service that computes all dashboard/report categories (status counts, derived conditions, pending decisions, reassignment/support state) for a single project.

**Requirements:** R1, R2, R3

**Dependencies:** Phase 1 (all units)

**Files:**
- Create: `backend/app/services/project_visibility.py` (`ProjectVisibilityService.summarize(project_id)`)
- Create: `backend/app/schemas/project_visibility.py`
- Test: `backend/tests/test_project_visibility_summary_v2.py`

**Approach:**
- One service call returns a structured summary: task counts by `lifecycle_status`, counts of derived `blocked`/`delayed`/`overdue`/`no_update` conditions (reusing Phase 1's exact derivation logic per Key Technical Decisions), pending `task_verifications`/`task_approval_decisions` awaiting action, approval gates past/near their due date without a decision, and Phase 1 U6's "Reassignment Required" projects/tasks.
- This service is the single source of truth both the dashboard route (U2) and report generation (U3) call — no duplicate aggregation logic between them.

**Test scenarios:**
- Happy path: a project with a mix of task states returns correct counts for each `lifecycle_status`.
- Happy path: a task with an unresolved blocker and a task past its `due_at` both appear in their respective derived-condition counts, simultaneously if applicable (matching Phase 1's "not mutually exclusive" rule).
- Edge case: a project with zero tasks (e.g., still in setup) returns a valid all-zero summary, not an error.
- Edge case: an approval gate with no decision past its due date appears in "approval gates at risk"; one decided on time does not.
- Integration: the same summary values are returned identically whether called from U2's dashboard route or U3's report generator, for the same project at the same instant.

**Verification:**
- Every dashboard/report category traces to exactly one call into this service — no parallel aggregation logic exists elsewhere in the codebase.

---

- U2. **Project dashboard API and frontend view**

**Goal:** Expose U1's summary as a per-project dashboard screen.

**Requirements:** R1, R2, R3, R4

**Dependencies:** U1; Phase 2 U3 for R4's vendor-risk data (degrades gracefully if absent)

**Files:**
- Create: `backend/app/routes/project_dashboard_v2.py` (`GET /api/v2/projects/{id}/dashboard`)
- Create: `frontend/src/features/projects/components/ProjectDashboard.jsx`
- Modify: `frontend/src/api/projectsApi.js` (add `dashboard(projectId)` call)
- Test: `backend/tests/test_project_dashboard_route_v2.py`

**Approach:**
- Route composes U1's summary with a vendor-risk query if Phase 2's `vendor_activity_events` table exists; if not (e.g., Phase 2 not yet deployed), the vendor-risk section returns an empty list rather than erroring. Presence is checked once at application startup (a simple `inspect(engine).has_table("vendor_activity_events")` check cached for the process lifetime, not re-checked per request) — a boolean the dashboard route reads, not a per-request try/catch around a missing-table error.
- Frontend follows the existing card/summary layout conventions used elsewhere in `features/projects/`, not a new design system.

**Test scenarios:**
- Happy path: an authorized project member (any role with project access) retrieves the dashboard and sees all summary categories.
- Edge case: dashboard request for a project with no vendor data (Phase 2 not shipped) succeeds with an empty vendor-risk section, not a 500.
- Error path: a user with no membership on the project and no admin/super_admin role cannot retrieve its dashboard.

**Verification:**
- The dashboard renders correctly against a project seeded purely with Phase 1 data (no Phase 2 dependency required for the page to function).

---

- U3. **Daily and weekly report generation**

**Goal:** Generate versioned daily/weekly report snapshots from U1's aggregation (daily) and an extended weekly aggregation (milestones, schedule movement, vendor concerns, ownership changes).

**Requirements:** R5, R6

**Dependencies:** U1

**Files:**
- Create: `supabase/migrations/<timestamp>_v2_report_snapshots.sql` (`report_snapshots`)
- Modify: `backend/app/execution_models.py` or a new `backend/app/report_models.py`
- Create: `backend/app/services/report_generation.py` (`ReportGenerationService.generate(project_id, report_type, period_start, period_end)`)
- Create: `backend/app/routes/reports_v2.py` (`POST /api/v2/projects/{id}/reports`, `GET /api/v2/projects/{id}/reports`)
- Test: `backend/tests/test_report_generation_v2.py`

**Approach:**
- Daily report payload is U1's summary plus role/support changes required (from Phase 1 U6), captured at generation time into `payload_json`.
- Weekly report additionally aggregates milestone completion progress, `task_schedule_revisions` (schedule movement), vendor concerns (Phase 2, if present), ownership changes (`project_role_changes`/`support_assignment_changes` from Phase 1 U6), and a "management decisions required" list (derived from pending approvals + reassignment-required + at-risk gates).
- `version_no` is unique within `(project_id, report_type, period)` — regenerating a report for an already-generated period creates a new version rather than overwriting, preserving history per the append-only modelling principle.

**Test scenarios:**
- Happy path: generating a daily report for a project produces a `report_snapshots` row with `report_type='daily'` and a payload matching U1's live summary at that instant.
- Happy path: generating a weekly report includes milestone/schedule/ownership-change data not present in the daily report.
- Edge case: generating two reports for the same project/type/period produces two versions, not an overwrite.
- Edge case: a report generated before any tasks existed (early project) still produces a valid, mostly-empty snapshot.
- Error path: an unauthorized user (no project access, not Admin) cannot trigger report generation or view snapshots.

**Verification:**
- Viewing an older report version shows the data as it was at generation time even if the project's live state has since changed (frozen-snapshot guarantee from Key Technical Decisions).

---

- U4. **Cross-project Admin rollup view**

**Goal:** Give Admin a multi-project rollup view, extending the existing per-project list/audit patterns to cross-project scope.

**Requirements:** R7

**Dependencies:** `GET /api/v2/admin/activity` has no dependency on U1 or Phase 1 (it queries `V2AuditEvent`, which already exists) and can be built first/independently; `GET /api/v2/admin/projects-overview` depends on U1 (and transitively Phase 1), since it calls the summarize service per project.

**Files:**
- Create: `backend/app/routes/admin_visibility_v2.py` (`GET /api/v2/admin/projects-overview`, `GET /api/v2/admin/activity`)
- Create: `frontend/src/features/admin/AdminProjectsOverview.jsx`
- Test: `backend/tests/test_admin_visibility_rollup_v2.py`

**Approach:**
- `projects-overview` calls U1's summarize service per project (bounded by the existing `GET /api/v2/projects` list, reusing that endpoint's data as the audit previously identified) and returns a lightweight rollup — status/team/template plus top-line counts, not the full per-project detail. At Release 1's expected project count this per-project-call pattern is acceptable; if project count grows meaningfully, this should become a single aggregate query rather than N calls to `summarize()` (noted here, not solved speculatively).
- `activity` extends the existing per-project `GET /{project_id}/activity` pattern to an unscoped, paginated, Admin-only cross-project query against `V2AuditEvent` — same table, wider filter, not a new audit system. This endpoint has no Phase 1 dependency and is the part of U4 that can genuinely be pulled forward and built early (see Documentation / Operational Notes).
- Access control: admin/super_admin only, following the existing bypass pattern rather than introducing a new permission concept.

**Test scenarios:**
- Happy path: an Admin retrieves a rollup across N projects with correct per-project top-line counts.
- Happy path: an Admin retrieves cross-project audit activity, correctly excluding a project they'd otherwise need direct membership to see (Admin's bypass, not membership, grants this).
- Error path: a PM/Supervisor/Internal Employee (no admin/super_admin role) cannot access either endpoint, even for projects they're a member of.
- Edge case: a rollup request with zero projects in the system (fresh install) returns an empty list, not an error.

**Verification:**
- No new audit storage is introduced — the cross-project view is provably a wider query over the existing `V2AuditEvent` table, not a parallel logging system.

---

## System-Wide Impact

- **Interaction graph:** U1 is the single dependency every other unit in this plan calls through — U2, U3, and U4 all consume it rather than querying Phase 1's tables directly, keeping aggregation logic in one place.
- **Error propagation:** All units are read-only except U3's report generation (a write, but append-only, non-destructive); no unit in this plan can corrupt or block Phase 1/Phase 2 data — worst case is a slow or empty read.
- **State lifecycle risks:** The only lifecycle concern is report-snapshot versioning (U3) — covered by its own uniqueness constraint and test scenarios; no other unit introduces new stateful risk.
- **API surface parity:** New read-only surface only; no existing endpoint's behavior changes.
- **Integration coverage:** U1's summary must agree exactly between its two callers (U2 dashboard, U3 report) at the same instant — the one integration scenario worth testing explicitly beyond each unit's own tests (already listed under U1).
- **Unchanged invariants:** Phase 1 and Phase 2's mutation services, data model, and business rules are entirely unmodified by this plan — every unit here is additive and read-side only.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Compute-on-request aggregation (no caching) could be slow if a project accumulates a very large number of tasks/events | Accepted for Release 1's expected scale (one 45-day project's data); revisit with caching/materialization only if real usage shows it's slow — not solved speculatively here |
| R4 (vendor-risk widget) creates a soft dependency on Phase 2 shipping first, even though this plan is otherwise Phase 1-only | U2 explicitly designs for graceful degradation (empty state) when Phase 2 data is absent, so this plan does not block on Phase 2's timeline |
| Report snapshot regeneration creating unbounded versions if triggered too frequently (e.g., accidental repeated calls) | Deferred to implementation: consider a minimum-interval guard between report generations for the same period, noted here rather than engineered speculatively |
| Cross-project rollup (U4) could become a performance concern as the number of projects grows | Same accepted-for-Release-1-scale reasoning as the caching risk above; not a concern at expected project counts |

---

## Documentation / Operational Notes

- Update `docs/RELEASE_1_IMPLEMENTATION_AUDIT.md`'s "Dashboard," "Reports," and "Audit History View" sections once this plan lands.
- This plan closes the loop the origin brainstorm doc's Section 6 (cross-phase parallel streams) anticipated — specifically, U4's `GET /api/v2/admin/activity` endpoint (not the full U4 unit, since `projects-overview` does depend on U1/Phase 1) was called out there as pullable forward with no real dependency on Phase 1/2 finishing; if capacity allows, that piece can be built early rather than strictly last.

---

## Sources & References

- **Origin document:** [docs/brainstorms/release-1-completion-requirements.md](docs/brainstorms/release-1-completion-requirements.md)
- **Depends on plans:** [docs/plans/2026-08-02-001-feat-task-execution-engine-plan.md](docs/plans/2026-08-02-001-feat-task-execution-engine-plan.md), [docs/plans/2026-08-02-002-feat-control-layer-vendor-whatsapp-plan.md](docs/plans/2026-08-02-002-feat-control-layer-vendor-whatsapp-plan.md)
- Architecture baseline: `docs/v2/02_V2_DATA_MODEL_SPECIFICATION.md` (§9, `report_snapshots`), `docs/v2/01_BUSINESS_RULES_DECISION_RECORD.md` (BR-016)
- Existing gap analysis: `docs/RELEASE_1_IMPLEMENTATION_AUDIT.md` ("Dashboard," "Reports," "Audit History View" sections)
