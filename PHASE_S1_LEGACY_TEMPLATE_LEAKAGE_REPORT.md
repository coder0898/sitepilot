# Prompt S1 — Legacy Template Leakage Audit

## Risks found

1. `GET /api/v2/execution` loaded and serialized every legacy execution template for every authenticated role, including Supervisor and Internal Employee.
2. Admin and Project Manager received archived template rows and template-management metadata that were not required for project creation.
3. The execution frontend stored whatever `templates` payload was returned, so unauthorized template metadata could remain in browser state even though template-management controls were hidden.
4. No regression test explicitly prohibited the legacy execution route from importing or querying governed V2 template models.

## Minimum fixes

- Added role-aware legacy template serialization in `backend/app/routes/execution_v2.py`.
- Super Admin retains existing legacy create/edit/archive/delete behavior.
- Admin and Project Manager receive active legacy templates only, with fields needed for project creation; management metadata is omitted.
- Supervisor and Internal Employee receive an empty template list.
- Added frontend response sanitization as defense in depth.
- Added backend and frontend regression tests.
- Added a source-level regression assertion that the legacy route does not import/query V2 template models or call the `/api/v2/templates` route family.

## Scope protection

- No migration or Alembic file changed.
- No legacy execution model or workflow was migrated or redesigned.
- No governed V2 template route, service, fixture, or schema was changed.
- Existing Super Admin legacy template management remains available.
- Admin/PM project creation continues to receive active legacy template choices.

## Remaining risks

- The legacy execution module still contains its own mutable legacy template system. This is intentionally retained for compatibility and is not the governed V2 template module.
- Full authenticated HTTP integration should be rerun in the deployment-like PostgreSQL environment.
- Browser/manual role-switch testing should confirm stale execution state is cleared when the authenticated user changes.
