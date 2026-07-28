# Workved SiteOps V2 - Release 1 Role-Permission Matrix

**Version:** 0.2  
**Status:** Implementation baseline; Management experience confirmed outside Release 1  
**Depends on:** `01_BUSINESS_RULES_DECISION_RECORD.md`, `02_V2_DATA_MODEL_SPECIFICATION.md`

## 1. Identity boundary

Portal roles are implemented in this governance order:

1. `super_admin`
2. `admin`
3. `project_manager`
4. `site_supervisor`
5. `internal_employee`

Vendor and sub-vendor are not portal roles. They are PM-managed business entities whose approved contacts participate through structured WhatsApp messages.

The approved PRD's `management` role is not included in this Release 1 matrix. Management will follow a separate product direction and is confirmed outside SiteOps Release 1. It must not be silently mapped to Admin; a future Management experience requires a separately approved scope and architecture amendment.

## 2. Accountability hierarchy

| Area | Accountable role | Delegated/support role | Fallback/replacement authority |
|---|---|---|---|
| System security and integrations | Super Admin | None | Controlled recovery procedure |
| Project setup and activation | Admin | PM reviews setup | Super Admin technical recovery only |
| Project execution control | PM | Supervisor | Admin replaces unavailable PM |
| Site-execution tasks | Supervisor | Internal Employee; confirmed vendor execution | PM replaces unavailable Supervisor; Admin audited fallback |
| Approval-gate tasks | PM decision | Internal Employee follow-up | Admin replaces unavailable PM |
| Vendor/sub-vendor master | PM | Vendor contacts via WhatsApp | Admin audited recovery transfer |
| Task verification | Supervisor | None | Authorized PM/Admin fallback with audit |
| Class A approval | PM | None | Admin fallback with recorded reason |

## 3. Release 1 permission matrix

Legend: **Own** = permitted within accountable scope; **View** = read-only; **Fallback** = permitted only with a recorded reason and audit; **No** = prohibited.

| Capability | Super Admin | Admin | PM | Supervisor | Internal Employee |
|---|---:|---:|---:|---:|---:|
| Manage Super Admin accounts | Own | No | No | No | No |
| Create/deactivate Admin | Own | No | No | No | No |
| Create/deactivate PM, Supervisor, Internal Employee | View | Own | No | No | No |
| Configure security/integrations | Own | No | No | No | No |
| View technical logs | Own | View | No | No | No |
| Govern approved template versions | View | Own | View | View | No |
| Create draft project | View | Own | View | No | No |
| Assign/replace project PM | View | Own | No | No | No |
| Assign/replace project Supervisor | View | Fallback | Own | No | No |
| Activate project/baseline | View | Own | Recommend | No | No |
| Manage project schedule | View | Fallback | Own | Propose | No |
| Create/manage vendor and sub-vendor | View | Fallback | Own | View | No |
| Confirm project-vendor mapping | View | Fallback | Own | Recommend | No |
| Confirm category-matched task vendor | View | Fallback | Own | Recommend | No |
| Assign task support employee | View | Fallback | View | Own | No |
| Submit progress/evidence | View | Fallback | View | Own | Own when assigned support |
| Report blocker/delay | View | Fallback | Own | Own | Own when assigned support |
| Verify/reject submitted site work | View | Fallback | Fallback | Own | No |
| Approve/reject Class A work | View | Fallback | Own | No | No |
| Decide/manage approval-gate tasks | View | Fallback | Own | View | Follow-up only when assigned |
| View project audit history | View | Own | Own project | Own project | Own activity only |
| Receive operational WhatsApp | No | Role-relevant | Role-relevant | Role-relevant | Assignment-relevant |

## 4. Vendor WhatsApp authority

Vendor contacts may:

- Receive confirmed project/task assignment messages.
- Acknowledge, accept, decline or request clarification.
- Provide structured presence, delay or issue information when enabled.

Vendor contacts may not:

- Log in as a portal role in Release 1.
- Officially start, complete, verify, approve or close a task.
- Change task category, schedule, accountable Supervisor or PM.
- Assign themselves or another vendor to a project/task.

## 5. Backend implementation order

1. Identity, secure authentication, fixed role codes and centralized authorization policies.
2. User and employee-profile administration.
3. Template/version and category master data.
4. PM-managed vendor/sub-vendor/contact master data.
5. Project creation, PM/Supervisor membership, baseline generation and activation.
6. Supervisor task accountability and Internal Employee support assignment.
7. Category-matched vendor recommendation and PM confirmation.
8. Verification, Class A approval and dependency-controlled approval gates.
9. Durable event outbox, role-based WhatsApp recipients and provider integration.

Each item is delivered as a vertical slice: database constraints, domain service, API, automated tests, minimal frontend and role-based end-to-end acceptance test.

## 6. Approval gate

Product/Management must explicitly approve:


- Supervisor accountability for every site-execution task.
- PM accountability for every approval-gate decision.
- Internal Employee as support only.
- Vendor/sub-vendor as non-login WhatsApp participants.
- The fallback permissions marked above.

No V2 role or ownership migration should be generated until this gate is signed off.




