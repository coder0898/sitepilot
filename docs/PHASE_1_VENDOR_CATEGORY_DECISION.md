# Phase 1 — Category and Vendor Data Decision

Status: implemented for staging migration review.

## Approved model

- Categories are typed as `material` or `service`.
- Categories support two levels: main category and subcategory.
- A main vendor has no parent.
- A sub-vendor must have exactly one active main vendor as its parent.
- Independent sub-vendors cannot be created or assigned.
- Tasks retain the legacy category text for compatibility and can also reference a structured category and subcategory.
- Task and vendor status changes are stored in append-only history tables.

## Existing subcontractor migration

1. A legacy exclusive subcontractor with exactly one distinct parent is converted automatically to `sub_vendor`.
2. Duplicate rows for that same parent are reduced to one relationship before the uniqueness constraint is applied.
3. An independent subcontractor, or an exclusive subcontractor with no unambiguous parent, becomes `migration_pending` with `parent_required`.
4. Every available legacy parent candidate is preserved for audit; SiteOps never guesses the parent.
5. Pending records remain visible in Communication Hub but cannot receive project or task assignments.
6. An Admin or Project Manager resolves each pending record using **Resolve parent mapping**.
7. Resolution sets the approved parent, converts the record to `sub_vendor`, and records who resolved it and when.

## Assignment rules

- Only active, migration-ready main vendors can be mapped to projects or assigned to tasks.
- Only active, migration-ready sub-vendors belonging to the selected main vendor can be assigned.
- Sub-vendors inherit project visibility from their parent vendor.
- Inactive or on-hold vendors are blocked from new assignments.

## Deployment acceptance checks

- Take a database backup before applying migration `0014_vendor_category_phase1`.
- Confirm automatically migrated sub-vendors still appear under the correct parent.
- Confirm every independent or ambiguous legacy record appears under **Resolve parent mapping**.
- Resolve one record and verify it disappears from the pending list and appears under its chosen parent.
- Confirm a pending record cannot be assigned to a task.
- Create Material and Service main categories and one subcategory under each.
- Confirm task assignment lists never show unrelated or inactive vendors.
- Confirm downgrade is tested on a restored staging database, not on production data.