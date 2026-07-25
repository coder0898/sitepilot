# Workved SiteOps V2 - Business Rules Decision Record

**Version:** 0.3  
**Status:** Implementation baseline; Management experience confirmed outside Release 1  
**Source of truth:** Approved Workved SiteOps PRD v1.1  
**Purpose:** Resolve MVP ambiguity before database design and implementation

## 1. Authority and change control

- The approved PRD is the product authority.
- This record interprets the PRD into implementable Release 1 rules.
- The existing portal is a legacy implementation reference, not a source of business rules.
- A rule in this record may change only through a numbered decision amendment approved by Product/Management.
- V2 database migrations and workflow implementation must not begin until this record and its role-permission matrix are signed off.

## 2. Deterministic product decisions

### BR-001 - Template model

- Release 1 has one approved **45-day master execution template** at a time.
- Templates are versioned; only one version may be `approved_active`.
- Draft versions may be edited but cannot create projects.
- Activation of a new version archives the previous active version.
- Existing projects retain an immutable snapshot of the template version used at creation.
- The recovered legacy 45-day seed is reference material only and is not an approved baseline.

### BR-002 - Project creation and activation

- Admin creates a project from the currently approved 45-day template.
- A Project Manager and Site Supervisor are mandatory before activation.
- PM reviews generated tasks, support assignments, vendors, dependencies and approval gates.
- A project may remain `draft` while setup is incomplete.
- Activation requires exactly one active PM and one active Site Supervisor; the Supervisor is accountable for site-execution work and the PM is accountable for approval-gate decisions.
- Activation locks the baseline. Later changes create revisions and audit events; they never overwrite baseline history.

### BR-003 - Roles

Release 1 uses these portal roles, in governance order:

- `super_admin`: technical administration, security, integrations, logs and recovery; no routine operational approval.
- `admin`: user administration, project setup, master data, template governance and PM fallback.
- `project_manager`: project control, vendor/sub-vendor management, vendor confirmation, external-approval accountability and PM approval decisions.
- `site_supervisor`: accountable owner of site-execution tasks, daily execution control, verification and support allocation.
- `internal_employee`: delegated execution or approval-follow-up support, progress updates and evidence submission; never the accountable owner of a site task or approval gate.

Vendors and sub-vendors are business entities, not portal roles, and do not receive portal accounts in Release 1. PM creates and manages them; their approved contacts interact through structured WhatsApp flows.

The approved PRD includes a `management` role, but Management will follow a separate product direction and is confirmed outside SiteOps Release 1. It is not implemented, aliased to Admin or included in this release's authorization model. Any future Management experience requires its own approved scope and architecture amendment.

### BR-004 - Site-task accountability

- Every active site-execution task is accountable to the project's active Site Supervisor.
- Internal Employees may be delegated support work but cannot replace Supervisor accountability.
- Vendor delegation does not transfer accountability away from the Supervisor.
- The accountable Supervisor is derived from the dated project-Supervisor membership history, not from an arbitrary task-owner dropdown.
- A task cannot enter `ready` or `in_progress` unless the project has an active Supervisor.

### BR-005 - Supporting employees

- A task may have zero or more supporting Internal Employees.
- Each support assignment has a responsibility description.
- The Supervisor assigns or replaces support employees and remains accountable for their work.
- Support employees may add permitted progress/evidence but cannot verify, approve or replace Supervisor accountability.
- Adding or removing support does not alter the project's Supervisor assignment.

### BR-006 - Employee availability

- Release 1 stores only operational availability: `available`, `unavailable` or `restricted`.
- An availability event requires start time, optional end time, reason and recorder.
- This is not leave, payroll, biometric or attendance management.
- Marking an employee unavailable evaluates their active project accountability, task-support assignments and approval-gate follow-up work.

### BR-007 - Role-specific reassignment

- Reassignment reasons include absence, unavailability, workload, operational requirement and correction.
- If a Supervisor is unavailable, the project PM replaces or temporarily assigns the Supervisor.
- If a PM is unavailable, Admin assigns the PM replacement or fallback.
- If a supporting Internal Employee is unavailable, the Supervisor replaces or ends that support assignment.
- Every change records project/task scope, previous assignee, replacement, reason, actor and effective time.
- Automatic skill-based or silent replacement is prohibited.
- Reassignment never promotes an Internal Employee or vendor into accountable Supervisor or PM authority.

### BR-008 - Task kinds, classes and approval path

- Every template task has a `task_kind`: `work`, `approval_gate` or `milestone`.
- `work` is actionable execution controlled by the Supervisor.
- `approval_gate` represents a required permission or decision, must be `class_a`, requires evidence and PM approval, and may block successors.
- `milestone` is a zero-duration schedule marker derived from completion of its required predecessor tasks.
- Every `work` task is classified as `standard` or `class_a`.
- For `work`, the Supervisor or delegated Internal Employee submits progress and evidence, and the Supervisor verifies or rejects it.
- Verified `standard` work completes after Supervisor verification.
- Verified `class_a` work requires PM approval before completion.
- For an `approval_gate`, the PM approves or rejects submitted evidence directly; Supervisor verification is not required.
- A rejected work task reopens under Supervisor accountability; a rejected approval gate reopens under PM accountability. Both require a correction reason.
- A `milestone` completes automatically when all required blocking predecessors satisfy their completion/approval conditions.
- A dependent task cannot start while any blocking predecessor remains unsatisfied.

### BR-009 - Task lifecycle

Canonical lifecycle states are:

`planned -> ready -> in_progress -> submitted -> verified -> completed`

Additional controlled transitions:

