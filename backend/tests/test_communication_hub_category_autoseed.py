from __future__ import annotations

import unittest
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import ExecutionTemplateTask, VendorCategory
from app.routes.communication import ensure_task_category_vendor_categories


class CommunicationHubCategoryAutoSeedTests(unittest.TestCase):
    """Replaces the old standalone "Vendor Category Mapping" page: instead
    of an Admin manually linking each template task category to a vendor
    category one at a time, communication.py's get_hub() now auto-creates
    a matching VendorCategory for every distinct
    ExecutionTemplateTask.category, so the Vendor Hub's existing category
    picker just has them available. The manual path (add/edit/archive any
    other category) is untouched - this only adds missing task-category
    rows, never removes or renames an existing one.
    """

    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        for table in (ExecutionTemplateTask.__table__, VendorCategory.__table__):
            table.create(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self):
        self.engine.dispose()

    def add_template_task(self, session, category):
        session.add(ExecutionTemplateTask(
            id=uuid.uuid4(), template_id=uuid.uuid4(), day_no=1, title="Task", category=category,
        ))

    def test_creates_a_service_category_per_distinct_task_category(self):
        with self.Session.begin() as session:
            self.add_template_task(session, "Ceiling")
            self.add_template_task(session, "Electrical")
            self.add_template_task(session, "Ceiling")  # duplicate task category, single category expected

        with self.Session() as session:
            ensure_task_category_vendor_categories(session)

        with self.Session() as session:
            names = {row.name for row in session.scalars(select(VendorCategory))}
            self.assertEqual(names, {"Ceiling", "Electrical"})
            for category in session.scalars(select(VendorCategory)):
                self.assertEqual(category.category_type, "service")
                self.assertIsNone(category.parent_id)
                self.assertTrue(category.active)

    def test_does_not_duplicate_an_existing_case_insensitive_match(self):
        with self.Session.begin() as session:
            self.add_template_task(session, "Ceiling")
            session.add(VendorCategory(name="ceiling", category_type="material"))

        with self.Session() as session:
            ensure_task_category_vendor_categories(session)

        with self.Session() as session:
            rows = session.scalars(select(VendorCategory)).all()
            self.assertEqual(len(rows), 1)
            # The pre-existing row (with its own category_type) is left untouched.
            self.assertEqual(rows[0].name, "ceiling")
            self.assertEqual(rows[0].category_type, "material")

    def test_idempotent_across_repeated_calls(self):
        with self.Session.begin() as session:
            self.add_template_task(session, "Logistics")

        with self.Session() as session:
            ensure_task_category_vendor_categories(session)
        with self.Session() as session:
            ensure_task_category_vendor_categories(session)

        with self.Session() as session:
            rows = session.scalars(select(VendorCategory)).all()
            self.assertEqual(len(rows), 1)

    def test_blank_categories_are_ignored(self):
        with self.Session.begin() as session:
            self.add_template_task(session, "")
            self.add_template_task(session, "  ")

        with self.Session() as session:
            ensure_task_category_vendor_categories(session)

        with self.Session() as session:
            self.assertEqual(session.scalars(select(VendorCategory)).all(), [])

    def test_no_template_tasks_is_a_no_op(self):
        with self.Session() as session:
            ensure_task_category_vendor_categories(session)
            self.assertEqual(session.scalars(select(VendorCategory)).all(), [])


if __name__ == "__main__":
    unittest.main()
