"""U4: relative day offsets become real planned start and target finish dates."""
from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timezone

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
    BaselineTask, ExecutionExcludedDependency, ExecutionGate, ExecutionGateTask, ProjectBaseline,
    Task, TaskBlocker, TaskDependency, TaskSupportAssignment,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import (
    V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectExternalGateTask,
    V2ProjectMembership, V2ProjectTask, V2ProjectTaskDependency,
)
from app.routes.execution_tasks_v2 import router as execution_router
from app.routes.projects_v2 import derive_target_handover_date, router
from app.services.project_schedule_dates import planned_start_at, scheduled_date, target_finish_at
from app.services.project_visibility import ProjectVisibilityService, _aware
from app.services.target_date_backfill import TargetDateBackfillService
from app.template_models import (
    V2Template, V2TemplateExternalGate, V2TemplateExternalGateTask,
    V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw): return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
START = date(2026, 8, 1)


def stored(value):
    """SQLite silently drops tzinfo on read where Postgres round-trips it
    aware, so compare through the same `_aware` shim the production code
    reads these columns with rather than against a raw naive value."""
    return None if value is None else _aware(value)


class ScheduleDateArithmeticTests(unittest.TestCase):
    """The conversion rule itself, with no database in the way."""

    def test_day_one_is_the_start_date_itself(self):
        self.assertEqual(scheduled_date(START, 1), date(2026, 8, 1))

    def test_day_eight_is_seven_days_after_the_start(self):
        self.assertEqual(scheduled_date(START, 8), date(2026, 8, 8))

    def test_a_null_offset_yields_no_date_rather_than_an_error(self):
        for helper in (scheduled_date, planned_start_at, target_finish_at):
            with self.subTest(helper=helper.__name__):
                self.assertIsNone(helper(START, None))

    def test_planned_start_is_midnight_at_the_start_of_the_day(self):
        # Work begun at any moment during the planned start day is not
        # early, so the comparison point is the start of that day.
        self.assertEqual(planned_start_at(START, 8), datetime(2026, 8, 8, 0, 0, tzinfo=timezone.utc))

    def test_target_finish_is_the_exclusive_end_of_the_day(self):
        self.assertEqual(target_finish_at(START, 8), datetime(2026, 8, 9, 0, 0, tzinfo=timezone.utc))

    def test_a_task_is_not_overdue_at_any_point_during_its_target_finish_day(self):
        """The reason target finish is not stored as midnight. Runs through
        the real `_overdue_tasks` predicate, so this breaks if that
        comparison ever changes."""
        task = Task(id=uuid.uuid4(), original_code="T008", title="Task 8", lifecycle_status="in_progress",
                    due_at=target_finish_at(START, 8))
        service = ProjectVisibilityService.__new__(ProjectVisibilityService)
        for label, now in (("start of the day", datetime(2026, 8, 8, 0, 0, tzinfo=timezone.utc)),
                           ("midday", datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)),
                           ("one second to midnight", datetime(2026, 8, 8, 23, 59, 59, tzinfo=timezone.utc))):
            with self.subTest(now=label):
                self.assertEqual(service._overdue_tasks([task], now), [])
        overdue = service._overdue_tasks([task], datetime(2026, 8, 9, 0, 0, 1, tzinfo=timezone.utc))
        self.assertEqual(len(overdue), 1, "a task should be overdue once the day after its target finish has begun")

    def test_handover_agrees_with_the_target_finish_of_a_final_day_task(self):
        """One rule, two callers. If these ever disagree, a project's
        handover date and its last task's deadline describe different days."""
        class _Version: duration_days = 45
        handover = derive_target_handover_date(START, _Version())
        self.assertEqual(handover, date(2026, 9, 14))
        # The handover date is the calendar day a day-45 task finishes on,
        # and that task's target finish is the exclusive end of that day.
        self.assertEqual(handover, scheduled_date(START, 45))
        self.assertEqual(target_finish_at(START, 45), datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc))


