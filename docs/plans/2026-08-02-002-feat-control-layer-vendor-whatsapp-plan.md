---
title: Control Layer — Vendor Integration and WhatsApp Infrastructure (Release 1, Phase 2)
type: feat
status: completed
date: 2026-08-02
origin: docs/brainstorms/release-1-completion-requirements.md
---

# Control Layer — Vendor Integration and WhatsApp Infrastructure (Release 1, Phase 2)

## Summary

Bridge the existing legacy vendor module into the new `siteops_v2` schema (project-vendor mapping, task delegation, acknowledgement, activity/incident capture) and build the WhatsApp communication infrastructure (outbox events, provider-agnostic delivery tracking, retry/idempotency, inbound message matching) called for by BR-015. WhatsApp *infrastructure* is buildable now; WhatsApp *live sending* is not — it is gated by an external Meta/WABA business approval and approved message-template wording that Product/Ops must supply, outside engineering's control.

---

## Problem Frame

Per `docs/RELEASE_1_IMPLEMENTATION_AUDIT.md`, vendor master-data management works today but lives entirely on the legacy schema (`app.models.Vendor`), disconnected from the new `siteops_v2` project/task system — no V2 project can currently have a vendor mapped to it or a task delegated to one. Separately, WhatsApp — the PRD's headline differentiator (PG-06) — has zero implementation: no outbox, no delivery tracking, no provider integration; only a manually-logged "channel" field exists in the Communication Hub.

**Depends on:** `docs/plans/2026-08-02-001-feat-task-execution-engine-plan.md` (Phase 1) — vendor task delegation needs the `tasks` table (Phase 1 U1) to exist, and outbox event emission needs Phase 1's mutation points (status transitions, verification/approval, blockers/delays, reassignment) as the events it wraps.

---

## Requirements

