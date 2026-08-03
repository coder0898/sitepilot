# Requirements: Completing Release 1 (Workved SiteOps)

**Status:** Draft for review
**Date:** 2026-08-02
**Author:** Brainstorm session (Pratik Bakshi + Claude)
**Scope tier:** Deep — feature (product shape already established by the approved PRD/MVP Scope docs and existing V2 codebase)

## Sources

- `Workved_Siteops_PRD.docx` (v1.1, Final Draft for Management Approval)
- `Workved_MVP_Scope.docx` (v1.1, Draft — Release 1 Development Scope)
- `docs/RELEASE_1_IMPLEMENTATION_AUDIT.md` — code-verified status of every MVP Scope Phase 1–3 item against the current `siteops_v2` schema
- `docs/v2/00_ARCHITECTURE_PACKAGE_INDEX.md` and sibling `docs/v2/0X_*.md` architecture decision docs

## 1. Problem

Release 1's **planning layer** (auth, templates, project setup, task/gate generation, dependency generation) is ~90% built and well-tested. Release 1's **execution layer** (day-to-day task tracking, verification, approvals, vendor coordination, WhatsApp, dashboards, reports) is ~0% built in the current `siteops_v2` schema — the `V2ProjectTask.lifecycle_status` column is database-constrained to `'draft'`, so a project task cannot structurally leave the planning stage today.

This document defines the remaining work needed to satisfy the approved PRD and MVP Scope Development Priority list (Phase 1: Execution Backbone, Phase 2: Control Layer, Phase 3: Visibility), sequenced so that dependency order is respected and parallelizable work is identified explicitly.

## 2. Goals

- Every MVP Scope Phase 1–3 module reaches at least "Mostly Complete" status against the audit's own status categories.
- The 10 PRD Non-Negotiable Business Rules (§7) are enforced in code, not just in the planning layer.
- Work is organized so that more than one engineer/stream can build concurrently without blocking each other, wherever the underlying dependency graph allows it.

## 3. Non-goals (explicitly out of scope for Release 1, per PRD §11 / MVP Scope §6)

- AI-based or skill-based automatic task assignment
- Native mobile app / offline mode
- Client or vendor self-service portals
- GPS, biometric attendance, payroll, leave management
- AI delay prediction, full critical-path scheduling
- Automatic reassignment without an approval step

## 4. Dependency reality (why the phasing is what it is)

The audit is explicit that this isn't a matter of preference — it's a hard dependency chain:

- Approval-gate **decisions** (PM approve/reject a landlord NOC, etc.) require a task/decision model that doesn't exist until the execution layer does.
- **Dashboards and reports** require delayed/blocked/overdue/completed states to exist somewhere — there is nothing to aggregate until tasks can leave `draft`.
- **Vendor↔project integration** is schema-independent of the execution layer, so it does *not* have to wait.
- **WhatsApp** is functionally independent of everything else in the app, but is gated by an external dependency (Meta/WABA business approval, approved message templates) that engineering does not control — so it can start in parallel, but "done" for WhatsApp depends on a Product/Ops deliverable outside this document's control.

This gives three phases, each internally decomposed into parallel-safe tracks.

## 5. Phases and Parallel Tracks

### Phase 1 — Task Execution Engine (blocking phase; must land before Phase 2/3 can be "real")

This is the single largest gap and the one everything else depends on. It corresponds to the unfinished remainder of MVP Scope Phase 1 ("Execution Backbone").

| Track | Module | Depends on | Parallel-safe? |
|---|---|---|---|
| 1A | Task lifecycle state machine (status transitions: ready → in_progress → submitted → verified/rejected → completed) | Nothing new — this is the root of Phase 1 | Build first; everything else in this phase reads/writes through it |
| 1B | Evidence upload on a task | 1A's task row existing | Parallel once 1A's schema shape is fixed |
| 1C | Supervisor verification + PM Class-A approval decision | 1A | Parallel once 1A's schema shape is fixed |
| 1D | Blocker and delay capture | 1A | Parallel once 1A's schema shape is fixed |
| 1E | Task-level primary ownership + support-employee assignment + reassignment-with-approval-step | Independent of 1A's internals (touches assignment, not lifecycle) | Fully parallel with 1A–1D |
| 1F | Baseline immutability (real snapshot at activation, not just a status flag) | Independent — touches project activation only | Fully parallel with 1A–1E |

**Parallel guidance:** 1A should land first (or at least its schema/contract shape agreed) since 1B/1C/1D build on it. 1E and 1F have no dependency on 1A at all and can start on day one alongside it — three concurrent streams are realistic: (Stream 1: 1A→1B→1C→1D), (Stream 2: 1E), (Stream 3: 1F).

**Business rules landed by this phase:** "Every active task must have one Primary Responsible Employee," "Employee absence must trigger reassignment," "Class A work requires Supervisor verification and PM approval," "Blocked and overdue are separate conditions," "The baseline schedule remains locked after activation."

### Phase 2 — Control Layer

Corresponds to MVP Scope Phase 2. Depends on Phase 1 existing (for 2A only) — 2B and 2C do not.

