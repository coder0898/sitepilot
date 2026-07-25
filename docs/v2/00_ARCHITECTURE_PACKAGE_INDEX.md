# Workved SiteOps V2 - Architecture Package Index

**Package version:** 0.1  
**Purpose:** Single entry point for the Release 1 rebuild decisions  
**Implementation state:** Foundation development may begin; project/task workflow awaits the content approvals listed below

## 1. Source documents

| Document | Purpose | Current state |
|---|---|---|
| `01_BUSINESS_RULES_DECISION_RECORD.md` | Deterministic Release 1 business rules and exclusions | Implementation baseline |
| `02_V2_DATA_MODEL_SPECIFICATION.md` | Logical entities, relationships, constraints and migration boundary | Architecture baseline; no executable migrations |
| `03_RELEASE_1_ROLE_PERMISSION_MATRIX.md` | Five-role authority, accountability and fallback permissions | Implementation baseline awaiting role-matrix sign-off |
| `04_SUPABASE_AUTH_DATABASE_ARCHITECTURE_DECISION.md` | Auth, database, environment, RLS and migration strategy | Accepted for internal development/testing |

The approved PRD remains the product authority. These documents define the agreed Release 1 interpretation and explicitly record deferred scope.

## 2. Confirmed Release 1 decisions

- Portal roles: Super Admin, Admin, Project Manager, Site Supervisor and Internal Employee.
- Management follows a separate product direction and is outside SiteOps Release 1.
- Vendors and sub-vendors are PM-managed business entities, not portal-login roles.
- Supervisor is accountable for site-execution work.
- PM is accountable for approval-gate decisions and vendor confirmation.
- Internal Employee is delegated support only.
- Task kinds are `work`, `approval_gate` and `milestone`.
- One dependency engine controls all blocking relationships.
- Essential external permissions are approval-gate tasks; a separate External Approval module is deferred to Release 2.
- Supabase Auth and Supabase PostgreSQL are used; FastAPI remains the business backend.
- Local, staging and future production Supabase projects are isolated.
- Supabase SQL migrations are the sole V2 migration history; Alembic is legacy-only.
- React uses Supabase directly for Auth only; critical data mutations go through FastAPI.

## 3. Safe foundation-development scope

Development may begin on:

1. Local Supabase CLI/Docker setup and isolated hosted staging project.
2. Supabase Auth integration and FastAPI JWT validation.
3. Fixed role codes, `user_profiles`, employee profiles and centralized permissions.
4. Secure user invitation/deactivation through backend-only Auth Admin APIs.
5. Supabase migration structure, deny-by-default RLS and database constraint conventions.
6. Audit-event and correlation-ID foundation.
7. Automated role and project-isolation tests.
8. Minimal React login/session and user-administration vertical slice.

## 4. Required before project/task workflow migrations

Product/Operations must provide or approve:

- Final five-role permission/fallback matrix.
- Complete, reviewed 45-day template content—not the recovered generic legacy seed.
- Classification criteria for `work`, `approval_gate`, `milestone`, `standard` and `class_a`.
- Dependency and approval-gate acceptance examples.
- Legacy migration boundary: validated master data to import and legacy execution data to archive.

## 5. Required before WhatsApp implementation

- Meta Business/WABA readiness and approved test numbers.
- Approved outbound template wording.
- Recipient matrix per domain event.
- Consent and phone-identity rules.
- Inbound command scope for employees and vendor contacts.
- Retry, duplicate-prevention and escalation acceptance criteria.

## 6. Required before production evidence rollout

Supabase Storage is not selected in Release 1's current platform decision. Before production proof uploads, approve a durable private object-storage provider, retention rules, signed-access strategy and backup/recovery process. Local/internal testing may use the backend file adapter but must not be treated as production durability.

## 7. Delivery rule

Every implementation item is delivered as a vertical slice:

```text
Migration and constraints
        -> domain service
        -> FastAPI contract
        -> automated tests
        -> minimal React UI
        -> role-based acceptance test
```

No dashboard-only database edits, duplicate migration systems or direct frontend workflow writes are permitted.
