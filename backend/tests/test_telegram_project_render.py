"""Readable Telegram messages for project role changes and the weekly
summary (app/services/telegram_project_render.py) - these used to arrive as a
raw key:value dump."""

from __future__ import annotations

import re
import unittest
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.report_models import ReportSnapshot
from app.services.telegram_render import render_telegram
from app.template_models import V2TemplateVersion  # noqa: F401 - FK target for V2Project

UUID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


class TelegramProjectRenderTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (User.__table__, EmployeeProfile.__table__, V2Project.__table__, V2ProjectMembership.__table__, ReportSnapshot.__table__):
            table.create(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        admin = User(id=uuid.uuid4(), name="Niddhi", email="a@example.com", role=UserRole.admin, active=True)
        pm = User(id=uuid.uuid4(), name="Prachit", email="p@example.com", role=UserRole.project_manager, active=True)
        self.db.add_all([admin, pm])
        self.db.flush()
        self.pm_profile = EmployeeProfile(user_id=pm.id, employee_code="PM1", designation="PM", availability="available")
        self.db.add(self.pm_profile)
        self.project = V2Project(
            code="PRJ-1", name="Futurex Office", client_name="Client", site_address="Site",
            start_date=date(2026, 9, 1), status="active", created_by=admin.id,
        )
        self.db.add(self.project)
        self.db.flush()
        self.membership = V2ProjectMembership(
            project_id=self.project.id, employee_id=self.pm_profile.id, project_role="project_manager",
            assigned_by=admin.id, assignment_reason="seed",
        )
        self.db.add(self.membership)
        self.snapshot = ReportSnapshot(
            project_id=self.project.id, report_type="weekly",
            period_start=datetime(2026, 9, 21, tzinfo=timezone.utc), period_end=datetime(2026, 9, 27, tzinfo=timezone.utc),
            version_no=1, generated_by=admin.id,
            payload_json={"summary": {
                "total_count": 40, "completed_count": 12, "active_count": 8, "planned_count": 20,
                "overdue_tasks": [{"id": "x"}, {"id": "y"}], "blocked_tasks": [{"id": "z"}], "delayed_tasks": [],
                "pending_verifications": [{"id": "v"}], "pending_approvals": [], "approval_gates_at_risk": [],
            }},
        )
        self.db.add(self.snapshot)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def assert_readable(self, text: str) -> None:
        self.assertTrue(text.startswith("<b>"))
        self.assertIsNone(UUID_PATTERN.search(text), text)
        self.assertNotRegex(text, r"(?m)^[a-z_]+: ")  # no raw payload keys

    def test_role_change_requested(self):
        message = render_telegram(self.db, "project.role_change_requested", {
            "project_id": str(self.project.id), "change_id": str(uuid.uuid4()), "role_type": "project_manager",
            "change_type": "replacement", "replacement_employee_id": str(self.pm_profile.id), "reason_code": "workload",
        })
        self.assert_readable(message.text)
        self.assertIn("<b>Role Change Requested</b>", message.text)
        self.assertIn("Project: Futurex Office", message.text)
        self.assertIn("Role: Project Manager", message.text)
        self.assertIn("Change: Replace with Prachit", message.text)
        self.assertIn("Reason: Workload", message.text)

    def test_role_change_approved_and_rejected(self):
        approved = render_telegram(self.db, "project.role_change_approved", {
            "project_id": str(self.project.id), "role_type": "project_manager", "change_type": "replacement",
            "membership_id": str(self.membership.id),
        })
        self.assert_readable(approved.text)
        self.assertIn("Now held by: Prachit", approved.text)
        vacated = render_telegram(self.db, "project.role_change_approved", {
            "project_id": str(self.project.id), "role_type": "site_supervisor", "change_type": "vacate",
        })
        self.assertIn("Now held by: Nobody - the role is now empty", vacated.text)
        rejected = render_telegram(self.db, "project.role_change_rejected", {
            "project_id": str(self.project.id), "role_type": "site_supervisor", "reason": "Keep the current team",
        })
        self.assert_readable(rejected.text)
        self.assertIn("Reason: Keep the current team", rejected.text)

    def test_weekly_summary(self):
        message = render_telegram(self.db, "report.weekly_summary_generated", {
            "project_id": str(self.project.id), "report_snapshot_id": str(self.snapshot.id),
        })
        self.assert_readable(message.text)
        self.assertIn("<b>Weekly Project Summary</b>", message.text)
        self.assertIn("Week: 21 Sep 2026 - 27 Sep 2026", message.text)
        self.assertIn("Tasks: 12 completed, 8 in progress, 20 not started (of 40)", message.text)
        self.assertIn("Overdue: 2", message.text)
        self.assertIn("Blocked: 1", message.text)
        self.assertIn("Some items need attention", message.text)

    def test_missing_records_never_raise(self):
        for event_type in (
            "project.role_change_requested", "project.role_change_approved",
            "project.role_change_rejected", "report.weekly_summary_generated",
        ):
            with self.subTest(event_type=event_type):
                message = render_telegram(self.db, event_type, {"project_id": str(uuid.uuid4())})
                self.assertIn("Unknown project", message.text)


if __name__ == "__main__":
    unittest.main()
