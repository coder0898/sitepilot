# Workved SiteOps V2 - Supabase Auth and Database Architecture Decision

**Version:** 0.1  
**Status:** Accepted for Release 1 internal development and testing  
**Decision:** Use Supabase Auth and Supabase PostgreSQL only; retain FastAPI as the business backend

## 1. Selected architecture

```text
React + Tailwind
      | Supabase Auth session
      | Bearer JWT
      v
FastAPI business API
      | validated JWT + centralized authorization
      v
Supabase PostgreSQL
```

- React uses `supabase-js` only for authentication/session operations.
- React sends the Supabase access token to FastAPI.
- FastAPI validates the JWT and enforces roles, project scope and workflow transitions.
- FastAPI performs critical project, task, approval, vendor and audit mutations.
- Direct browser mutation of critical workflow tables is prohibited.

## 2. Environment topology

| Environment | Auth and PostgreSQL | Purpose |
|---|---|---|
| Local | Supabase CLI/Docker local stack | Daily development and destructive test resets |
| Internal testing/staging | Dedicated hosted Supabase project | Shared acceptance and migration testing |
| Production | Separate hosted Supabase project | Created only after release hardening |

Local development must not use the staging database for routine work.

## 3. Authentication and authorization

- `auth.users` is the credential and session authority.
- `public.user_profiles` and employee tables store SiteOps business identity.
- Fixed system roles are Super Admin, Admin, Project Manager, Site Supervisor and Internal Employee.
- A high-level role may be included in a Supabase custom JWT claim.
- Project-specific authority is always checked from current database memberships, not trusted as a long-lived JWT claim.
- User invitations, deactivation and privileged Auth operations are executed by FastAPI through the Supabase Admin API.
- The Supabase service-role key is backend-only and must never appear in React, logs or source control.

## 4. Database access and RLS

- FastAPI remains the authoritative domain boundary.
- React uses Supabase Data APIs for no V2 workflow tables in Release 1; its direct Supabase use is authentication only.
- PostgreSQL constraints protect referential and lifecycle integrity.
- RLS is enabled deny-by-default as defense in depth; any future browser-readable exception requires a documented policy and test.
- Authorization policies must be tested per role and project membership.
- Backend service access bypassing RLS is limited to audited domain services.

## 5. Migration authority

- `supabase/migrations/*.sql` is the only V2 schema-migration history.
- Migrations include public tables, enums, foreign keys, checks, indexes, functions, triggers and RLS policies.
- Alembic remains legacy-only and must not create or modify V2 tables.
- The same committed migration sequence is applied to local, staging and production.
- Dashboard-made schema changes must be captured as reviewed migrations before use.

## 6. Explicitly excluded Supabase services

Release 1 does not adopt Supabase Storage, Realtime, Edge Functions, Queues or Cron by this decision.

- Evidence metadata remains provider-neutral in `file_objects`.
- Local/internal proof-file storage uses the backend-configured file adapter.
- A production object-storage decision is required before production evidence rollout.
- WhatsApp workers and webhooks remain backend services and are introduced in their planned phase.

## 7. Security acceptance requirements

- JWT issuer, audience, expiry and signature are validated by FastAPI.
- Role changes require token refresh and are verified against current database state for sensitive actions.
- Service-role and database credentials are stored only in environment/secret management.
- CORS uses explicit allowed origins.
- No plaintext passwords, development JWT fallback or returned password-reset tokens.
- RLS tests prove that users cannot access another project without membership.
- Audit events identify actor, source, project, action and correlation ID.

## 8. Development gate

Foundation implementation may begin when:

- The five-role matrix is approved.
- This architecture decision is accepted.
- Local and staging Supabase projects are isolated.
- Migration ownership is assigned.

Project/task workflow migrations additionally require the approved 45-day template, task-kind/Class A criteria and legacy migration boundary.