- `submitted -> rejected -> in_progress` for rejected work
- `verified -> approval_pending -> completed` for Class A work
- `submitted -> approval_pending -> completed` for approval gates
- `approval_pending -> rejected -> in_progress`
- `planned -> completed` for a system-derived milestone after all blocking predecessors are satisfied
- Any non-terminal state may move to `cancelled` only through an authorized override with reason.

`blocked`, `delayed`, `overdue` and `no_update` are separate conditions, not mutually exclusive lifecycle states.

### BR-010 - Schedule and exceptions

- Original planned dates belong to the locked baseline.
- A live date change creates a schedule-revision record containing old date, new date, reason, requester and approver.
- `overdue` is derived when the current due date has passed and the task is not complete.
- `blocked` requires blocker type, description, owner, start time and resolution.
- `delayed` requires responsibility category and impact reason.
- `no_update` is derived from a configurable update SLA.
- Carry-forward changes the live working date but preserves the baseline date.

### BR-011 - Dependencies and approval gates

- Release 1 has one dependency engine for work, approval gates and milestones.
- A blocking dependency prevents its successor from starting until the predecessor reaches its required completed/approved state.
- Essential landlord, society, client, building, permit and material approvals are represented as `approval_gate` tasks in the 45-day template.
- The active PM is accountable for approval-gate decisions; an Internal Employee may be delegated follow-up but cannot approve or close the gate.
- An approval gate records the approving party, due date, evidence requirement, decision and blocking dependencies.
- A separate External Approval module, owner table, follow-up workflow and dashboard are deferred to Release 2.

### BR-012 - Vendor and sub-vendor model

- A sub-vendor must have exactly one parent vendor.
- Independent sub-vendors are prohibited.
- Vendor capability categories are separate from internal task ownership.
- A project-vendor mapping is required before a vendor can receive a task assignment.
- A sub-vendor task assignment requires its parent vendor to be mapped to the project.
- Inactive or blocked vendors cannot receive new assignments.
- Existing assignments remain visible after inactivation for audit purposes.

### BR-013 - Vendor authority

- Vendors may acknowledge, accept, decline or clarify an assignment.
- Vendors cannot officially start, complete, verify, approve or close a task.
- The Site Supervisor remains accountable for the site task even when execution is delegated to a vendor.

### BR-014 - Vendor accountability in Release 1

Release 1 captures:

- Assignment acceptance/decline
- Basic site-presence confirmation, without biometric attendance
- Vendor-attributable delay
- Rework requests
- Incidents with evidence

Automated scoring, ranking and replacement recommendations remain outside Release 1.

### BR-015 - WhatsApp scope

- WhatsApp is the primary field communication channel, with the portal as operational fallback.
- Super Admin receives no routine operational WhatsApp messages.
- Admin, PM, Supervisor and Internal Employee receive only role-relevant messages; vendor contacts receive only messages for their confirmed assignments.
- Messages are created from durable domain events, never directly from UI code.
- Mandatory outbound events include project assignment, PM/Supervisor membership change, Internal Employee support assignment/change, vendor assignment, due tomorrow, due today, blocker/delay, evidence submitted, verification/rejection, approval-gate/Class A approval or rejection and approval-gate reminders.
- Required recipients are derived from the event and current approved assignments.
- Delivery requires idempotency, retry count, failure reason, status webhook handling and duplicate prevention.
- Vendor replies are limited to approved structured acknowledgements in Release 1.
- Employee WhatsApp update commands must map to authenticated portal-user phone numbers and produce the same audit events as portal updates.
- Vendor replies map to vendor-contact identities and cannot invoke employee-only completion, verification or approval actions.

### BR-016 - Reports and management visibility

- A daily report shows planned, completed, delayed, blocked, overdue and no-update work; pending verification/approval; approval gates at risk; and role/support changes required.
- A weekly report shows milestone progress, schedule movement, vendor concerns, ownership changes and management decisions required.
- Reports are generated from recorded system data and stored as versioned snapshots.
- Release 1 cross-project visibility is available to authorized Admin users. A separate Management experience remains deferred only if the documented scope deviation is approved.

### BR-017 - Auditability

- Assignment, reassignment, status, schedule, verification, approval, override, availability and communication events are append-only.
- Audit records include actor, action, entity, timestamp, correlation ID and relevant before/after values.
- Business history is not deleted when a user, vendor or project becomes inactive.
- Super Admin may inspect logs but may not rewrite business history.

### BR-018 - Deletion and retention

- Referenced users, employees, templates, categories, vendors, projects and tasks are archived/inactivated rather than hard-deleted.
- Unreferenced draft master data may be hard-deleted by an authorized role.
- Activated projects and their baseline/history cannot be hard-deleted through normal product workflows.

### BR-019 - Legacy data migration

- Migrate validated users, employee identities, vendors, sub-vendors, contacts and capability categories.
- Force secure password reset; do not migrate plain or test passwords.
- Do not migrate current three-day tasks as active V2 execution records.
- Preserve legacy projects/tasks in a read-only archive or export when required for reference.
- Migrate a legacy project only through an explicit, project-by-project validation procedure approved by Product and Operations.

## 3. Release 1 exclusions

- AI allocation or replacement
- Automatic skill-based assignment
- Native mobile application and offline mode
- Client or vendor portal
- GPS and biometric attendance
- Payroll and leave management
- AI delay prediction
- Full critical-path optimization
- Automatic vendor scoring or replacement
- Dedicated External Approval module, external-owner workflow and approval dashboard

## 4. Sign-off gate

Implementation may begin after Product/Management confirms:

- The numbered rules above

- The final role-permission matrix and accountability hierarchy
- The approved 45-day template content and version owner
- The Admin/PM/Supervisor role-specific replacement hierarchy
- Task-kind and Class A classification criteria
- WhatsApp templates, consent and recipients
- Legacy migration scope