| Track | Module | Depends on | Parallel-safe? |
|---|---|---|---|
| 2A | Approval-gate decision step (PM approve/reject an external gate; blocking-dependency enforcement) | Phase 1's approval mechanics (1C) | Blocked until 1C lands |
| 2B | Vendor ↔ V2 project/task integration (bridge the existing, working legacy vendor module into `siteops_v2`) | Nothing in Phase 1 | Fully parallel — can start immediately, even before Phase 1 finishes |
| 2C | WhatsApp notifications (assignment, reminders, delay alerts, reassignment alerts) | Nothing in Phase 1 for infrastructure (outbox, provider integration, retry/suppression); the actual message *content* depends on which events exist, which grows as Phase 1 lands | Infrastructure work (outbox pattern, provider client, delivery tracking) is parallel-safe from day one; wiring specific event triggers happens incrementally as Phase 1 modules land |

**External blocker (not engineering-controlled):** 2C cannot go live without Meta/WABA business approval and approved message template wording — a Product/Ops deliverable that should be kicked off in parallel with Phase 1, not after it, since it has its own external lead time.

### Phase 3 — Visibility

Corresponds to MVP Scope Phase 3. Needs Phase 1 data to exist to be meaningful; largely independent of Phase 2.

| Track | Module | Depends on | Parallel-safe? |
|---|---|---|---|
| 3A | Management dashboards (progress, delayed/blocked/overdue/no-update, pending approvals, reassignment-pending, vendor risk) | Phase 1 (needs real states to aggregate); vendor-risk widget also needs 2B | Can start once Phase 1's state machine (1A) is stable, doesn't need 2A/2C |
| 3B | Daily/weekly report generation | Phase 1 | Parallel with 3A — different surface, same underlying data |
| 3C | Cross-project / Admin-level audit history view | Nothing new — per-project audit already exists (Phase "Mostly Complete" per audit); this is a rollup view | Fully parallel, can be done anytime, even now |

**Parallel guidance:** 3A and 3B are separable workstreams reading the same data; 3C has no dependency on anything above and could be pulled forward into Phase 1 or Phase 2 if a stream has spare capacity.

## 6. What can run in parallel *across* phases, not just within them

Because 1E, 1F, 2B, and 3C have no real dependency on the Phase 1 state machine (1A), a team with multiple concurrent streams doesn't have to wait for phases to fully close before starting the next phase's independent tracks. A realistic four-stream parallel plan:

- **Stream 1 (core):** 1A → 1B → 1C → 1D → 2A (this stream is the critical path; it gates 2A, 3A, 3B)
- **Stream 2 (ownership):** 1E, then idle or reassigned once done (early finisher)
- **Stream 3 (structural):** 1F, then 2B (vendor bridge), then 3C (audit rollup) — none of these wait on Stream 1
- **Stream 4 (external-gated):** 2C infrastructure (outbox, provider client, retry logic) in parallel with Product/Ops chasing Meta/WABA approval — this stream's *finish* is capped by an external approval timeline regardless of engineering speed

3A and 3B start once Stream 1 reaches the end of 1D (state machine + evidence + verification + blockers/delays all in place) — they are the last things to unblock because they need the fullest picture of task state.

## 7. Success Criteria (from PRD §9 / MVP Scope §5, unchanged — restated here as the completion bar)

- 100% of active tasks and external approvals have exactly one internal owner.
- 100% of ownership/reassignment changes are approval-gated and fully audited.
- 100% of absent-owner responsibilities enter the reassignment workflow; no urgent responsibility remains without temporary ownership.
- No critical (Class A) work closes without required verification + approval.
- At least 90% daily task/responsibility update compliance (requires Phase 1 + WhatsApp reminders from 2C to be realistically achievable).
- Project status available anytime (Phase 3 dashboard).
- Consistent daily/weekly report generation (Phase 3).
- Complete audit history for assignments, reassignments, approvals, overrides (already substantially met; 3C closes the remaining gap).

## 8. Assumptions (flag for review, not yet validated with Product/Ops)

- The 45-day template *content* sign-off (currently "recovered generic legacy seed," per `01_BUSINESS_RULES_DECISION_RECORD.md` §4) is a Product/Ops deliverable running in parallel to all engineering phases, not a blocker to starting Phase 1.
- The final five-role permission/fallback matrix sign-off (per `docs/v2/00_ARCHITECTURE_PACKAGE_INDEX.md` §4) is assumed to land before or during Phase 1, since task-level ownership (1E) and approval decisions (1C/2A) depend on knowing exactly who can do what.
- WhatsApp's Meta/WABA approval lead time is unknown to this document — Stream 4's actual completion date cannot be estimated without a Product/Ops-supplied timeline.
- The legacy `execution_v2` module's existing (but disconnected) implementation of status transitions, proof upload, and approve/reject is assumed to be usable as a reference/pattern for Phase 1, not reusable code as-is (different schema, and per prior direction it is being replaced, not extended).

## 9. Open Decisions for Planning (`/ce-plan`)

These are intentionally left to planning, not decided here:

- Whether Phase 1's task lifecycle state machine reuses/adapts patterns from the legacy `execution_v2` module or is designed fresh against the V2 data model spec.
- Exact schema for `task_progress_updates`, `task_evidence`, `task_verifications`, `task_approval_decisions`, `task_blockers`, `task_delay_events`, `task_support_assignments` (all named in `docs/v2/02_V2_DATA_MODEL_SPECIFICATION.md` but not yet built).
- Whether to relax the `lifecycle_status = 'draft'` constraint via a new migration or a different mechanism.
- WhatsApp provider selection and outbox/retry architecture details.
