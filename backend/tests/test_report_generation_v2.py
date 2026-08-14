from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.database import get_db
from app.execution_models import (
    BaselineTask,
    OutboxEvent,
    ProjectBaseline,
    SupportAssignmentChange,
    Task,
    TaskApprovalDecision,
    TaskBlocker,
    TaskDelayEvent,
    TaskDependency,
    TaskProgressUpdate,
    TaskSupportAssignment,
    TaskVerification,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import (
    ProjectRoleChange,
    V2AuditEvent,
    V2Project,
    V2ProjectMembership,
    V2ProjectTask,
    V2ProjectTaskDependency,
)
from app.report_models import ReportSnapshot
from app.routes.projects_v2 import router as projects_router
from app.routes.reports_v2 import router as reports_router
from app.template_models import V2Template, V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
OUTSIDER_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")


class ReportGenerationTests(unittest.TestCase):
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
            EmployeeProfile.__table__,
            V2Template.__table__,
            V2TemplateVersion.__table__,
            V2TemplateTask.__table__,
            V2TemplateTaskDependency.__table__,
            V2Project.__table__,
            V2ProjectMembership.__table__,
            V2ProjectTask.__table__,
            V2ProjectTaskDependency.__table__,
            ProjectRoleChange.__table__,
            V2AuditEvent.__table__,
            ProjectBaseline.__table__,
            BaselineTask.__table__,
            Task.__table__,
            TaskDependency.__table__,
            TaskProgressUpdate.__table__,
            TaskVerification.__table__,
            TaskBlocker.__table__,
            TaskDelayEvent.__table__,
            TaskApprovalDecision.__table__,
            TaskSupportAssignment.__table__,
            SupportAssignmentChange.__table__,
            OutboxEvent.__table__,
            ReportSnapshot.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.project_id = uuid.uuid4()

        with self.Session.begin() as session:
            session.add(User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True))
            session.add(User(
                id=OUTSIDER_ID, name="Outsider", email="outsider@example.com", role=UserRole.supervisor, active=True,
            ))
            session.flush()
            session.add(EmployeeProfile(user_id=OUTSIDER_ID, employee_code="OUT-001", designation="Supervisor", availability="available"))
            session.add(V2Project(
                id=self.project_id, code="PRJ-1", name="Project 1", client_name="Client", site_address="Site",
                start_date=date(2026, 8, 1), status="active", created_by=ADMIN_ID,
            ))
            session.add(Task(
                id=uuid.uuid4(), project_id=self.project_id, baseline_id=uuid.uuid4(), baseline_task_id=uuid.uuid4(),
                original_code="T001", template_sequence=1, title="Task T001",
                schedule_classification="execution", applicability="mandatory", lifecycle_status="in_progress",
            ))

        self.app = FastAPI()
        self.app.include_router(projects_router)
        self.app.include_router(reports_router)

        def override_db():
            with self.Session() as session:
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self._current_actor = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
        self.app.dependency_overrides[current_user] = lambda: self._current_actor
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def act_as_outsider(self):
        self._current_actor = User(
            id=OUTSIDER_ID, name="Outsider", email="outsider@example.com", role=UserRole.supervisor, active=True,
        )

    def generate(self, report_type="daily", period_start=None, period_end=None):
        now = datetime.now(timezone.utc)
        period_start = period_start or (now - timedelta(days=1))
        period_end = period_end or now
        return self.client.post(
            f"/api/v2/projects/{self.project_id}/reports",
            json={
                "report_type": report_type,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
            },
        )

    # ---- happy paths ---------------------------------------------------

    def test_daily_report_matches_live_summary_at_generation(self):
        response = self.generate("daily")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["report_type"], "daily")
        self.assertEqual(body["version_no"], 1)
        self.assertEqual(body["payload_json"]["summary"]["total_count"], 1)
        self.assertNotIn("milestone_progress", body["payload_json"])

    def test_weekly_report_includes_data_not_in_daily(self):
        response = self.generate("weekly")
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()["payload_json"]
        self.assertIn("milestone_progress", payload)
        self.assertIn("schedule_revisions", payload)
        self.assertIn("ownership_changes", payload)
        self.assertIn("management_decisions_required", payload)

    # ---- U17: variance reaches the reports ---------------------------------

    def test_a_generated_report_carries_the_schedule_variance_figures(self):
        """U17: variance must reach the places management already looks.

        It arrives via the visibility summary rather than as its own payload
        section - `_build_payload` dumps the whole summary, and
        `schedule_variance` is a field on it. That makes this test the only
        thing standing between a future refactor (dumping a subset of the
        summary, reshaping the payload) and variance silently vanishing from
        every report with nothing failing.
        """
        for report_type in ("daily", "weekly"):
            with self.subTest(report_type=report_type):
                payload = self.generate(report_type).json()["payload_json"]
                variance = payload["summary"]["schedule_variance"]
                self.assertEqual(
                    set(variance),
                    {"early_count", "on_time_count", "late_count", "not_measured_count", "worst_late_days"},
                )

    def test_report_variance_counts_a_late_task_as_late(self):
        """Not just present, but populated: a report whose variance block is
        structurally correct and always zero would pass the test above."""
        with self.Session.begin() as session:
            task = session.scalars(select(Task).where(Task.project_id == self.project_id)).one()
            task.planned_start_date = date(2026, 8, 1)
            task.planned_end_date = date(2026, 8, 5)
            task.actual_start_at = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
            task.actual_finish_at = datetime(2026, 8, 9, 17, 0, tzinfo=timezone.utc)
            task.lifecycle_status = "completed"
            session.add(task)

        variance = self.generate("weekly").json()["payload_json"]["summary"]["schedule_variance"]
        self.assertEqual(variance["late_count"], 1)
        self.assertEqual(variance["worst_late_days"], 4)
        self.assertEqual(variance["early_count"], 0)

    # ---- integration -------------------------------------------------------

    def test_snapshot_payload_is_frozen_after_live_state_changes(self):
        """The plan's Key Technical Decision: a report snapshot must never
        silently change after generation, even if the project's live state
        (task counts, blockers, etc.) changes afterward."""
        response = self.generate("daily")
        self.assertEqual(response.status_code, 200, response.text)
        snapshot_id = response.json()["id"]
        original_total_count = response.json()["payload_json"]["summary"]["total_count"]
        self.assertEqual(original_total_count, 1)

        with self.Session.begin() as session:
            session.add(Task(
                id=uuid.uuid4(), project_id=self.project_id, baseline_id=uuid.uuid4(), baseline_task_id=uuid.uuid4(),
                original_code="T002", template_sequence=2, title="Task T002",
                schedule_classification="execution", applicability="mandatory", lifecycle_status="planned",
            ))

        listing = self.client.get(f"/api/v2/projects/{self.project_id}/reports")
        self.assertEqual(listing.status_code, 200, listing.text)
        refetched = next(row for row in listing.json() if row["id"] == snapshot_id)
        self.assertEqual(refetched["payload_json"]["summary"]["total_count"], original_total_count)

    # ---- edge cases ------------------------------------------------------

    def test_regenerating_same_period_creates_a_new_version_not_an_overwrite(self):
        start = datetime.now(timezone.utc) - timedelta(days=1)
        end = datetime.now(timezone.utc)
        first = self.generate("daily", start, end)
        second = self.generate("daily", start, end)
        self.assertEqual(first.json()["version_no"], 1)
        self.assertEqual(second.json()["version_no"], 2)

        listing = self.client.get(f"/api/v2/projects/{self.project_id}/reports")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.json()), 2)

    def test_report_generated_before_any_tasks_existed_is_still_valid(self):
        empty_project_id = uuid.uuid4()
        with self.Session.begin() as session:
            session.add(V2Project(
                id=empty_project_id, code="PRJ-2", name="Project 2", client_name="Client", site_address="Site",
                start_date=date(2026, 8, 1), status="draft", created_by=ADMIN_ID,
            ))
        response = self.client.post(
            f"/api/v2/projects/{empty_project_id}/reports",
            json={
                "report_type": "daily",
                "period_start": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                "period_end": datetime.now(timezone.utc).isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["payload_json"]["summary"]["total_count"], 0)

    # ---- error path --------------------------------------------------------

    def test_non_member_non_admin_cannot_generate_or_list_reports(self):
        self.act_as_outsider()
        generate_response = self.generate("daily")
        self.assertEqual(generate_response.status_code, 403)
        list_response = self.client.get(f"/api/v2/projects/{self.project_id}/reports")
        self.assertEqual(list_response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