- R1. Legacy vendor/sub-vendor master data is imported into new `siteops_v2` vendor tables (one-time, validated import per BR-019), not live-synced — the legacy module remains the source of truth for its own schema, but new project/task work reads only the V2 tables.
- R2. A vendor can be mapped to a project (`project_vendors`) only when active, and a sub-vendor only when its parent vendor already has an active project mapping (BR-012).
- R3. A task can be delegated to a mapped vendor (`task_vendor_assignments`) without transferring Site Supervisor accountability (BR-013) — the accountable Supervisor from Phase 1's derived-accountability model remains accountable regardless of vendor delegation.
- R4. A vendor assignment can receive an acknowledgement response — `accepted`, `declined`, or `clarification_requested` (`vendor_acknowledgements`); vendors cannot start, complete, verify, approve, or close a task through this mechanism (BR-013).
- R5. Vendor-attributable activity — presence, delay, rework, incident — can be recorded with evidence (`vendor_activity_events`, reusing Phase 1's `file_objects` pattern) (BR-014).
- R6. Every mandatory domain event listed in BR-015 (project assignment, PM/Supervisor membership change, support assignment/change, vendor assignment, due tomorrow/today, blocker/delay, evidence submitted, verification/rejection, approval/rejection, approval-gate reminders) is written to a durable `outbox_events` row in the same transaction as the domain mutation that caused it.
- R7. `message_deliveries` tracks provider-agnostic delivery status (`queued/sending/sent/delivered/read/failed/suppressed`) with idempotency keys preventing duplicate sends.
- R8. Inbound WhatsApp replies (`inbound_messages`) are matched to an authenticated portal-user or vendor-contact identity by phone number; unmatched/unauthorized messages are retained for review but cannot mutate business state.
- R9. Employee WhatsApp update commands and vendor acknowledgement replies produce the identical audit events a portal action of the same kind would produce (BR-015).

**Origin flows:** Control Layer (origin doc §5, Phase 2 tracks 2B "Vendor ↔ V2 project/task integration" and 2C "WhatsApp notifications"). Track 2A ("Approval-gate decision step") from the origin doc is **already delivered** by Phase 1's plan (see `2026-08-02-001-feat-task-execution-engine-plan.md` Implementation Unit U4, which implements the full BR-008 decision model for both Class A work and approval-gate tasks in one service) — it is not repeated here.

---

## Scope Boundaries

- No live WhatsApp sending. This plan builds the outbox/delivery/provider-adapter infrastructure and can be exercised against a sandbox/test provider, but Product/Ops must supply Meta/WABA business approval, approved template wording, and a recipient/consent matrix before any real message goes out — that approval is not in engineering's control and is not part of this plan's deliverable.
- No client or vendor self-service portal — vendor interaction remains WhatsApp-and-PM-managed only, per PRD §11. This excludes a vendor-facing login/UI specifically; it does not exclude the internal PM-facing UI this plan's U2/U3 add for mapping vendors, delegating tasks, and logging acknowledgement/activity on a vendor's behalf ("PM-managed" implies the PM needs a portal surface to manage from).
- No Admin-facing outbox/delivery monitoring dashboard for U4–U6's infrastructure (failed sends, retry queues) — these units have no natural end-user screen of their own; delivery outcomes surface indirectly through U2/U3's UI once a recipient acts on a message. A dedicated monitoring view is a reasonable follow-up, not required to satisfy R6–R9.
- No automated vendor scoring, ranking, or replacement recommendation (BR-014 explicitly excludes this from Release 1).
- No changes to the legacy vendor module's own CRUD (`backend/app/routes/vendors.py`) beyond what's needed to run the one-time import — it keeps functioning as today's vendor master-data UI.
- No dashboard/report consumption of this data — Phase 3 owns aggregation; this plan only produces the underlying records.

### Deferred to Follow-Up Work

- Ongoing legacy-vendor-to-V2 reconciliation (e.g., if the legacy module keeps being used for new vendor creation after this plan ships) is not solved here — this plan assumes a cutover point after which new vendors are created directly in V2, to be confirmed operationally, not engineered around speculatively.
- Actual Meta/WABA account setup, template approval, and going live — tracked as a Product/Ops deliverable, not an engineering unit.

---

## Context & Research

### Relevant Code and Patterns

- `backend/app/routes/vendors.py`, `app.models.Vendor` — legacy vendor CRUD already implements most of BR-012's rules (`engagement_type`, mandatory `parent_vendor_id` for sub-vendors, status history, category mapping) on the old schema; read as the source for the one-time import in U1.
- `app.models.Vendor.engagement_type` also has a third state, `migration_pending` (with `migration_status` `ready`/`parent_required`), and `VendorParentMigrationCandidate` tracks candidate parent assignments for vendors in that unresolved state — U1's import must decide how to handle these rows (import as-is pending resolution, or require resolution before import), not treat `engagement_type` as a simple two-state field.
- `app.models.ContractorRelationship` (`main_contractor_id`/`subcontractor_id`) is a **second, separate** legacy representation of main/sub-vendor relationships that coexists with `Vendor.parent_vendor_id` — U1 must pick one as authoritative for the import (recommend `Vendor.parent_vendor_id`, since it's the field BR-012's rules are written against) and explicitly document that `ContractorRelationship` is not migrated.
- `backend/app/routes/vendor_category_mapping_v2.py` (`TaskVendorCategoryMapping`) — despite the `_v2` naming, this is a **legacy-schema** table mapping template-task categories to vendor categories; U2's new `vendor_capabilities` model should treat this as a candidate data source to import from (or explicitly note it's superseded), not build a parallel, disconnected capability concept.
- `backend/app/services/history.py` (`record_task_assignment`) — legacy vendor *task* assignment-history pattern; conceptual analog for `task_vendor_assignments`/`vendor_acknowledgements`, not directly reusable (old schema, assigns to `ExecutionTask` not the new `tasks` table).
- Phase 1 plan's `backend/app/services/audit.py` (consolidated audit helper) and `backend/app/execution_models.py` — this plan's new services and models follow the same conventions established there.
- Phase 1 plan's `file_objects`/`task_evidence` pattern (U3) — `vendor_activity_evidence` reuses `file_objects` with its own link table, per `docs/v2/02_V2_DATA_MODEL_SPECIFICATION.md` §5 ("separate link tables preserve real foreign keys; a polymorphic entity_type/entity_id reference is prohibited").

### Institutional Learnings

- None in `docs/solutions/` yet (confirmed absent during Phase 1 planning). Recommend capturing the outbox-pattern and vendor-import learnings from this plan via `/ce-compound` once implemented, since outbox/idempotency is new infrastructure the rest of Release 1 will depend on.

---

## Key Technical Decisions

