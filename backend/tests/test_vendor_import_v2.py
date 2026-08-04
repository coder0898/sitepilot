from __future__ import annotations

import unittest
import uuid

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import ContractorRelationship, User, UserRole, Vendor, VendorContact
from app.services.vendor_import import VendorImportService
from app.vendor_models import V2CapabilityCategory, V2Vendor, V2VendorCapability, V2VendorContact

ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")


def _make_vendor(
    *,
    name: str,
    engagement_type: str = "main",
    status: str = "active",
    parent_vendor_id: uuid.UUID | None = None,
    category: str = "Electrical",
) -> Vendor:
    migration_status = "parent_required" if engagement_type == "migration_pending" else "ready"
    return Vendor(
        id=uuid.uuid4(),
        name=name,
        category=category,
        contact_person=f"{name} Contact",
        phone="9999999999",
        status=status,
        engagement_type=engagement_type,
        parent_vendor_id=parent_vendor_id,
        migration_status=migration_status,
    )


class VendorImportV2Tests(unittest.TestCase):
    """Phase 2 U1: one-time legacy vendor import into siteops_v2 (R1).

    Follows the SQLite-in-memory-with-ATTACHed-schema harness pattern
    established across the rest of the V2 test suite (see
    test_project_baseline_lock_v2.py). VendorImportService is exercised
    directly against a Session - this unit adds no routes, so there is no
    FastAPI TestClient here.
    """

    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (
            User.__table__,
            Vendor.__table__,
            VendorContact.__table__,
            ContractorRelationship.__table__,
            V2Vendor.__table__,
            V2CapabilityCategory.__table__,
            V2VendorCapability.__table__,
            V2VendorContact.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Session() as session:
            session.add(User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True))
            session.commit()

    def tearDown(self):
        self.engine.dispose()

    # ---- 1. happy path ---------------------------------------------------

    def test_main_and_sub_vendor_imported_with_parent_relationship_preserved(self):
        main = _make_vendor(name="Main Co")
        sub = _make_vendor(name="Sub Co", engagement_type="sub_vendor", parent_vendor_id=main.id)
        with self.Session() as session:
            session.add_all([main, sub])
            session.add(VendorContact(vendor_id=main.id, name="Primary Contact", phone="8888888888", is_primary=True))
            session.commit()

            report = VendorImportService(session).import_from_legacy(actor_id=ADMIN_ID, dry_run=False)

            self.assertEqual(report.imported_count, 2)
            self.assertEqual(report.rejected, [])
            self.assertEqual(report.excluded_pending, [])

            v2_main = session.scalar(select(V2Vendor).where(V2Vendor.legacy_vendor_id == main.id))
            v2_sub = session.scalar(select(V2Vendor).where(V2Vendor.legacy_vendor_id == sub.id))
            self.assertIsNotNone(v2_main)
            self.assertIsNotNone(v2_sub)
            self.assertIsNone(v2_main.parent_vendor_id)
            self.assertEqual(v2_sub.parent_vendor_id, v2_main.id)
            self.assertEqual(v2_main.created_by, ADMIN_ID)

            # Category normalized into capability_categories + join row.
            category = session.scalar(select(V2CapabilityCategory).where(V2CapabilityCategory.name == "Electrical"))
            self.assertIsNotNone(category)
            capability = session.scalar(
                select(V2VendorCapability).where(
                    V2VendorCapability.vendor_id == v2_main.id, V2VendorCapability.category_id == category.id
                )
            )
            self.assertIsNotNone(capability)

            contact = session.scalar(select(V2VendorContact).where(V2VendorContact.vendor_id == v2_main.id))
            self.assertIsNotNone(contact)
            self.assertTrue(contact.is_primary)

    # ---- 2. inactive/missing parent ---------------------------------------

    def test_sub_vendor_with_inactive_parent_is_rejected(self):
        main = _make_vendor(name="Inactive Main", status="inactive")
        sub = _make_vendor(name="Sub Of Inactive", engagement_type="sub_vendor", parent_vendor_id=main.id)
        with self.Session() as session:
            session.add_all([main, sub])
            session.commit()

            report = VendorImportService(session).import_from_legacy(dry_run=False)

            self.assertEqual(len(report.rejected), 1)
            self.assertEqual(report.rejected[0]["legacy_vendor_id"], sub.id)
            self.assertEqual(report.rejected[0]["reason"], "parent_missing_or_inactive")
            self.assertEqual(session.scalar(select(V2Vendor).where(V2Vendor.legacy_vendor_id == sub.id)), None)

    def test_sub_vendor_with_missing_parent_is_rejected(self):
        dangling_parent_id = uuid.uuid4()  # no legacy Vendor row exists for this id
        sub = _make_vendor(name="Orphan Sub", engagement_type="sub_vendor", parent_vendor_id=dangling_parent_id)
        with self.Session() as session:
            session.add(sub)
            session.commit()

            report = VendorImportService(session).import_from_legacy(dry_run=False)

            self.assertEqual(len(report.rejected), 1)
            self.assertEqual(report.rejected[0]["reason"], "parent_missing_or_inactive")
            self.assertEqual(session.scalar(select(V2Vendor).where(V2Vendor.legacy_vendor_id == sub.id)), None)

    # ---- 3. duplicate primary contacts -------------------------------------

    def test_vendor_with_two_primary_contacts_is_rejected(self):
        vendor = _make_vendor(name="Double Primary Co")
        with self.Session() as session:
            session.add(vendor)
            session.add(VendorContact(vendor_id=vendor.id, name="Contact A", phone="1111111111", is_primary=True))
            session.add(VendorContact(vendor_id=vendor.id, name="Contact B", phone="2222222222", is_primary=True))
            session.commit()

            report = VendorImportService(session).import_from_legacy(dry_run=False)

            self.assertEqual(len(report.rejected), 1)
            self.assertEqual(report.rejected[0]["legacy_vendor_id"], vendor.id)
            self.assertEqual(report.rejected[0]["reason"], "multiple_primary_contacts")
            self.assertEqual(session.scalar(select(V2Vendor).where(V2Vendor.legacy_vendor_id == vendor.id)), None)
            # No orphaned V2VendorContact rows either.
            self.assertEqual(session.scalars(select(V2VendorContact)).all(), [])

    # ---- 4. migration_pending exclusion -------------------------------------

    def test_migration_pending_vendor_is_excluded_and_reported(self):
        vendor = _make_vendor(name="Pending Co", engagement_type="migration_pending")
        with self.Session() as session:
            session.add(vendor)
            session.commit()

            report = VendorImportService(session).import_from_legacy(dry_run=False)

            self.assertEqual(report.imported, [])
            self.assertEqual(report.rejected, [])
            self.assertEqual(len(report.excluded_pending), 1)
            self.assertEqual(report.excluded_pending[0]["legacy_vendor_id"], vendor.id)
            self.assertEqual(report.excluded_pending[0]["reason"], "requires resolution before import")
            self.assertEqual(session.scalar(select(V2Vendor).where(V2Vendor.legacy_vendor_id == vendor.id)), None)

    # ---- 5. ContractorRelationship disagreement --------------------------

    def test_contractor_relationship_disagreement_is_flagged_not_auto_resolved(self):
        authoritative_parent = _make_vendor(name="Authoritative Parent")
        other_parent = _make_vendor(name="Other Parent")
        sub = _make_vendor(name="Disputed Sub", engagement_type="sub_vendor", parent_vendor_id=authoritative_parent.id)
        with self.Session() as session:
            session.add_all([authoritative_parent, other_parent, sub])
            # Disagrees with sub.parent_vendor_id (authoritative_parent).
            session.add(ContractorRelationship(main_contractor_id=other_parent.id, subcontractor_id=sub.id))
            session.commit()

            report = VendorImportService(session).import_from_legacy(dry_run=False)

            self.assertEqual(len(report.flagged_for_review), 1)
            flag = report.flagged_for_review[0]
            self.assertEqual(flag["legacy_vendor_id"], sub.id)
            self.assertEqual(flag["parent_vendor_id"], authoritative_parent.id)
            self.assertEqual(flag["contractor_relationship_main_id"], other_parent.id)

            # parent_vendor_id remains authoritative: the sub is still
            # imported, against the authoritative parent - not silently
            # dropped, and not silently switched to the disputed parent.
            v2_authoritative = session.scalar(
                select(V2Vendor).where(V2Vendor.legacy_vendor_id == authoritative_parent.id)
            )
            v2_sub = session.scalar(select(V2Vendor).where(V2Vendor.legacy_vendor_id == sub.id))
            self.assertIsNotNone(v2_sub)
            self.assertEqual(v2_sub.parent_vendor_id, v2_authoritative.id)

    # ---- 6. idempotent re-run ----------------------------------------------

    def test_rerunning_import_does_not_create_duplicates(self):
        main = _make_vendor(name="Repeat Main")
        sub = _make_vendor(name="Repeat Sub", engagement_type="sub_vendor", parent_vendor_id=main.id)
        with self.Session() as session:
            session.add_all([main, sub])
            session.commit()

            first_report = VendorImportService(session).import_from_legacy(dry_run=False)
            self.assertEqual(first_report.imported_count, 2)

            second_report = VendorImportService(session).import_from_legacy(dry_run=False)
            self.assertEqual(second_report.imported_count, 0)
            self.assertEqual(len(second_report.already_imported), 2)

            all_v2_vendors = session.scalars(select(V2Vendor)).all()
            self.assertEqual(len(all_v2_vendors), 2)
            all_capabilities = session.scalars(select(V2VendorCapability)).all()
            self.assertEqual(len(all_capabilities), 2)

    # ---- 7. dry_run semantics ----------------------------------------------

    def test_dry_run_default_makes_no_writes_real_run_commits(self):
        vendor = _make_vendor(name="Dry Run Co")
        with self.Session() as session:
            session.add(vendor)
            session.commit()

            # Default dry_run=True.
            dry_report = VendorImportService(session).import_from_legacy()
            self.assertTrue(dry_report.dry_run)
            self.assertEqual(dry_report.imported_count, 1)
            self.assertEqual(session.scalars(select(V2Vendor)).all(), [])

        with self.Session() as session:
            real_report = VendorImportService(session).import_from_legacy(dry_run=False)
            self.assertFalse(real_report.dry_run)
            self.assertEqual(real_report.imported_count, 1)

        with self.Session() as session:
            v2_vendor = session.scalar(select(V2Vendor).where(V2Vendor.legacy_vendor_id == vendor.id))
            self.assertIsNotNone(v2_vendor)


if __name__ == "__main__":
    unittest.main()
