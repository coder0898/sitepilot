"""Phase 2 U1: one-time legacy vendor import into siteops_v2 (R1).

`VendorImportService.import_from_legacy` reads the legacy `vendors` /
`vendor_contacts` / `contractor_relationships` tables (app.models) and
writes validated rows into the new siteops_v2 vendor tables
(app.vendor_models).

This is explicitly a ONE-TIME, validated import, not a live sync: the
legacy module stays the system of record for its own schema, and this
import is the only bridge new (V2) project/task work uses to see vendor
data going forward. Re-running is safe - it is idempotent by
`V2Vendor.legacy_vendor_id`, so an admin can re-run after fixing flagged
legacy data without duplicating already-imported vendors, their
capability, or their contact rows.

Validation performed BEFORE any write (see plan Approach):
 - `engagement_type = 'migration_pending'` vendors are excluded from
   automatic import entirely; reported separately (`excluded_pending`) so
   an admin can resolve them in the legacy module first.
 - A `sub_vendor` requires an active, already-imported `main` parent,
   resolved via `Vendor.parent_vendor_id` - the sole authoritative source
   for this relationship (see below on why `ContractorRelationship` is not
   migrated). A missing, inactive, or not-yet-imported parent -> the
   sub-vendor is rejected, not silently imported.
 - `ContractorRelationship` is a separate legacy representation of
   parent/sub relationships that coexists with `Vendor.parent_vendor_id`.
   It is explicitly NOT migrated. If a `ContractorRelationship` row
   disagrees with `parent_vendor_id` for the same vendor, that vendor is
   flagged for manual review (`flagged_for_review`). This flag does NOT
   block or alter the import - parent_vendor_id remains authoritative -
   it only surfaces the disagreement so an admin can reconcile the legacy
   data by hand. It is never auto-resolved by silently picking a side.
 - More than one legacy `VendorContact` marked `is_primary=True` for a
   vendor is a rejected data-quality condition (`multiple_primary_contacts`),
   not auto-resolved to a single primary - consistent with the
   "flag/reject, don't guess" approach used for the ContractorRelationship
   case above.

`dry_run=True` (the default) computes and returns the full report with NO
database writes, so an Admin can review before committing anything.
`dry_run=False` performs the writes and commits.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ContractorRelationship, Vendor, VendorContact
from app.vendor_models import V2CapabilityCategory, V2Vendor, V2VendorCapability, V2VendorContact


@dataclass
class VendorImportReport:
    dry_run: bool
    imported: list[dict] = field(default_factory=list)
    already_imported: list[dict] = field(default_factory=list)
    excluded_pending: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    flagged_for_review: list[dict] = field(default_factory=list)

    @property
    def imported_count(self) -> int:
        return len(self.imported)


class VendorImportService:
    def __init__(self, db: Session):
        self.db = db

    def import_from_legacy(
        self, actor_id: uuid.UUID | None = None, dry_run: bool = True
    ) -> VendorImportReport:
        report = VendorImportReport(dry_run=dry_run)

        legacy_vendors = list(self.db.scalars(select(Vendor)).all())
        legacy_by_id: dict[uuid.UUID, Vendor] = {v.id: v for v in legacy_vendors}

        # Legacy's separate parent/sub representation - read-only here,
        # used only to detect disagreement with parent_vendor_id below.
        cr_parent_by_subcontractor: dict[uuid.UUID, uuid.UUID] = {
            cr.subcontractor_id: cr.main_contractor_id
            for cr in self.db.scalars(select(ContractorRelationship)).all()
        }

        contacts_by_vendor_id: dict[uuid.UUID, list[VendorContact]] = {}
        for contact in self.db.scalars(select(VendorContact)).all():
            contacts_by_vendor_id.setdefault(contact.vendor_id, []).append(contact)

        already_imported = list(
            self.db.scalars(select(V2Vendor).where(V2Vendor.legacy_vendor_id.is_not(None))).all()
        )
        # Legacy vendor ids already resolvable in V2 - either from a prior
        # run, or (below) from this run, so subsequent sub-vendors in this
        # same batch can validate against a main vendor imported earlier in
        # the batch. `v2_id_by_legacy_id` only ever holds *real* V2 ids
        # (only ever populated on an actual write), used for FK values.
        resolvable_legacy_ids: set[uuid.UUID] = {v.legacy_vendor_id for v in already_imported}
        v2_id_by_legacy_id: dict[uuid.UUID, uuid.UUID] = {v.legacy_vendor_id: v.id for v in already_imported}
        already_imported_by_legacy_id = {v.legacy_vendor_id: v for v in already_imported}

        category_by_name: dict[str, V2CapabilityCategory] = {
            c.name: c for c in self.db.scalars(select(V2CapabilityCategory)).all()
        }

        # Mains first so a sub-vendor's parent has already been resolved
        # (imported this run, or previously imported) by the time the
        # sub-vendor itself is evaluated.
        ordered_vendors = sorted(legacy_vendors, key=lambda v: 0 if v.engagement_type == "main" else 1)

        for vendor in ordered_vendors:
            # Data-quality signal on the legacy data itself - checked
            # regardless of whether this vendor is importable this run.
            cr_parent_id = cr_parent_by_subcontractor.get(vendor.id)
            if cr_parent_id is not None and cr_parent_id != vendor.parent_vendor_id:
                report.flagged_for_review.append({
                    "legacy_vendor_id": vendor.id,
                    "name": vendor.name,
                    "reason": "contractor_relationship_disagrees_with_parent_vendor_id",
                    "parent_vendor_id": vendor.parent_vendor_id,
                    "contractor_relationship_main_id": cr_parent_id,
                })

            if vendor.engagement_type == "migration_pending":
                report.excluded_pending.append({
                    "legacy_vendor_id": vendor.id,
                    "name": vendor.name,
                    "reason": "requires resolution before import",
                })
                continue

            if vendor.id in already_imported_by_legacy_id:
                existing = already_imported_by_legacy_id[vendor.id]
                report.already_imported.append({
                    "legacy_vendor_id": vendor.id,
                    "v2_vendor_id": existing.id,
                    "name": vendor.name,
                })
                continue

            resolved_parent_v2_id: uuid.UUID | None = None
            if vendor.engagement_type == "sub_vendor":
                parent = legacy_by_id.get(vendor.parent_vendor_id) if vendor.parent_vendor_id else None
                if parent is None or parent.status != "active":
                    report.rejected.append({
                        "legacy_vendor_id": vendor.id,
                        "name": vendor.name,
                        "reason": "parent_missing_or_inactive",
                    })
                    continue
                if parent.id not in resolvable_legacy_ids:
                    report.rejected.append({
                        "legacy_vendor_id": vendor.id,
                        "name": vendor.name,
                        "reason": "parent_not_imported",
                    })
                    continue
                resolved_parent_v2_id = v2_id_by_legacy_id.get(parent.id)

            primary_contacts = [c for c in contacts_by_vendor_id.get(vendor.id, []) if c.is_primary]
            if len(primary_contacts) > 1:
                report.rejected.append({
                    "legacy_vendor_id": vendor.id,
                    "name": vendor.name,
                    "reason": "multiple_primary_contacts",
                })
                continue

            v2_vendor_id: uuid.UUID | None = None
            if not dry_run:
                v2_vendor = V2Vendor(
                    legacy_vendor_id=vendor.id,
                    name=vendor.name,
                    contact_person=vendor.contact_person,
                    phone=vendor.phone,
                    whatsapp=vendor.whatsapp,
                    email=vendor.email,
                    address=vendor.address,
                    gst_number=vendor.gst_number,
                    notes=vendor.notes,
                    status=vendor.status,
                    engagement_type=vendor.engagement_type,
                    parent_vendor_id=resolved_parent_v2_id,
                    created_by=actor_id,
                )
                self.db.add(v2_vendor)
                self.db.flush()
                v2_vendor_id = v2_vendor.id
                v2_id_by_legacy_id[vendor.id] = v2_vendor_id

                category = category_by_name.get(vendor.category)
                if category is None:
                    category = V2CapabilityCategory(name=vendor.category)
                    self.db.add(category)
                    self.db.flush()
                    category_by_name[vendor.category] = category
                self.db.add(V2VendorCapability(vendor_id=v2_vendor_id, category_id=category.id))

                for contact in contacts_by_vendor_id.get(vendor.id, []):
                    self.db.add(V2VendorContact(
                        vendor_id=v2_vendor_id,
                        name=contact.name,
                        designation=contact.designation,
                        phone=contact.phone,
                        whatsapp=contact.whatsapp,
                        is_primary=contact.is_primary,
                    ))
                self.db.flush()

            resolvable_legacy_ids.add(vendor.id)
            report.imported.append({
                "legacy_vendor_id": vendor.id,
                "v2_vendor_id": v2_vendor_id,
                "name": vendor.name,
                "engagement_type": vendor.engagement_type,
            })

        if not dry_run:
            self.db.commit()

        return report