- **Vendor import is one-time and validated, not a live sync**: per BR-019's migration boundary ("Vendors/sub-vendors: Import after parent/status validation"), this plan treats the legacy `Vendor` table as a one-time data source, not an ongoing dual-write system. Avoids building and maintaining a sync layer between two schemas indefinitely.
- **Outbox pattern, not direct send-on-mutation**: per data-model spec §1 ("all external communication is driven by an outbox event") and §9, every mutation writes an `outbox_events` row in the same DB transaction; a separate dispatch process reads the outbox and attempts delivery. This decouples domain-mutation correctness from WhatsApp provider availability — a provider outage never blocks a task status change.
- **Provider adapter interface, sandboxed for this plan**: `message_deliveries.provider` is a column, not a hardcoded assumption, so the actual WhatsApp Business API client can be swapped/deferred without reworking the outbox/delivery-tracking schema. This plan implements the adapter interface and can be exercised against a mock/sandbox provider for testing; wiring a real Meta/WABA client is a follow-up once Product/Ops external approval lands.
- **Inbound matching is phone-number-based against confirmed identities only**: employee commands map to `phone_e164` on `user_profiles`, vendor replies map to `phone_e164`/`whatsapp_e164` on `vendor_contacts` — an unmatched sender is logged to `inbound_messages` for review, never assumed to be a valid identity (BR-015's "vendor replies cannot invoke employee-only actions" is enforced by this identity-type separation, not by trusting message content).

---

## Open Questions

### Resolved During Planning

- Whether to build a live vendor sync or one-time import: resolved — one-time import (see Key Technical Decisions).
- Whether WhatsApp sending is in scope: resolved — no, infrastructure only; live sending is externally gated.

### Deferred to Implementation

- Exact dispatch mechanism for the outbox (polling worker vs. Postgres `LISTEN/NOTIFY` vs. a scheduled job) — any is architecturally valid per the spec; the choice affects operational complexity but not the schema this plan defines. Default to a simple polling worker unless implementation finds a strong reason otherwise, consistent with Phase 1's "no new infrastructure unless needed" bias.
- Whether the one-time vendor import runs as a management command, an Admin-triggered UI action, or a manual migration script — depends on how many vendors exist in the legacy system at cutover time, not knowable from this planning pass.

---

## Implementation Units

- U1. **V2 vendor tables and one-time legacy import**

**Goal:** Create the new `siteops_v2` vendor/capability tables and import validated legacy vendor data into them per BR-019.

**Requirements:** R1

**Dependencies:** None (independent of Phase 1)

**Files:**
- Create: `supabase/migrations/<timestamp>_v2_vendors.sql` (`vendors`, `capability_categories`, `vendor_capabilities`, `vendor_contacts`)
- Create: `backend/app/vendor_models.py` (`V2_SCHEMA`-scoped SQLAlchemy models — naming convention: prefix V2 model classes distinctly from their legacy namesakes, e.g. `V2VendorContact`/`V2ProjectVendor` mirroring Phase 1's `V2Project`/`V2ProjectTask` convention, since `app.models.VendorContact` and `app.models.ProjectVendor` already exist in the legacy schema and an unprefixed name would be a Python-level naming collision even though the DB schema-qualification avoids a table collision)
- Create: `backend/app/services/vendor_import.py` (`VendorImportService.import_from_legacy(dry_run=True)`)
- Test: `backend/tests/test_vendor_import_v2.py`

**Approach:**
- Import validates parent/status consistency (sub-vendor requires an active main-vendor parent already imported) before writing, per BR-012.
- `dry_run` mode reports what would be imported/rejected without writing, so an Admin can review before committing — mirrors the caution BR-019 asks for ("explicit, project-by-project validation").
- Only one active primary contact per vendor is enforced at write time (spec §8).
- `Vendor.parent_vendor_id` is the authoritative source for sub-vendor relationships; `ContractorRelationship` (a separate legacy representation of main/sub relationships) is explicitly **not** migrated — if it disagrees with `parent_vendor_id` for a given vendor, the import flags it for manual review rather than silently picking one.
- Vendors in legacy `engagement_type = 'migration_pending'` state are excluded from the import by default (reported in `dry_run` output as "requires resolution before import"), since their parent assignment is unresolved by definition; only `main_vendor`/`sub_vendor` (fully resolved) vendors are imported automatically.

**Test scenarios:**
- Happy path: importing a main vendor and its sub-vendor creates both V2 rows with the parent relationship preserved.
- Edge case: a sub-vendor whose legacy parent is inactive/missing is rejected (or flagged) rather than silently imported.
- Edge case: a vendor with two primary contacts in the legacy data is rejected or resolved to one, not silently duplicated.
- Edge case: a vendor in `migration_pending` state is excluded and reported, not silently imported or silently dropped.
- Edge case: a vendor whose `ContractorRelationship` row disagrees with its `parent_vendor_id` is flagged for manual review, not auto-resolved.
- Error path: re-running the import against already-imported vendors does not create duplicates (idempotent by legacy vendor ID).

**Verification:**
- Every V2 vendor row traces back to a validated legacy vendor via a stable external-ID reference; no orphaned sub-vendors exist post-import.

---

- U2. **Project-vendor mapping and task delegation**

**Goal:** Let a PM map a vendor to a project and delegate a task to a mapped vendor, without altering Supervisor accountability.

**Requirements:** R2, R3

**Dependencies:** U1, Phase 1 U1 (`tasks` table)

**Files:**
- Create: `supabase/migrations/<timestamp>_v2_project_vendors_task_assignments.sql` (`project_vendors`, `task_vendor_assignments`)
- Modify: `backend/app/vendor_models.py`
- Create: `backend/app/services/project_vendor.py`, `backend/app/services/task_vendor_assignment.py`
- Create: `backend/app/routes/project_vendors_v2.py` (`POST /api/v2/projects/{id}/vendors`, `POST /api/v2/projects/{id}/tasks/{task_id}/vendor-assignment`)
- Create: `frontend/src/api/vendorAssignmentApi.js` (flat function-per-route client for `project_vendors_v2.py`, following `projectsApi.js`'s pattern: `mapVendor(projectId, payload)`, `delegateTask(projectId, taskId, payload)`)
- Create: `frontend/src/features/projects/components/ProjectVendorPanel.jsx` (map an active vendor — and, when applicable, its already-mapped parent — to the project; list current mappings)
- Create: `frontend/src/features/execution/components/TaskVendorDelegationForm.jsx` (delegate a mapped vendor to a task; rendered inside Phase 1 U2's `TaskExecutionBoard` task detail)
- Modify: `frontend/src/features/projects/components/ProjectDetailModal.jsx` (add a "Vendors" tab to the existing `detailTabs` array, alongside `team`/`activity`, rendering `ProjectVendorPanel`)
- Test: `backend/tests/test_project_vendor_mapping_v2.py`, `backend/tests/test_task_vendor_assignment_v2.py`

**Approach:**
- `project_vendors` requires an active vendor; a sub-vendor mapping additionally requires its parent's active mapping to the same project (BR-012).
- `task_vendor_assignments` checks vendor capability against the task's `capability_category_id` at assignment time (spec §8 "vendor capability must match task classification"); status starts `pending_ack`.
- Creating a vendor task assignment never writes to any accountability-resolution path from Phase 1 — the Supervisor query (Phase 1 U6) is unaffected by this table's existence (BR-013).
- `ProjectVendorPanel` follows `ProjectDetailModal.jsx`'s existing tab-array pattern (`detailTabs`, pill-nav header) for adding "Vendors" as a new tab, the same shape `template-review`/`dependencies` already use. Vendor selection reuses the picker/lookup approach from `frontend/src/features/communication/CommunicationHubPage.jsx` (the live vendor-data screen) as a pattern reference, not `frontend/src/features/vendors/VendorsPage.jsx`, which is orphaned dead code disconnected from any live tab.

**Test scenarios:**
- Happy path: PM maps an active vendor to a project, then assigns a mapped vendor to a matching-capability task.
- Edge case: assigning a sub-vendor whose parent has no active mapping to this project is rejected.
- Edge case: assigning a vendor whose capability doesn't match the task's category is rejected.
- Error path: an inactive/blocked vendor cannot receive a new mapping or assignment.
- Integration: after a vendor task assignment, the task's accountable Supervisor (per Phase 1's derived-accountability query) is unchanged.
- Frontend: `ProjectVendorPanel` surfaces the same 422 the backend returns when a sub-vendor's parent has no active project mapping, rather than a generic error; `TaskVendorDelegationForm` only lists vendors already mapped to the project.

**Verification:**
- No code path lets a vendor assignment satisfy Phase 1's dependency-blocking "predecessor satisfied" condition on its own — only Supervisor verification/PM approval (Phase 1 U4) does, regardless of vendor delegation.

---

- U3. **Vendor acknowledgement and activity/incident capture**

**Goal:** Capture vendor acknowledgement of assignments and vendor-attributable activity (presence, delay, rework, incident) with evidence.

**Requirements:** R4, R5

**Dependencies:** U2

**Files:**
- Create: `supabase/migrations/<timestamp>_v2_vendor_acknowledgements_activity.sql` (`vendor_acknowledgements`, `vendor_activity_events`, `vendor_activity_evidence`)
- Modify: `backend/app/vendor_models.py`
- Create: `backend/app/services/vendor_acknowledgement.py`, `backend/app/services/vendor_activity.py`
- Modify: `backend/app/routes/project_vendors_v2.py` (`POST /{assignment_id}/acknowledge`, `POST /{assignment_id}/activity`)
- Modify: `frontend/src/api/vendorAssignmentApi.js` (add `logAcknowledgement`, `logActivity`)
- Create: `frontend/src/features/execution/components/VendorAcknowledgementForm.jsx` (PM records `accepted`/`declined`/`clarification_requested` on behalf of the vendor — the portal channel this unit's own test scenarios assume — rendered alongside U2's `TaskVendorDelegationForm`)
- Create: `frontend/src/features/execution/components/VendorActivityForm.jsx` (log presence/delay/rework/incident with an optional evidence file)
- Test: `backend/tests/test_vendor_acknowledgement_v2.py`, `backend/tests/test_vendor_activity_v2.py`

**Approach:**
- Acknowledgement responses are `accepted`, `declined`, `clarification_requested` (matching R4 exactly) — recorded regardless of channel (portal now, WhatsApp once U5/U6 land), so the schema doesn't need to change when the channel is added.
- Activity events reuse Phase 1's `file_objects` table for evidence via a dedicated `vendor_activity_evidence` link table (not a polymorphic reference), matching the spec's explicit prohibition.
- No endpoint in this unit allows a vendor identity to change task/verification/approval state — only acknowledgement and activity logging (BR-013).
- `VendorActivityForm`'s optional evidence upload reuses Phase 1 U3's file-input pattern (mirroring the existing `<input type="file">` in `frontend/src/features/execution/components/ExecutionModals.jsx` plus `frontend/src/api/client.js`'s `FormData`-aware request handling) rather than a third, independent upload implementation.

**Test scenarios:**
- Happy path: a PM logs an acknowledgement response on behalf of a vendor (portal channel); assignment status updates accordingly (`accepted`/`declined`/`clarification_requested`, all three exercised).
- Happy path: logging a delay-type activity event with `responsibility_decision` and evidence creates the event and evidence link.
- Edge case: an incident logged without evidence is still accepted (evidence is optional, not required, per spec).
- Error path: no endpoint in this unit exposes a vendor-identity action that mutates task lifecycle state — verify by exhaustive route inspection, not just a single negative test.
- Frontend: `VendorAcknowledgementForm` offers exactly the three response types and reflects the updated status immediately after submit; `VendorActivityForm`'s evidence field is optional, matching the backend.

**Verification:**
- Vendor acknowledgement/activity data is fully queryable per task/project without any write path existing from a vendor identity into task lifecycle, verification, or approval state.

---

- U4. **Outbox event infrastructure and mutation hooks**

**Goal:** Build the durable outbox pattern and wire it into every BR-015-mandated mutation point established in Phase 1 and this plan's U2/U3.

**Requirements:** R6

**Dependencies:** Phase 1 (all units — this is where their mutation points get instrumented), U2, U3

**Files:**
- Create: `supabase/migrations/<timestamp>_v2_outbox_events.sql` (`outbox_events`)
- Create: `backend/app/services/outbox.py` (`OutboxService.emit(event_type, aggregate_type, aggregate_id, payload, idempotency_key)`, called within the same transaction as the domain mutation)
- Modify: Phase 1's `backend/app/services/task_lifecycle.py`, `task_verification.py`, `task_approval.py`, `task_blocker.py`, `task_delay.py`, `task_support_assignment.py`, `project_role_change.py` (each calls `OutboxService.emit` for its BR-015-mandated event type)
- Modify: this plan's `task_vendor_assignment.py` (emits vendor-assignment event)
- Test: `backend/tests/test_outbox_emission_v2.py` (parametrized across every mutation type in BR-015's mandatory list)

**Approach:**
- `OutboxService.emit` is called inside the caller's existing transaction, never in a separate commit — "domain mutation and outbox insert occur in the same database transaction" is a stated modelling principle (spec §1), not optional.
- `idempotency_key` is deterministically derived from `(aggregate_type, aggregate_id, event_type, target_status_or_decision)` — e.g. for a status transition the discriminator is the target lifecycle status being transitioned to, for a verification/approval it's the decision value (`verified`/`rejected`/`approved`), for a blocker/delay it's the specific record's own UUID (already unique per occurrence). This guarantees retrying the *same* logical mutation call produces the same key, while two *different* mutations on the same aggregate (e.g. `in_progress` then later `submitted`) produce different keys and both get recorded.
- This unit does not dispatch anything — it only guarantees every mandatory event lands in `outbox_events`. Dispatch is U5.

**Test scenarios:**
- Happy path: each of Phase 1's mutation services (status transition, verification, approval, blocker, delay, support assignment, role change) and this plan's vendor assignment produces exactly one `outbox_events` row with the correct `event_type`.
- Edge case: calling the same mutation twice with the same idempotency key does not create a duplicate outbox row.
- Error path: if the outbox insert fails, the domain mutation itself rolls back (same-transaction guarantee) rather than silently succeeding without an event.
- Integration: a full request (e.g., Phase 1's task verification endpoint) produces both the domain state change and the outbox row atomically — verified by inspecting both tables after one API call, not just the service function in isolation.

**Verification:**
- Every event type in BR-015's mandatory list has at least one exercised code path proving it reaches `outbox_events`.

---

- U5. **Message delivery tracking and provider adapter**

**Goal:** Build the delivery-tracking schema and a provider-agnostic adapter interface that reads the outbox and attempts delivery, exercisable against a sandbox provider.

**Requirements:** R7

**Dependencies:** U4

**Files:**
- Create: `supabase/migrations/<timestamp>_v2_message_deliveries.sql` (`message_deliveries`)
- Create: `backend/app/services/message_dispatch.py` (`MessageDispatchService.process_pending()`, `WhatsAppProviderAdapter` interface + a `SandboxProviderAdapter` implementation for testing)
- Create: `backend/app/schemas/message_delivery.py`
- Test: `backend/tests/test_message_delivery_dispatch_v2.py`

**Approach:**
- Recipients are derived from the event's `aggregate_type`/`aggregate_id` plus current approved assignments (BR-015's "required recipients are derived from the event and current approved assignments") — not hardcoded per event type, so recipient logic doesn't need to be duplicated per message kind. The recipient-resolution query is scoped to project-membership/assignment roles only (PM, Supervisor, Internal Employee, vendor contact) — `super_admin` is structurally never a queried role in this resolution path, so it cannot appear as a recipient by construction, not by a separate filter that could be forgotten.
- `provider_message_id` and the `(event, recipient, template)` key are both unique, preventing duplicate delivery on retry (spec §9).
- The `SandboxProviderAdapter` simulates provider responses (accepted/rejected/delivered) for test and staging use; swapping in a real Meta/WABA client later is a configuration change to which adapter is wired, not a schema change.
- The provider access token (and, for U6, the inbound webhook verification secret) is stored via the existing backend secrets/environment-variable mechanism (`backend/app/config.py`'s settings pattern), scoped per environment (sandbox vs. staging vs. future production) — never hardcoded or committed, consistent with how other credentials in this codebase are handled.

**Test scenarios:**
- Happy path: a pending outbox event produces one `message_deliveries` row per required recipient, dispatched through the sandbox adapter.
- Happy path: a delivery status webhook/callback updates the row's status through `queued -> sent -> delivered`.
- Edge case: retrying a failed delivery increments `attempt_count` and does not create a second `message_deliveries` row for the same event/recipient/template.
- Error path: a provider failure sets `status = failed` with `failure_code`/`failure_reason` populated, without blocking other recipients' deliveries for the same event.
- Edge case: Super Admin never appears as a recipient for routine operational events (BR-015).

**Verification:**
- The dispatch service can run end-to-end against the sandbox adapter with no code change required to swap in a real provider later — only adapter configuration.

---

- U6. **Inbound message matching**

**Goal:** Receive inbound WhatsApp replies, match them to an authenticated identity, and translate approved vendor acknowledgements into the same records a portal action would produce.

**Requirements:** R8, R9

**Dependencies:** U3, U5

**Files:**
- Create: `supabase/migrations/<timestamp>_v2_inbound_messages.sql` (`inbound_messages`)
- Create: `backend/app/services/inbound_message.py`
- Create: `backend/app/routes/whatsapp_webhook_v2.py` (`POST /api/v2/whatsapp/inbound` — provider webhook receiver)
- Test: `backend/tests/test_inbound_message_matching_v2.py`

**Approach:**
- **Every inbound request is signature-verified before any phone-matching logic runs.** The webhook route validates the provider's request signature (e.g. Meta's `X-Hub-Signature-256` HMAC against the shared app secret, stored per U5's secrets-management approach) and rejects unsigned/invalid requests with no further processing. This is a hard gate, not optional hardening — without it, phone-number-based matching alone means anyone who knows or guesses a vendor's or employee's phone number could forge a request and trigger real state mutations (task status changes, vendor acknowledgements) with a fully legitimate-looking audit trail, since R9 requires matched replies to produce the exact same effect a portal action would.
- After signature verification, matching is phone-number-based: `sender_phone_e164` against `user_profiles.phone_e164` (employee) or `vendor_contacts.phone_e164`/`whatsapp_e164` (vendor). Exactly one identity match is required to proceed; zero matches or more than one simultaneous match is logged with `processing_status = unmatched` and never mutates state — this plan does not implement a "most recently active identity wins" heuristic for genuinely ambiguous matches, since that heuristic is itself spoofable by a reused phone number and doesn't reliably surface as "ambiguous" (see phone-reuse note below).
- Phone-number **unbinding is part of the offboarding/contact-removal flow**, not just an inbound-matching heuristic: when an employee is deactivated or a vendor contact is removed/replaced, their `phone_e164`/`whatsapp_e164` field is cleared as part of that action (in the existing user-deactivation and vendor-contact-removal code paths, not a new mechanism). This is the primary control against a reassigned phone number inheriting a former identity's command authority; without it, a "single match" on a recycled number is never even flagged as ambiguous by phone-matching alone.
- A matched vendor-contact reply mapped to an "accept/decline/clarify" structured command calls U3's `VendorAcknowledgementService` — same code path and same resulting audit event a portal-logged acknowledgement would produce (R9).
- A matched employee reply mapped to an approved command (e.g., a status update) calls the same Phase 1 service the portal UI calls — this unit is a new *entry point*, not a new *business rule*.

**Test scenarios:**
- Happy path: a vendor-contact phone number sending an approved "accept" command produces the identical `vendor_acknowledgements` row and audit event a portal acknowledgement would.
- Happy path: an employee phone number sending an approved status-update command produces the identical outcome the portal endpoint would (same service call).
- Error path: a request with a missing or invalid provider signature is rejected before any phone-matching or state mutation occurs, regardless of how well-formed its payload is.
- Edge case: a message from an unrecognized phone number is retained in `inbound_messages` with `processing_status = unmatched` and mutates nothing.
- Edge case: a phone number matching more than one active identity simultaneously is logged as `unmatched` for manual review, not resolved automatically.
- Edge case: a phone number previously bound to an offboarded employee/removed vendor contact (now unbound) produces zero matches, not a stale match.
- Error path: a vendor-contact identity attempting an employee-only command (e.g., "approve") is rejected — vendor replies cannot invoke employee-only actions (BR-015).
- Error path: duplicate inbound webhook delivery (same `provider_message_id`) is processed once, not twice.

**Verification:**
- No request reaches phone-matching or service-call logic without passing signature verification first.
- Every state-mutating action reachable via WhatsApp reply is reachable through the exact same service call a portal action uses — no parallel, WhatsApp-only business logic exists anywhere in this unit.

---

## System-Wide Impact

- **Interaction graph:** U4 instruments every Phase 1 mutation service plus this plan's U2/U3 — it is the widest-reaching unit in this plan, touching more existing files than it creates new ones.
- **Error propagation:** Outbox insert failure rolls back the domain mutation (same transaction); delivery failure at U5 never rolls back anything upstream — delivery is fire-and-forget from the domain's perspective, tracked but not blocking.
- **State lifecycle risks:** Retry/idempotency is the primary risk surface across U4–U6 (duplicate outbox rows, duplicate deliveries, duplicate inbound processing) — each unit's test scenarios specifically target duplicate-call safety, not just the happy path.
- **API surface parity:** U6's WhatsApp entry points are explicitly required to reuse Phase 1's existing services rather than reimplementing business logic, so there is no parity gap to introduce — verified by U6's "same code path" verification criterion. U2/U3's portal-facing endpoints (vendor mapping, task delegation, acknowledgement, activity) now ship with the frontend component and API-client function that call them, so this plan's only human-facing surface (the internal PM UI, per the Scope Boundaries note above) is exercisable without waiting on WhatsApp; U4–U6 remain backend/infrastructure-only by design (no natural end-user screen — see Scope Boundaries).
- **Integration coverage:** The riskiest cross-unit path is U4 → U5 → U6 → (back into Phase 1 services) — an inbound acknowledgement should be traceable end-to-end from webhook receipt to the same audit trail a portal action produces; this needs one explicit end-to-end integration test beyond the per-unit tests.
- **Unchanged invariants:** Phase 1's task lifecycle, verification, and approval business rules are not modified by this plan — U4 only adds an outbox emission call alongside their existing logic; U6 only adds a new entry point into the same services.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| WhatsApp live-sending timeline is entirely outside engineering's control (Meta/WABA approval, template approval) | This plan explicitly builds infrastructure only and is fully testable via the sandbox adapter without waiting on external approval; going live is a configuration change once approval lands |
| Legacy vendor import (U1) could import inconsistent or stale data if the legacy module is still being actively edited during cutover | `dry_run` mode lets Admin review before committing; recommend freezing legacy vendor edits during the actual import window (an operational note, not an engineering safeguard) |
| Outbox instrumentation (U4) touches nearly every Phase 1 service file — high blast radius for a single unit | Each Phase 1 service gets one additive `OutboxService.emit` call, not a rewrite; U4's tests re-verify each mutation's original behavior is unchanged in addition to checking the new outbox row |
| Duplicate message delivery or duplicate inbound processing under retry/at-least-once delivery semantics | Idempotency keys and unique constraints are load-bearing requirements (R7, R8), not optional hardening — explicitly tested in U5/U6 |
| U6's phone-based identity matching could misroute a message if a phone number is reused across an old and new identity (e.g., employee offboarded, number reassigned) | Phone unbinding is part of the offboarding/contact-removal flow (see U6 Approach); genuinely ambiguous matches are logged for manual review, never auto-resolved |
| An unauthenticated actor could forge inbound webhook payloads to trigger real state mutations, since phone-number matching alone is not authentication | U6 requires provider signature verification (e.g. HMAC) as a hard gate before any phone-matching or mutation logic runs — not deferred, not optional |
| Public inbound webhook endpoint has no rate limiting against volumetric abuse (flooding `inbound_messages` or matching-lookup load) | Accepted as defense-in-depth follow-up once signature verification (the primary control) is in place; not blocking for this plan |
| `inbound_messages`/`message_deliveries` and phone-number fields store PII (phone numbers, message content) with no stated retention/deletion policy | Deferred — evidence/message retention policy should be defined before production rollout, tracked as follow-up work alongside Phase 1's equivalent evidence-retention gap |

---

## Documentation / Operational Notes

- Coordinate with Product/Ops on Meta/WABA business approval and template wording approval in parallel with this plan's engineering work — per the origin brainstorm doc, this has its own external lead time and should not wait for U1–U4 to finish before starting.
- Update `docs/RELEASE_1_IMPLEMENTATION_AUDIT.md`'s "Vendors" and "WhatsApp Notifications and Reassignment Alerts" sections once this plan lands.

---

## Sources & References

- **Origin document:** [docs/brainstorms/release-1-completion-requirements.md](docs/brainstorms/release-1-completion-requirements.md)
- **Depends on plan:** [docs/plans/2026-08-02-001-feat-task-execution-engine-plan.md](docs/plans/2026-08-02-001-feat-task-execution-engine-plan.md)
- Architecture baseline: `docs/v2/02_V2_DATA_MODEL_SPECIFICATION.md` (§8–§9), `docs/v2/01_BUSINESS_RULES_DECISION_RECORD.md` (BR-012 through BR-015, BR-019)
- Existing gap analysis: `docs/RELEASE_1_IMPLEMENTATION_AUDIT.md` ("Vendors," "WhatsApp Notifications and Reassignment Alerts" sections)
- Pattern reference: `backend/app/routes/vendors.py`, `backend/app/services/history.py`
