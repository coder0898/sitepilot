"""Plan Phase 6 (first half): escalation-tracking table + `EscalationService`
sweep logic.

Exercises `EscalationService`'s four sweep methods directly against a
SQLite in-memory harness (ATTACHed `siteops_v2` schema, mirroring
test_project_visibility_summary_v2.py's lighter pattern - real `Task`/
`ProjectExternalApproval` rows built directly rather than driven through
the full baseline-lock/activation HTTP flow, since this unit only needs
realistic rows plus an explicit `now`, the same way any other service in
this codebase is unit tested).

Covers, for each of the four sweep methods:
- happy path: a qualifying entity gets tracked + its event emitted.
- idempotency: running the same sweep twice with the same `now` does not
  double-track or double-emit.
- (escalation methods only) the 6-hour boundary: just under 6h since the
  `followup` row was triggered -> not escalated; at/over 6h -> escalated.
- (escalation methods only) the "condition cleared" resolve behavior: an
  update/status-change landed before the escalation sweep runs -> the
  `followup` row is resolved, not escalated further.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.execution_models import (
    EscalationTracking,
    OutboxEvent,
    ProjectExternalApproval,
    Task,
    TaskProgressUpdate,
)
from app.models import User, UserRole
from app.project_models import V2Project
from app.services.escalation import EscalationService
from app.template_models import V2Template, V2TemplateVersion


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


def _aware(value: datetime) -> datetime:
    """SQLite silently drops tzinfo on read - normalize before comparing
    against an aware `self.now`, mirroring the service's own `_aware`."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
ASSIGNEE_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")


