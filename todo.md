# TODO — Phase 1 Units (U1-U6): all implemented

Plan: `docs/plans/2026-08-02-001-feat-task-execution-engine-plan.md`
Branch: `feat/task-execution-engine`

## Status

- [x] U1: Baseline lock and task/dependency/gate instantiation — committed (`7022d42`)
- [x] U2: Task lifecycle state machine — committed (`e538f9e`)
- [x] U3: Progress updates and evidence submission — committed (`035fe7b`)
- [x] U4: Supervisor verification and PM approval decisions — committed (`f6b9520`)
- [x] U5: Blocker and delay capture — committed (`fc6f360`)
- [x] U6: Task-level accountability, support assignment, controlled reassignment — committed (`fc6f360`)

All six implementation units of the plan are now committed. Remaining work is the plan's Quality Check and Shipping steps below — this file's per-unit specs are preserved for reference but no longer describe outstanding work.
- [ ] U6: Task-level accountability, support assignment, controlled reassignment — not started

## U5 — Blocker and delay capture

**Requirements:** R5 (see plan). **Dependencies:** U1, U2 (both done).

**Files to create:**
- `supabase/migrations/202608020004_v2_task_blockers_delays.sql` — `task_blockers` (id, task_id, type, description, owner_employee_id, started_at, resolved_at, resolved_by), `task_delay_events` (id, task_id, responsibility_type in ('vendor','client','approval','design','site_readiness','internal','other'), responsible_vendor_id nullable, reason, impact_days, recorded_by, created_at). Follow U1/U3 migration conventions exactly (`revoke all ... from anon, authenticated`, index naming).
- `backend/app/services/task_blocker.py` — create blocker, resolve blocker (resolver must be accountable Supervisor/PM or authorized fallback).
- `backend/app/services/task_delay.py` — create delay event; `responsible_vendor_id` required when `responsibility_type == 'vendor'`, else null.
- `backend/tests/test_task_blockers_delays_v2.py` — all plan U5 test scenarios (log/resolve blocker, log delay, task simultaneously blocked+delayed+in_progress with no mutual-exclusion constraint, vendor-responsibility requires vendor id, no-membership actor rejected).

**Files to modify:**
- `backend/app/execution_models.py` — add `TaskBlocker`, `TaskDelayEvent` models.
- `backend/app/routes/execution_tasks_v2.py` — add `POST /{task_id}/blockers`, `POST /{task_id}/blockers/{blocker_id}/resolve`, `POST /{task_id}/delays`.
- `backend/app/schemas/execution_tasks.py` — add request/response schemas.

**Key point:** blocker/delay creation must NOT change `Task.lifecycle_status` — they're independent, combinable conditions per BR-010, not lifecycle states. Do not call `TaskLifecycleService.transition` from these services at all.

## U6 — Task-level accountability, support assignment, controlled reassignment

**Requirements:** R6, R7 (see plan). **Dependencies:** U1 (done).

**Files to create:**
- `supabase/migrations/202608020005_v2_support_assignments_role_changes.sql` — `task_support_assignments` (id, task_id, employee_id, responsibility, status, starts_at, ends_at, assigned_by), `support_assignment_changes`, `project_role_changes` (id, project_id, role_type, previous_membership_id, replacement_employee_id, change_type, reason_code, reason_detail, effective_from, effective_to, changed_by, created_at) **plus a partial unique index on `V2ProjectMembership`** enforcing at most one active (`ends_at IS NULL`) `project_manager` and one active `site_supervisor` per project — this is a document-review-confirmed gap (currently application-code-only via `assign_membership()`).
- `backend/app/services/task_support_assignment.py` — Supervisor controls support for `work` tasks, PM controls follow-up support for `approval_gate` tasks; assignee must be active `internal_employee` project member; unique active assignment per task/employee.
- `backend/app/services/project_role_change.py` — two-step request/approval flow: Admin requests/approves PM replacement, active PM requests/approves Supervisor replacement (Admin audited fallback). A `pending` record doesn't affect current accountability; approval atomically ends previous membership + starts replacement (reuse `assign_membership()`'s existing transactional pattern).
- `backend/tests/test_task_support_assignment_v2.py`, `backend/tests/test_project_role_change_approval_v2.py` — all plan U6 test scenarios, INCLUDING the new DB-level partial-unique-index test (reject a second concurrent active PM/Supervisor at the DB level, independent of `assign_membership()`'s own check).

**Files to modify:**
- `backend/app/execution_models.py` — add `TaskSupportAssignment`, `SupportAssignmentChange`, `ProjectRoleChange` models.
- `backend/app/routes/projects_v2.py` — `assign_membership()` needs to move from immediate-effect to the two-step request/approval flow for accountable roles (PM/Supervisor). Support-assignment endpoints live in `execution_tasks_v2.py` instead.
- `frontend/src/features/projects/components/ProjectTeamReplaceModal.jsx` — surface pending-approval state instead of assuming immediate effect (this is a real UX/behavior change — flag it explicitly when this ships).

**Key point:** `EmployeeProfile.availability == 'unavailable'` should surface a queryable "Reassignment Required" condition (not a new column, not a silent auto-reassignment) per BR-007's "automatic skill-based or silent replacement is prohibited."

## After U5 and U6

1. Quality check task (#7 in the task list): run full backend test suite (blocked on Python/Docker not being available in this session's environment — needs to run in an environment that has them), review RLS policy shape for all new tables added across U1–U6, confirm the U2↔U4↔U1 dependency-integration test actually passes.
2. Shipping workflow (#8): flip `docs/plans/2026-08-02-001-feat-task-execution-engine-plan.md` frontmatter `status: active` → `status: completed`, prepare final commit/PR summary.

## Environment note

No Python or Docker interpreter is available in this working environment, so none of U1–U4's tests have been executed — only manually/carefully reviewed. Before merging, run:

```
pytest backend/tests/test_project_baseline_lock_v2.py backend/tests/test_task_lifecycle_transitions_v2.py backend/tests/test_task_progress_evidence_v2.py backend/tests/test_task_verification_approval_v2.py backend/tests/test_project_activation_deletion_v2.py backend/tests/test_project_execution_tasks_v2.py backend/tests/test_supervisor_readonly_view_v2.py
```

in an environment with the project's Python/Docker toolchain, and fix any failures before U5/U6 build further on top of this code.
