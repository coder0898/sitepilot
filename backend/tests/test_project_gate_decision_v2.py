"""U11: recording a decision against an execution-layer external approval.

What this file pins:

- Authority is the PM's, with Admin/Super Admin as the audited fallback -
  the same rule `TaskApprovalService._require_approver` already applies to
  task approvals. A Supervisor may see the approvals but may not decide one,
  and an Internal Employee may do neither.
- Rejection needs a reason, matching the task rejection rule.
- A decision is attributable: status, `decided_by` and `decided_at` all move
  together, which is exactly what the DB's
  `ck_v2_project_external_approvals_decision_completeness` check demands.
- A decided approval is final. Re-deciding is refused rather than silently
  overwriting who granted what.
- The listing feeds the Execution tab (U18): status, coverage and covered
  task ids for one project, and never another project's approvals.

The harness seeds rows directly rather than driving the activation flow -
this unit's subject is the decision, not instantiation (which
test_project_approval_instantiation_v2.py already covers), and seeding
directly lets the tests state the exact approval state under test.
"""

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
    BaselineTask,
    OutboxEvent,
    ProjectBaseline,
    ProjectExternalApproval,
    ProjectExternalApprovalTask,
    Task,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import (
    V2AuditEvent,
    V2Project,
    V2ProjectExternalGate,
    V2ProjectMembership,
)
from app.routes.execution_tasks_v2 import router as execution_tasks_router


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
INTERNAL_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")


class ProjectGateDecisionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            # V2ProjectExternalGate's broad-text check uses Postgres's btrim().
            dbapi_connection.create_function(
                "btrim", 1, lambda value: value.strip() if value is not None else None
            )

        for table in (
            User.__table__,
            EmployeeProfile.__table__,
            V2Project.__table__,
            V2ProjectMembership.__table__,
            V2ProjectExternalGate.__table__,
            V2AuditEvent.__table__,
            ProjectBaseline.__table__,
            BaselineTask.__table__,
            Task.__table__,
            ProjectExternalApproval.__table__,
            ProjectExternalApprovalTask.__table__,
            OutboxEvent.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._sequence = 0
        self._seed()

        self.app = FastAPI()
        self.app.include_router(execution_tasks_router)

        def override_db():
            with self.Session() as session:
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self._current_actor = self.admin_user()
        self.app.dependency_overrides[current_user] = lambda: self._current_actor
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    # ---- actors ---------------------------------------------------------

    def admin_user(self) -> User:
        return User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)

    def pm_user(self) -> User:
        return User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True)

    def supervisor_user(self) -> User:
        return User(
            id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com",
            role=UserRole.supervisor, active=True,
        )

    def internal_user(self) -> User:
        return User(
            id=INTERNAL_ID, name="Internal", email="internal@example.com",
            role=UserRole.internal_employee, active=True,
        )

    def act_as(self, user: User) -> None:
        self._current_actor = user

    # ---- seeding --------------------------------------------------------

    def _seed(self) -> None:
        with self.Session.begin() as session:
            session.add_all([
                self.admin_user(), self.pm_user(), self.supervisor_user(), self.internal_user(),
            ])
            session.flush()
            profiles = {
                PM_ID: EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                SUPERVISOR_ID: EmployeeProfile(
                    user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor",
                    availability="available",
                ),
                INTERNAL_ID: EmployeeProfile(
                    user_id=INTERNAL_ID, employee_code="INT-001", designation="Internal Employee",
                    availability="available",
                ),
            }
            session.add_all(profiles.values())
            session.flush()

            self.project_id = uuid.uuid4()
            self.other_project_id = uuid.uuid4()
            for index, project_id in enumerate((self.project_id, self.other_project_id), start=1):
                session.add(V2Project(
                    id=project_id, code=f"P00{index}", name=f"Project {index}", client_name="Client",
                    site_address="Somewhere", start_date=date(2026, 8, 1), status="active",
                    created_by=ADMIN_ID,
                ))
            session.flush()

            for user_id, project_role in (
                (PM_ID, "project_manager"),
                (SUPERVISOR_ID, "site_supervisor"),
                (INTERNAL_ID, "internal_employee"),
            ):
                # Membership on both projects, so a 403 in a cross-project
                # test is never just an access accident.
                for project_id in (self.project_id, self.other_project_id):
                    session.add(V2ProjectMembership(
                        project_id=project_id, employee_id=profiles[user_id].id,
                        project_role=project_role, assigned_by=ADMIN_ID,
                        assignment_reason="Seeded for tests.",
                    ))

            self.baseline_ids = {}
            for project_id in (self.project_id, self.other_project_id):
                baseline_id = uuid.uuid4()
                session.add(ProjectBaseline(
                    # `ck_v2_project_baselines_task_count_positive` - a
                    # baseline with no tasks is not a real baseline.
                    id=baseline_id, project_id=project_id, task_count=1,
                    dependency_count=0, gate_count=0, locked_by=ADMIN_ID,
                ))
                self.baseline_ids[project_id] = baseline_id
            session.flush()

    def _task(self, session, project_id: uuid.UUID) -> Task:
        """One execution task for an approval to cover. No planning-layer
        `V2ProjectTask` behind it: this unit never reads the planning tasks,
        and SQLite does not enforce the foreign key, so a bare id satisfies
        `BaselineTask.project_task_id` without the extra fixture."""
        self._sequence += 1
        code = f"T{self._sequence:03d}"
        baseline_id = self.baseline_ids[project_id]
        baseline_task = BaselineTask(
            id=uuid.uuid4(), baseline_id=baseline_id, project_id=project_id,
            project_task_id=uuid.uuid4(), original_code=code, template_sequence=self._sequence,
            title=f"Task {code}", schedule_classification="execution", applicability="mandatory",
            content_hash="hash",
        )
        session.add(baseline_task)
        session.flush()
        task = Task(
            id=uuid.uuid4(), project_id=project_id, baseline_id=baseline_id,
            baseline_task_id=baseline_task.id, original_code=code,
            template_sequence=self._sequence, title=f"Task {code}",
            schedule_classification="execution", applicability="mandatory",
            lifecycle_status="planned",
        )
        session.add(task)
        session.flush()
        return task

    def make_approval(
        self,
        project_id: uuid.UUID | None = None,
        *,
        status: str = "pending",
        blocking: bool = True,
        coverage_state: str = "exact",
        coverage_text: str | None = None,
        covered_task_count: int = 0,
        decided_by: uuid.UUID | None = None,
    ) -> dict:
        """Seeds one gate + its execution-layer approval, returning plain
        values (not ORM instances) so assertions never depend on a session
        that has since closed."""
        project_id = project_id or self.project_id
        with self.Session.begin() as session:
            self._sequence += 1
            gate = V2ProjectExternalGate(
                id=uuid.uuid4(), project_id=project_id,
                original_code=f"E{self._sequence:03d}", template_sequence=self._sequence,
                approval_name=f"Fire NOC {self._sequence}",
                mapping_classification="exact" if coverage_state == "exact" else "broad_text",
                broad_mapping_text=coverage_text,
                applicability_state="applicable", blocking=blocking,
                accountable_pm_user_id=PM_ID, source_type="project_manual",
            )
            session.add(gate)
            session.flush()
            approval = ProjectExternalApproval(
                id=uuid.uuid4(), project_id=project_id, project_gate_id=gate.id,
                status=status, blocking=blocking, coverage_state=coverage_state,
                coverage_text=coverage_text,
                decided_by=decided_by,
                decided_at=datetime.now(timezone.utc) if decided_by else None,
            )
            session.add(approval)
            session.flush()
            task_ids = []
            for _ in range(covered_task_count):
                task = self._task(session, project_id)
                session.add(ProjectExternalApprovalTask(
                    project_id=project_id, approval_id=approval.id, task_id=task.id,
                ))
                task_ids.append(task.id)
            session.flush()
            return {
                "id": approval.id,
                "gate_id": gate.id,
                "gate_code": gate.original_code,
                "gate_name": gate.approval_name,
                "project_id": project_id,
                "task_ids": task_ids,
            }

    # ---- requests -------------------------------------------------------

    def decide(self, approval: dict, decision: str, reason: str | None = None, project_id=None):
        body: dict = {"decision": decision}
        if reason is not None:
            body["reason"] = reason
        target = project_id or approval["project_id"]
        return self.client.post(
            f"/api/v2/projects/{target}/external-approvals/{approval['id']}/decision", json=body,
        )

    def listing(self, project_id=None):
        return self.client.get(f"/api/v2/projects/{project_id or self.project_id}/external-approvals")

    def stored(self, approval: dict) -> ProjectExternalApproval:
        with self.Session() as session:
            return session.get(ProjectExternalApproval, approval["id"])

    # ---- who may decide -------------------------------------------------

    def test_the_projects_pm_can_approve_a_pending_approval(self):
        approval = self.make_approval()
        self.act_as(self.pm_user())
        response = self.decide(approval, "approved")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "approved")
        self.assertEqual(self.stored(approval).status, "approved")

    def test_an_admin_can_approve_a_pending_approval(self):
        approval = self.make_approval()
        self.act_as(self.admin_user())
        response = self.decide(approval, "approved")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.stored(approval).status, "approved")

    def test_a_supervisor_cannot_approve(self):
        approval = self.make_approval()
        self.act_as(self.supervisor_user())
        response = self.decide(approval, "approved")
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.stored(approval).status, "pending")

    def test_an_internal_employee_cannot_approve(self):
        approval = self.make_approval()
        self.act_as(self.internal_user())
        response = self.decide(approval, "approved")
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.stored(approval).status, "pending")

    # ---- the decision itself --------------------------------------------

    def test_rejection_without_a_reason_is_refused(self):
        approval = self.make_approval()
        self.act_as(self.pm_user())
        response = self.decide(approval, "rejected")
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.stored(approval).status, "pending")

    def test_a_blank_reason_does_not_count_as_a_reason(self):
        approval = self.make_approval()
        self.act_as(self.pm_user())
        response = self.decide(approval, "rejected", reason="   ")
        self.assertEqual(response.status_code, 422, response.text)

    def test_rejection_with_a_reason_is_recorded(self):
        approval = self.make_approval()
        self.act_as(self.pm_user())
        response = self.decide(approval, "rejected", reason="Fire NOC refused by the authority.")
        self.assertEqual(response.status_code, 200, response.text)
        row = self.stored(approval)
        self.assertEqual(row.status, "rejected")
        self.assertEqual(row.decided_by, PM_ID)

    def test_a_decision_records_the_deciding_user_and_the_time(self):
        approval = self.make_approval()
        before = datetime.now(timezone.utc)
        self.act_as(self.pm_user())
        self.assertEqual(self.decide(approval, "approved").status_code, 200)

        row = self.stored(approval)
        self.assertEqual(row.decided_by, PM_ID)
        self.assertIsNotNone(row.decided_at)
        decided_at = row.decided_at
        if decided_at.tzinfo is None:
            decided_at = decided_at.replace(tzinfo=timezone.utc)
        self.assertGreaterEqual(decided_at, before.replace(microsecond=0))

    def test_a_decision_writes_an_audit_event_and_emits_an_outbox_event(self):
        approval = self.make_approval()
        self.act_as(self.pm_user())
        self.assertEqual(self.decide(approval, "approved").status_code, 200)

        with self.Session() as session:
            audit = session.scalars(
                select(V2AuditEvent).where(V2AuditEvent.entity_id == approval["id"])
            ).all()
            self.assertEqual(len(audit), 1, "exactly one audit event per decision")
            self.assertEqual(audit[0].entity_type, "project_external_approval")
            self.assertEqual(audit[0].actor_user_id, PM_ID)
            self.assertEqual(audit[0].project_id, self.project_id)
            self.assertEqual(audit[0].before_json.get("status"), "pending")
            self.assertEqual(audit[0].after_json.get("status"), "approved")

            events = session.scalars(
                select(OutboxEvent).where(OutboxEvent.aggregate_id == approval["id"])
            ).all()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event_type, "project_external_approval.decided")
            self.assertEqual(events[0].payload["decision"], "approved")
            self.assertEqual(events[0].payload["decided_by"], str(PM_ID))

    def test_deciding_on_an_already_decided_approval_is_refused(self):
        approval = self.make_approval(status="approved", decided_by=ADMIN_ID)
        self.act_as(self.pm_user())
        response = self.decide(approval, "rejected", reason="Changed my mind.")
        self.assertEqual(response.status_code, 409, response.text)
        row = self.stored(approval)
        self.assertEqual(row.status, "approved")
        self.assertEqual(row.decided_by, ADMIN_ID)

    def test_an_unknown_decision_is_refused(self):
        approval = self.make_approval()
        self.act_as(self.pm_user())
        self.assertIn(self.decide(approval, "maybe").status_code, (400, 422))

    def test_an_approval_from_another_project_is_not_decidable_through_this_project(self):
        approval = self.make_approval(self.other_project_id)
        self.act_as(self.pm_user())
        response = self.decide(approval, "approved", project_id=self.project_id)
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(self.stored(approval).status, "pending")

    def test_a_decision_does_not_touch_coverage(self):
        """`ck_v2_project_external_approvals_coverage_text` only permits prose
        on an unresolved approval - a decision must leave both alone."""
        approval = self.make_approval(
            coverage_state="unresolved", coverage_text="All procurement activities",
        )
        self.act_as(self.pm_user())
        self.assertEqual(self.decide(approval, "approved").status_code, 200)
        row = self.stored(approval)
        self.assertEqual(row.coverage_state, "unresolved")
        self.assertEqual(row.coverage_text, "All procurement activities")

    # ---- the listing ----------------------------------------------------

    def test_the_listing_returns_status_coverage_state_and_covered_task_ids(self):
        approval = self.make_approval(covered_task_count=2)
        self.act_as(self.pm_user())
        response = self.listing()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body), 1)
        item = body[0]
        self.assertEqual(item["id"], str(approval["id"]))
        self.assertEqual(item["gate_code"], approval["gate_code"])
        self.assertEqual(item["gate_name"], approval["gate_name"])
        self.assertEqual(item["status"], "pending")
        self.assertTrue(item["blocking"])
        self.assertEqual(item["coverage_state"], "exact")
        self.assertIsNone(item["coverage_text"])
        self.assertIsNone(item["decided_by"])
        self.assertIsNone(item["decided_at"])
        self.assertEqual(
            sorted(item["covered_task_ids"]), sorted(str(t) for t in approval["task_ids"]),
        )

    def test_the_listing_carries_unresolved_coverage_prose(self):
        self.make_approval(coverage_state="unresolved", coverage_text="Anything touching the facade")
        self.act_as(self.pm_user())
        item = self.listing().json()[0]
        self.assertEqual(item["coverage_state"], "unresolved")
        self.assertEqual(item["coverage_text"], "Anything touching the facade")
        self.assertEqual(item["covered_task_ids"], [])

    def test_the_listing_does_not_leak_another_projects_approvals(self):
        mine = self.make_approval(self.project_id)
        self.make_approval(self.other_project_id)
        self.act_as(self.pm_user())
        body = self.listing(self.project_id).json()
        self.assertEqual([item["id"] for item in body], [str(mine["id"])])

    def test_the_listing_shows_a_recorded_decision(self):
        approval = self.make_approval()
        self.act_as(self.pm_user())
        self.assertEqual(self.decide(approval, "approved").status_code, 200)
        item = self.listing().json()[0]
        self.assertEqual(item["status"], "approved")
        self.assertEqual(item["decided_by"], str(PM_ID))
        self.assertIsNotNone(item["decided_at"])

    def test_a_supervisor_may_read_the_listing_even_though_they_cannot_decide(self):
        """Reading which approvals block the site is part of the Supervisor's
        job; deciding them is not."""
        self.make_approval()
        self.act_as(self.supervisor_user())
        self.assertEqual(self.listing().status_code, 200)

    def test_a_non_member_cannot_read_the_listing(self):
        self.make_approval()
        self.act_as(User(
            id=uuid.uuid4(), name="Outsider", email="outsider@example.com",
            role=UserRole.supervisor, active=True,
        ))
        self.assertEqual(self.listing().status_code, 403)


if __name__ == "__main__":
    unittest.main()