class ScheduleDateInstantiationTests(unittest.TestCase):
    """Activation writes the dates, and the backfill catches up projects
    activated before it existed."""

    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            dbapi_connection.create_function("btrim", 1, lambda v: v.strip() if v is not None else None)

        for table in (User.__table__, EmployeeProfile.__table__, V2Template.__table__, V2TemplateVersion.__table__,
                      V2TemplateTask.__table__, V2TemplateTaskDependency.__table__, V2Project.__table__,
                      V2ProjectMembership.__table__, V2ProjectTask.__table__, V2ProjectTaskDependency.__table__,
                      V2ProjectExternalGate.__table__, V2AuditEvent.__table__, ProjectBaseline.__table__,
                      BaselineTask.__table__, Task.__table__, TaskDependency.__table__, V2TemplateExternalGate.__table__,
                      V2TemplateExternalGateTask.__table__, V2ProjectExternalGateTask.__table__,
                      TaskBlocker.__table__, TaskSupportAssignment.__table__,
                      ExecutionGate.__table__, ExecutionGateTask.__table__, ExecutionExcludedDependency.__table__):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()
        self.app = FastAPI(); self.app.include_router(router); self.app.include_router(execution_router)

        def override_db():
            with self.Session() as session: yield session

        self.app.dependency_overrides[get_db] = override_db
        self.app.dependency_overrides[current_user] = lambda: User(
            id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
        self.client = TestClient(self.app)

    def tearDown(self): self.client.close(); self.engine.dispose()

    def _seed(self):
        """Three execution tasks on days 1, 8 and 45, plus one
        pre-activation task with no day offsets at all - the R53 case."""
        with self.Session.begin() as session:
            session.add_all([
                User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True),
                User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True),
                User(id=SUPERVISOR_ID, name="Supervisor", email="sup@example.com", role=UserRole.supervisor, active=True),
            ])
            session.flush()
            session.add_all([
                EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                EmployeeProfile(user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor", availability="available"),
            ])
            template = V2Template(code=f"W45-{uuid.uuid4().hex[:8]}", name="Workved 45 Day"); session.add(template); session.flush()
            published = V2TemplateVersion(template_id=template.id, version_no=1, status="published", duration_days=45,
                                          content_hash="h", is_current_published=True, created_by=ADMIN_ID,
                                          published_by=ADMIN_ID, published_at=datetime.now(timezone.utc))
            session.add(published); session.flush()
            session.add(V2TemplateTask(template_version_id=published.id, code="T000", sequence_no=1, title="Pre-activation",
                                       schedule_classification="pre_activation", planned_start_day=None, planned_end_day=None,
                                       applicability="mandatory", task_class="standard", task_kind="work",
                                       evidence_required=False, phase="Pre", category="Admin"))
            for seq, day in ((2, 1), (3, 8), (4, 45)):
                session.add(V2TemplateTask(template_version_id=published.id, code=f"T{day:03d}", sequence_no=seq,
                                           title=f"Day {day}", schedule_classification="execution", planned_start_day=day,
                                           planned_end_day=day, applicability="mandatory", task_class="standard",
                                           task_kind="work", evidence_required=False, duration_days=1,
                                           phase="Setup", category="Site"))
            self.published_version_id = published.id

    def activate_project(self):
        payload = {"project_name": "Futurex Fitout", "client": "Example Client", "location": "Mumbai",
                   "proposed_start_date": START.isoformat(), "target_handover_date": "2026-09-14",
                   "pm_user_id": str(PM_ID), "supervisor_user_id": str(SUPERVISOR_ID),
                   "template_version_id": str(self.published_version_id)}
        project = self.client.post("/api/v2/projects", json=payload)
        self.assertEqual(project.status_code, 201, project.text)
        project_id = project.json()["id"]
        self.assertEqual(self.client.post(f"/api/v2/projects/{project_id}/generate-tasks").status_code, 200)
        activated = self.client.post(f"/api/v2/projects/{project_id}/activate", json={"reason": "Go live."})
        self.assertEqual(activated.status_code, 200, activated.text)
        return uuid.UUID(project_id)

    def tasks_by_code(self, project_id):
        with self.Session() as session:
            return {t.original_code: t for t in session.scalars(select(Task).where(Task.project_id == project_id)).all()}

    def test_activation_writes_both_dates_from_the_day_offsets(self):
        tasks = self.tasks_by_code(self.activate_project())
        self.assertEqual(stored(tasks["T001"].planned_start_at), datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(stored(tasks["T008"].due_at), datetime(2026, 8, 9, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(stored(tasks["T045"].due_at), datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc))

    def test_a_pre_activation_task_gets_null_dates_and_raises_nothing(self):
        """Covers AE8. Seven tasks per real project take this path."""
        pre_activation = self.tasks_by_code(self.activate_project())["T000"]
        self.assertIsNone(pre_activation.planned_start_at)
        self.assertIsNone(pre_activation.due_at)
        self.assertEqual(pre_activation.schedule_classification, "pre_activation")

    def test_the_execution_payload_carries_the_new_fields_and_keeps_the_old_ones(self):
        project_id = self.activate_project()
        response = self.client.get(f"/api/v2/projects/{project_id}/tasks")
        self.assertEqual(response.status_code, 200, response.text)
        rows = {row["original_code"]: row for row in response.json()}
        self.assertEqual(rows["T008"]["target_finish_at"][:10], "2026-08-09")
        self.assertEqual(rows["T008"]["planned_start_at"][:10], "2026-08-08")
        self.assertIsNone(rows["T000"]["planned_start_at"])
        for previously_present in ("id", "original_code", "title", "lifecycle_status", "planned_start_day",
                                   "planned_end_day", "phase", "category", "open_blocker_count", "approval"):
            self.assertIn(previously_present, rows["T008"])

    def _strip_dates(self, project_id):
        """Reproduce a project activated before U4 existed."""
        with self.Session.begin() as session:
            for task in session.scalars(select(Task).where(Task.project_id == project_id)).all():
                task.due_at = None
                task.planned_start_at = None

    def test_the_backfill_populates_a_project_activated_before_this_unit(self):
        project_id = self.activate_project()
        self._strip_dates(project_id)
        with self.Session.begin() as session:
            # A completed task is deliberately included: U11 needs a target
            # finish for work that has already finished.
            session.scalars(select(Task).where(Task.original_code == "T001")).one().lifecycle_status = "completed"
        with self.Session() as session:
            result = TargetDateBackfillService(session).backfill_project(session.get(V2Project, project_id), ADMIN_ID)
        self.assertEqual(result.target_finish_written, 3)
        self.assertEqual(result.skipped_no_offsets, 1)
        tasks = self.tasks_by_code(project_id)
        self.assertEqual(tasks["T001"].lifecycle_status, "completed")
        self.assertEqual(stored(tasks["T001"].due_at), datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc))
        self.assertIsNone(tasks["T000"].due_at)

    def test_the_backfill_is_idempotent_and_leaves_an_existing_due_at_alone(self):
        project_id = self.activate_project()
        with self.Session() as session:
            project = session.get(V2Project, project_id)
            first = TargetDateBackfillService(session).backfill_project(project, ADMIN_ID)
            second = TargetDateBackfillService(session).backfill_project(project, ADMIN_ID)
        # Activation already wrote every date, so the backfill writes none
        # and reports the three dated tasks as already-populated.
        self.assertEqual((first.target_finish_written, first.skipped_existing_due_at), (0, 3))
        self.assertEqual((second.target_finish_written, second.skipped_existing_due_at), (0, 3))
        self.assertEqual(stored(self.tasks_by_code(project_id)["T008"].due_at), datetime(2026, 8, 9, 0, 0, tzinfo=timezone.utc))

    def test_the_backfill_audits_what_it_touched(self):
        project_id = self.activate_project()
        self._strip_dates(project_id)
        with self.Session() as session:
            TargetDateBackfillService(session).backfill_project(session.get(V2Project, project_id), ADMIN_ID)
        with self.Session() as session:
            event_row = session.scalar(select(V2AuditEvent).where(V2AuditEvent.action == "PROJECT_TARGET_DATES_BACKFILLED"))
            self.assertIsNotNone(event_row)
            self.assertEqual(event_row.project_id, project_id)
            self.assertEqual(event_row.after_json["target_finish_written"], 3)
            self.assertTrue(event_row.reason)

    def test_the_backfill_lights_the_overdue_tile_in_one_predictable_step(self):
        """The visible one-off jump, asserted as a count here rather than
        discovered on a live dashboard. A project mid-flight at 20 Aug has
        two of its three dated tasks already past their target finish."""
        mid_flight = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
        # `summarize` reads the clock itself, so the overdue rule is
        # exercised through the same `_overdue_tasks` it calls, with the
        # date injected. That is the part the backfill actually changes.
        overdue = ProjectVisibilityService.__new__(ProjectVisibilityService)._overdue_tasks

        project_id = self.activate_project()
        self._strip_dates(project_id)
        with self.Session() as session:
            tasks = list(session.scalars(select(Task).where(Task.project_id == project_id)).all())
            self.assertEqual(overdue(tasks, mid_flight), [])
            TargetDateBackfillService(session).backfill_project(session.get(V2Project, project_id), ADMIN_ID)
        with self.Session() as session:
            tasks = list(session.scalars(select(Task).where(Task.project_id == project_id)).all())
            self.assertEqual({t.original_code for t in overdue(tasks, mid_flight)}, {"T001", "T008"})

    def test_the_backfill_module_registers_no_router(self):
        """R28: due_at is what delay is measured against, so it must not be
        reachable over HTTP by any execution role."""
        import app.services.target_date_backfill as backfill_module
        self.assertFalse([name for name in dir(backfill_module) if "router" in name.lower()])


if __name__ == "__main__":
    unittest.main()