class EscalationServiceTests(unittest.TestCase):
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
            V2Template.__table__,
            V2TemplateVersion.__table__,
            V2Project.__table__,
            Task.__table__,
            TaskProgressUpdate.__table__,
            ProjectExternalApproval.__table__,
            EscalationTracking.__table__,
            OutboxEvent.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.project_id = uuid.uuid4()
        self.now = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)

        with self.Session.begin() as session:
            session.add(User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True))
            session.add(User(
                id=ASSIGNEE_ID, name="Assignee", email="assignee@example.com",
                role=UserRole.project_manager, active=True,
            ))
            session.add(V2Project(
                id=self.project_id, code="PRJ-1", name="Project 1", client_name="Client", site_address="Site",
                start_date=date(2026, 8, 1), status="active", created_by=ADMIN_ID,
            ))

    def tearDown(self):
        self.engine.dispose()

    # ---- fixtures --------------------------------------------------------

    def make_task(self, session, code: str, **overrides) -> Task:
        defaults = dict(
            id=uuid.uuid4(), project_id=self.project_id,
            baseline_id=uuid.uuid4(), baseline_task_id=uuid.uuid4(),
            original_code=code, template_sequence=1, title=f"Task {code}",
            schedule_classification="execution", applicability="mandatory",
            lifecycle_status="in_progress", update_sla_hours=24,
            created_at=self.now - timedelta(hours=48),
        )
        defaults.update(overrides)
        task = Task(**defaults)
        session.add(task)
        return task

    def make_approval(self, session, **overrides) -> ProjectExternalApproval:
        defaults = dict(
            id=uuid.uuid4(), project_id=self.project_id, project_gate_id=uuid.uuid4(),
            status="assigned", assigned_to_user_id=ASSIGNEE_ID, assigned_by=ADMIN_ID,
            assigned_at=self.now - timedelta(days=2),
            due_at=self.now.date() - timedelta(days=1),
        )
        defaults.update(overrides)
        approval = ProjectExternalApproval(**defaults)
        session.add(approval)
        return approval

    def outbox_events(self, session, event_type: str, aggregate_id: uuid.UUID) -> list[OutboxEvent]:
        return list(session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.event_type == event_type, OutboxEvent.aggregate_id == aggregate_id,
            )
        ).all())

    def open_tracking(self, session, entity_type: str, entity_id: uuid.UUID, stage: str) -> EscalationTracking | None:
        return session.scalar(
            select(EscalationTracking).where(
                EscalationTracking.entity_type == entity_type,
                EscalationTracking.entity_id == entity_id,
                EscalationTracking.stage == stage,
            )
        )

    # ---- sweep_task_followups ---------------------------------------------

    def test_stale_task_gets_tracked_and_event_emitted(self):
        with self.Session.begin() as session:
            task = self.make_task(session, "T001")
        task_id = task.id

        with self.Session() as session:
            result = EscalationService(session).sweep_task_followups(self.now)
        self.assertEqual([t.id for t in result], [task_id])

        with self.Session() as session:
            tracking = self.open_tracking(session, "task", task_id, "followup")
            self.assertIsNotNone(tracking)
            self.assertIsNone(tracking.resolved_at)
            self.assertEqual(_aware(tracking.triggered_at), self.now)

            events = self.outbox_events(session, "task.eod_followup_required", task_id)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].aggregate_type, "task")
            self.assertEqual(events[0].payload["task_id"], str(task_id))

    def test_sweep_task_followups_is_idempotent_for_the_same_now(self):
        with self.Session.begin() as session:
            task = self.make_task(session, "T001")
        task_id = task.id

        with self.Session() as session:
            first = EscalationService(session).sweep_task_followups(self.now)
        with self.Session() as session:
            second = EscalationService(session).sweep_task_followups(self.now)

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])

        with self.Session() as session:
            tracking_rows = list(session.scalars(
                select(EscalationTracking).where(
                    EscalationTracking.entity_type == "task", EscalationTracking.entity_id == task_id,
                )
            ).all())
            self.assertEqual(len(tracking_rows), 1)
            events = self.outbox_events(session, "task.eod_followup_required", task_id)
            self.assertEqual(len(events), 1)

    def test_task_with_recent_progress_update_is_not_flagged(self):
        with self.Session.begin() as session:
            task = self.make_task(session, "T001")
            session.flush()
            session.add(TaskProgressUpdate(
                task_id=task.id, project_id=self.project_id, update_type="note", note="Still going.",
                submitted_by=ADMIN_ID, created_at=self.now - timedelta(hours=1),
            ))

        with self.Session() as session:
            result = EscalationService(session).sweep_task_followups(self.now)
        self.assertEqual(result, [])

    def test_completed_task_is_never_flagged(self):
        with self.Session.begin() as session:
            self.make_task(session, "T001", lifecycle_status="completed")

        with self.Session() as session:
            result = EscalationService(session).sweep_task_followups(self.now)
        self.assertEqual(result, [])

    # ---- sweep_task_escalations --------------------------------------------

    def test_task_escalation_just_under_six_hours_is_not_escalated(self):
        with self.Session.begin() as session:
            task = self.make_task(session, "T001")
            session.flush()
            session.add(EscalationTracking(
                entity_type="task", entity_id=task.id, stage="followup",
                triggered_at=self.now - timedelta(hours=5, minutes=59),
            ))
        task_id = task.id

        with self.Session() as session:
            result = EscalationService(session).sweep_task_escalations(self.now)
        self.assertEqual(result, [])

        with self.Session() as session:
            self.assertIsNone(self.open_tracking(session, "task", task_id, "admin_escalation"))
            followup = self.open_tracking(session, "task", task_id, "followup")
            self.assertIsNone(followup.resolved_at)
            self.assertEqual(self.outbox_events(session, "task.escalated_to_admin", task_id), [])

    def test_task_escalation_at_six_hours_escalates(self):
        with self.Session.begin() as session:
            task = self.make_task(session, "T001")
            session.flush()
            session.add(EscalationTracking(
                entity_type="task", entity_id=task.id, stage="followup",
                triggered_at=self.now - timedelta(hours=6),
            ))
        task_id = task.id

        with self.Session() as session:
            result = EscalationService(session).sweep_task_escalations(self.now)
        self.assertEqual([t.id for t in result], [task_id])

        with self.Session() as session:
            admin_row = self.open_tracking(session, "task", task_id, "admin_escalation")
            self.assertIsNotNone(admin_row)
            self.assertIsNone(admin_row.resolved_at)
            events = self.outbox_events(session, "task.escalated_to_admin", task_id)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].aggregate_type, "task")

    def test_task_escalation_condition_cleared_resolves_without_escalating(self):
        with self.Session.begin() as session:
            task = self.make_task(session, "T001")
            session.flush()
            session.add(EscalationTracking(
                entity_type="task", entity_id=task.id, stage="followup",
                triggered_at=self.now - timedelta(hours=7),
            ))
            # An update landed after the followup was triggered, before the
            # escalation sweep runs - the live staleness condition has since
            # cleared.
            session.add(TaskProgressUpdate(
                task_id=task.id, project_id=self.project_id, update_type="note", note="Caught up.",
                submitted_by=ADMIN_ID, created_at=self.now - timedelta(hours=1),
            ))
        task_id = task.id

        with self.Session() as session:
            result = EscalationService(session).sweep_task_escalations(self.now)
        self.assertEqual(result, [])

        with self.Session() as session:
            followup = self.open_tracking(session, "task", task_id, "followup")
            self.assertEqual(_aware(followup.resolved_at), self.now)
            self.assertIsNone(self.open_tracking(session, "task", task_id, "admin_escalation"))
            self.assertEqual(self.outbox_events(session, "task.escalated_to_admin", task_id), [])

    def test_a_second_stale_episode_can_be_tracked_after_the_first_resolves(self):
        # Regression: uq_v2_escalation_tracking_entity_stage_open must be a
        # PARTIAL unique index (where resolved_at is null), not a table-wide
        # one - otherwise a task that stalls, resolves, and later stalls
        # again could never get a second 'followup' row for the same stage.
        with self.Session.begin() as session:
            task = self.make_task(session, "T001")
            session.flush()
            session.add(EscalationTracking(
                entity_type="task", entity_id=task.id, stage="followup",
                triggered_at=self.now - timedelta(days=10), resolved_at=self.now - timedelta(days=9),
            ))
        task_id = task.id

        with self.Session() as session:
            result = EscalationService(session).sweep_task_followups(self.now)
        self.assertEqual([t.id for t in result], [task_id])

        with self.Session() as session:
            rows = list(session.scalars(
                select(EscalationTracking).where(
                    EscalationTracking.entity_type == "task", EscalationTracking.entity_id == task_id,
                    EscalationTracking.stage == "followup",
                ).order_by(EscalationTracking.triggered_at)
            ).all())
            self.assertEqual(len(rows), 2)
            self.assertIsNotNone(rows[0].resolved_at)
            self.assertIsNone(rows[1].resolved_at)
            self.assertEqual(_aware(rows[1].triggered_at), self.now)

    def test_task_escalation_is_idempotent_for_the_same_now(self):
        with self.Session.begin() as session:
            task = self.make_task(session, "T001")
            session.flush()
            session.add(EscalationTracking(
                entity_type="task", entity_id=task.id, stage="followup",
                triggered_at=self.now - timedelta(hours=6),
            ))
        task_id = task.id

        with self.Session() as session:
            first = EscalationService(session).sweep_task_escalations(self.now)
        with self.Session() as session:
            second = EscalationService(session).sweep_task_escalations(self.now)

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])

        with self.Session() as session:
            admin_rows = list(session.scalars(
                select(EscalationTracking).where(
                    EscalationTracking.entity_type == "task", EscalationTracking.entity_id == task_id,
                    EscalationTracking.stage == "admin_escalation",
                )
            ).all())
            self.assertEqual(len(admin_rows), 1)
            self.assertEqual(len(self.outbox_events(session, "task.escalated_to_admin", task_id)), 1)

    # ---- sweep_approval_followups -------------------------------------------

    def test_overdue_assigned_approval_gets_tracked_and_event_emitted(self):
        with self.Session.begin() as session:
            approval = self.make_approval(session)
        approval_id = approval.id

        with self.Session() as session:
            result = EscalationService(session).sweep_approval_followups(self.now)
        self.assertEqual([a.id for a in result], [approval_id])

        with self.Session() as session:
            tracking = self.open_tracking(session, "project_external_approval", approval_id, "followup")
            self.assertIsNotNone(tracking)
            events = self.outbox_events(session, "project_external_approval.followup_required", approval_id)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].aggregate_type, "project_external_approval")
            self.assertEqual(events[0].payload["approval_id"], str(approval_id))

    def test_approval_due_today_is_flagged(self):
        with self.Session.begin() as session:
            self.make_approval(session, due_at=self.now.date())

        with self.Session() as session:
            result = EscalationService(session).sweep_approval_followups(self.now)
        self.assertEqual(len(result), 1)

    def test_approval_not_yet_due_is_not_flagged(self):
        with self.Session.begin() as session:
            self.make_approval(session, due_at=self.now.date() + timedelta(days=3))

        with self.Session() as session:
            result = EscalationService(session).sweep_approval_followups(self.now)
        self.assertEqual(result, [])

    def test_submitted_approval_is_not_flagged(self):
        with self.Session.begin() as session:
            self.make_approval(session, status="submitted")

        with self.Session() as session:
            result = EscalationService(session).sweep_approval_followups(self.now)
        self.assertEqual(result, [])

    def test_sweep_approval_followups_is_idempotent_for_the_same_now(self):
        with self.Session.begin() as session:
            approval = self.make_approval(session)
        approval_id = approval.id

        with self.Session() as session:
            first = EscalationService(session).sweep_approval_followups(self.now)
        with self.Session() as session:
            second = EscalationService(session).sweep_approval_followups(self.now)

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])

        with self.Session() as session:
            self.assertEqual(
                len(self.outbox_events(session, "project_external_approval.followup_required", approval_id)), 1,
            )

    # ---- sweep_approval_escalations -----------------------------------------

    def test_approval_escalation_just_under_six_hours_is_not_escalated(self):
        with self.Session.begin() as session:
            approval = self.make_approval(session)
            session.flush()
            session.add(EscalationTracking(
                entity_type="project_external_approval", entity_id=approval.id, stage="followup",
                triggered_at=self.now - timedelta(hours=5, minutes=59),
            ))
        approval_id = approval.id

        with self.Session() as session:
            result = EscalationService(session).sweep_approval_escalations(self.now)
        self.assertEqual(result, [])

        with self.Session() as session:
            self.assertIsNone(self.open_tracking(session, "project_external_approval", approval_id, "admin_escalation"))
            followup = self.open_tracking(session, "project_external_approval", approval_id, "followup")
            self.assertIsNone(followup.resolved_at)

    def test_approval_escalation_at_six_hours_escalates(self):
        with self.Session.begin() as session:
            approval = self.make_approval(session)
            session.flush()
            session.add(EscalationTracking(
                entity_type="project_external_approval", entity_id=approval.id, stage="followup",
                triggered_at=self.now - timedelta(hours=6),
            ))
        approval_id = approval.id

        with self.Session() as session:
            result = EscalationService(session).sweep_approval_escalations(self.now)
        self.assertEqual([a.id for a in result], [approval_id])

        with self.Session() as session:
            admin_row = self.open_tracking(session, "project_external_approval", approval_id, "admin_escalation")
            self.assertIsNotNone(admin_row)
            events = self.outbox_events(session, "project_external_approval.escalated_to_admin", approval_id)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].aggregate_type, "project_external_approval")

    def test_approval_escalation_condition_cleared_resolves_without_escalating(self):
        with self.Session.begin() as session:
            approval = self.make_approval(session)
            session.flush()
            session.add(EscalationTracking(
                entity_type="project_external_approval", entity_id=approval.id, stage="followup",
                triggered_at=self.now - timedelta(hours=7),
            ))
            # The approval was submitted after the followup was triggered,
            # before the escalation sweep runs.
            approval.status = "submitted"
            session.add(approval)
        approval_id = approval.id

        with self.Session() as session:
            result = EscalationService(session).sweep_approval_escalations(self.now)
        self.assertEqual(result, [])

        with self.Session() as session:
            followup = self.open_tracking(session, "project_external_approval", approval_id, "followup")
            self.assertEqual(_aware(followup.resolved_at), self.now)
            self.assertIsNone(self.open_tracking(session, "project_external_approval", approval_id, "admin_escalation"))
            self.assertEqual(
                self.outbox_events(session, "project_external_approval.escalated_to_admin", approval_id), [],
            )

    def test_approval_escalation_is_idempotent_for_the_same_now(self):
        with self.Session.begin() as session:
            approval = self.make_approval(session)
            session.flush()
            session.add(EscalationTracking(
                entity_type="project_external_approval", entity_id=approval.id, stage="followup",
                triggered_at=self.now - timedelta(hours=6),
            ))
        approval_id = approval.id

        with self.Session() as session:
            first = EscalationService(session).sweep_approval_escalations(self.now)
        with self.Session() as session:
            second = EscalationService(session).sweep_approval_escalations(self.now)

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])

        with self.Session() as session:
            self.assertEqual(
                len(self.outbox_events(session, "project_external_approval.escalated_to_admin", approval_id)), 1,
            )


if __name__ == "__main__":
    unittest.main()
