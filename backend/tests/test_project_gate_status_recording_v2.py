"""U2: recording an external approval's outcome.

The authority rules are the point of this file. `not_required` is one of
the two statuses that stop a gate blocking, so a flat "may this actor
record outcomes?" guard would let any accountable PM release every task a
gate holds back, by setting a status that reads like paperwork.
"""
from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.database import get_db
from app.execution_models import (
    BaselineTask, ExecutionExcludedDependency, ExecutionGate, ExecutionGateDelegation,
    ExecutionGateStatusHistory, ExecutionGateTask, ProjectBaseline, Task, TaskDependency,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import (
    V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectExternalGateApplicabilityDecision,
    V2ProjectExternalGateTask, V2ProjectMembership, V2ProjectTask, V2ProjectTaskDependency,
)
from app.routes.execution_tasks_v2 import router as execution_router
from app.routes.projects_v2 import router as projects_router
from app.template_models import (
    V2Template, V2TemplateExternalGate, V2TemplateExternalGateTask,
    V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw): return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
OTHER_PM_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")
SUPER_ADMIN_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5")
EMPLOYEE_ID = uuid.UUID("ffffffff-ffff-4fff-8fff-fffffffffff6")
START = date(2026, 8, 1)


class GateStatusRecordingTests(unittest.TestCase):
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
                      BaselineTask.__table__, Task.__table__, TaskDependency.__table__,
                      V2TemplateExternalGate.__table__, V2TemplateExternalGateTask.__table__,
                      V2ProjectExternalGateTask.__table__, V2ProjectExternalGateApplicabilityDecision.__table__,
                      ExecutionGate.__table__, ExecutionGateTask.__table__, ExecutionExcludedDependency.__table__,
                      ExecutionGateStatusHistory.__table__, ExecutionGateDelegation.__table__):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()
        self.app = FastAPI()
        self.app.include_router(projects_router)
        self.app.include_router(execution_router)

        def override_db():
            with self.Session() as session: yield session

        self.app.dependency_overrides[get_db] = override_db
        self._actor = self.user(ADMIN_ID, UserRole.admin)
        self.app.dependency_overrides[current_user] = lambda: self._actor
        self.client = TestClient(self.app)
        self.project_id = self._activate()

    def tearDown(self): self.client.close(); self.engine.dispose()

    @staticmethod
    def user(user_id, role):
        return User(id=user_id, name=str(role), email=f"{user_id}@example.com", role=role, active=True)

    def act_as(self, user_id, role): self._actor = self.user(user_id, role)

    def _seed(self):
        with self.Session.begin() as session:
            session.add_all([
                self.user(ADMIN_ID, UserRole.admin), self.user(PM_ID, UserRole.project_manager),
                self.user(SUPERVISOR_ID, UserRole.supervisor), self.user(OTHER_PM_ID, UserRole.project_manager),
                self.user(SUPER_ADMIN_ID, UserRole.super_admin), self.user(EMPLOYEE_ID, UserRole.internal_employee),
            ])
            session.flush()
            session.add_all([
                EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                EmployeeProfile(user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor", availability="available"),
                EmployeeProfile(user_id=OTHER_PM_ID, employee_code="PM-002", designation="PM", availability="available"),
                EmployeeProfile(user_id=EMPLOYEE_ID, employee_code="EMP-001", designation="Fitter", availability="available"),
            ])
            template = V2Template(code="WORKVED-45", name="Workved 45 Day"); session.add(template); session.flush()
            published = V2TemplateVersion(template_id=template.id, version_no=1, status="published", duration_days=45,
                                          content_hash="h", is_current_published=True, created_by=ADMIN_ID,
                                          published_by=ADMIN_ID, published_at=datetime.now(timezone.utc))
            session.add(published); session.flush()
            tt = V2TemplateTask(template_version_id=published.id, code="T001", sequence_no=1, title="Task T001",
                                schedule_classification="execution", planned_start_day=1, planned_end_day=1,
                                applicability="mandatory", task_class="standard", task_kind="work",
                                evidence_required=False, duration_days=1, phase="Setup", category="Site")
            session.add(tt); session.flush()
            gate = V2TemplateExternalGate(template_version_id=published.id, code="E001", sequence_no=1,
                                          approval_name="Landlord approval", external_party="Landlord",
                                          mapping_classification="exact", required_by_type="project_day",
                                          required_by_value="5")
            session.add(gate); session.flush()
            session.add(V2TemplateExternalGateTask(gate_id=gate.id, template_task_id=tt.id))
            self.published_version_id = published.id

    def _activate(self):
        payload = {"project_name": "Futurex Fitout", "client": "Example Client", "location": "Mumbai",
                   "proposed_start_date": START.isoformat(), "target_handover_date": "2026-09-14",
                   "pm_user_id": str(PM_ID), "supervisor_user_id": str(SUPERVISOR_ID),
                   "template_version_id": str(self.published_version_id)}
        created = self.client.post("/api/v2/projects", json=payload)
        self.assertEqual(created.status_code, 201, created.text)
        pid = created.json()["id"]
        self.assertEqual(self.client.post(f"/api/v2/projects/{pid}/generate-tasks").status_code, 200)
        self.assertEqual(self.client.post(f"/api/v2/projects/{pid}/generate-gates").status_code, 200)
        with self.Session() as session:
            gate_id = session.scalar(select(V2ProjectExternalGate.id).where(
                V2ProjectExternalGate.project_id == uuid.UUID(pid)))
        self.assertEqual(self.client.post(
            f"/api/v2/projects/{pid}/gates/{gate_id}/applicability-decisions",
            json={"decision": "applicable"}).status_code, 200)
        self.assertEqual(self.client.post(f"/api/v2/projects/{pid}/activate",
                                          json={"reason": "Go live."}).status_code, 200)
        return pid

    @property
    def gate_id(self):
        with self.Session() as session:
            return session.scalar(select(ExecutionGate.id).where(
                ExecutionGate.project_id == uuid.UUID(self.project_id)))

    def gate(self):
        with self.Session() as session:
            return session.get(ExecutionGate, self.gate_id)

    def record(self, status, reason="Recorded by the accountable PM.", gate_id=None):
        return self.client.post(
            f"/api/v2/projects/{self.project_id}/execution-gates/{gate_id or self.gate_id}/status",
            json={"status": status, "reason": reason})

    def advance_to(self, status):
        """Walk the machine to `status` as an Admin, so a test can start
        from any state without asserting the path."""
        previous = self._actor
        self.act_as(ADMIN_ID, UserRole.admin)
        path = {"submitted": ["submitted"], "approved": ["submitted", "approved"],
                "rejected": ["submitted", "rejected"], "not_required": ["not_required"]}[status]
        for step in path:
            self.assertEqual(self.record(step, reason="Setup.").status_code, 200)
        self._actor = previous

    # ---- the happy path ---------------------------------------------------

    def test_admin_records_an_approval_with_history_and_audit(self):
        self.advance_to("submitted")
        self.act_as(ADMIN_ID, UserRole.admin)
        response = self.record("approved", reason="Landlord signed on site.")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "approved")

        gate = self.gate()
        self.assertEqual(gate.status, "approved")
        self.assertEqual(gate.status_recorded_by_user_id, ADMIN_ID)
        self.assertIsNotNone(gate.status_recorded_at)

        with self.Session() as session:
            history = session.scalars(select(ExecutionGateStatusHistory).order_by(
                ExecutionGateStatusHistory.recorded_at.asc())).all()
            self.assertEqual([(h.previous_status, h.new_status) for h in history],
                             [("pending_review", "submitted"), ("submitted", "approved")])
            self.assertEqual(history[-1].reason, "Landlord signed on site.")
            audit = session.scalars(select(V2AuditEvent).where(
                V2AuditEvent.action == "PROJECT_GATE_STATUS_RECORDED")).all()
            self.assertEqual(len(audit), 2)
            self.assertEqual(audit[-1].before_json["status"], "submitted")
            self.assertEqual(audit[-1].after_json["status"], "approved")

    def test_the_status_is_written_on_the_execution_row_not_the_planning_row(self):
        """KTD12. A status recorded on the planning gate would be invisible
        to readiness, so the approval would release nothing."""
        self.advance_to("submitted")
        self.act_as(ADMIN_ID, UserRole.admin)
        self.assertEqual(self.record("approved", reason="Signed.").status_code, 200)
        with self.Session() as session:
            planning = session.scalar(select(V2ProjectExternalGate))
            self.assertEqual(planning.status, "pending_review", "the planning row is a Draft-time snapshot")
            self.assertEqual(self.gate().status, "approved")

    def test_the_api_spelling_pending_is_accepted_but_never_stored(self):
        self.advance_to("not_required")
        self.act_as(ADMIN_ID, UserRole.admin)
        response = self.record("pending", reason="Back in scope after all.")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "pending_review")
        with self.Session() as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(ExecutionGateStatusHistory).where(
                    ExecutionGateStatusHistory.new_status == "pending")), 0)

    # ---- who may record what ----------------------------------------------

    def test_no_project_manager_can_record_an_outcome(self):
        """External approvals are Admin's responsibility. The accountable PM
        is named on the gate for escalation and visibility - that is not
        permission to assert what an external authority decided."""
        self.advance_to("submitted")
        # The accountable PM is a project member, so they clear the access
        # guard and are stopped by the authority rule itself.
        self.act_as(PM_ID, UserRole.project_manager)
        refused = self.record("approved", reason="Landlord signed.")
        self.assertEqual(refused.status_code, 403, refused.text)
        self.assertIn("Only Admin", refused.json()["detail"])
        self.assertEqual(self.gate().status, "submitted")

        # A PM from another project never reaches that rule - access stops
        # them first, which is the correct order.
        self.act_as(OTHER_PM_ID, UserRole.project_manager)
        self.assertEqual(self.record("approved", reason="Landlord signed.").status_code, 403)
        self.assertEqual(self.gate().status, "submitted")

    def test_an_admin_and_a_super_admin_may_both_record_an_outcome(self):
        """Super Admin is admitted everywhere Admin is - following `can_edit`
        in projects_v2, not the applicability service's `_require_decider`,
        which omits the role."""
        self.advance_to("submitted")
        self.act_as(ADMIN_ID, UserRole.admin)
        self.assertEqual(self.record("approved", reason="Recorded centrally.").status_code, 200)
        # Reopen, then let the Super Admin close it - one gate, no fixture reset.
        self.assertEqual(self.record("submitted", reason="Landlord superseded the letter.").status_code, 200)
        self.act_as(SUPER_ADMIN_ID, UserRole.super_admin)
        response = self.record("approved", reason="Recorded by Super Admin.")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.gate().status_recorded_by_user_id, SUPER_ADMIN_ID)

    def test_a_supervisor_and_an_internal_employee_are_refused(self):
        self.advance_to("submitted")
        for user_id, role in ((SUPERVISOR_ID, UserRole.supervisor), (EMPLOYEE_ID, UserRole.internal_employee)):
            with self.subTest(role=role):
                self.act_as(user_id, role)
                self.assertEqual(self.record("approved").status_code, 403)
                self.assertEqual(self.gate().status, "submitted")

    def test_nobody_but_admin_can_reach_not_required_in_either_direction(self):
        """The readiness bypass this guard exists to prevent: `not_required`
        stops the gate blocking, so setting it releases every task it holds."""
        self.act_as(PM_ID, UserRole.project_manager)
        refused = self.record("not_required", reason="Not needed here.")
        self.assertEqual(refused.status_code, 403, refused.text)
        self.assertIn("Only Admin", refused.json()["detail"])
        self.assertEqual(self.gate().status, "pending_review")

        self.advance_to("not_required")
        self.act_as(PM_ID, UserRole.project_manager)
        self.assertEqual(self.record("pending_review", reason="Back in scope.").status_code, 403)
        self.assertEqual(self.gate().status, "not_required")

    def test_an_admin_performs_both_not_required_transitions(self):
        self.act_as(ADMIN_ID, UserRole.admin)
        self.assertEqual(self.record("not_required", reason="Landlord waived it.").status_code, 200)
        self.assertEqual(self.gate().status, "not_required")
        self.assertEqual(self.record("pending_review", reason="Reinstated.").status_code, 200)
        self.assertEqual(self.gate().status, "pending_review")

    # ---- the state machine -------------------------------------------------

    def test_a_rejected_gate_cannot_go_straight_to_approved(self):
        """It must be resubmitted first, so the history shows the second
        submission rather than a silent reversal."""
        self.advance_to("rejected")
        self.act_as(ADMIN_ID, UserRole.admin)
        refused = self.record("approved", reason="They changed their mind.")
        self.assertEqual(refused.status_code, 422, refused.text)
        self.assertEqual(self.gate().status, "rejected")
        self.assertEqual(self.record("submitted", reason="Resubmitted with revised drawings.").status_code, 200)
        self.assertEqual(self.record("approved", reason="Approved on the second pass.").status_code, 200)

    def test_a_forbidden_transition_writes_no_history_row(self):
        self.act_as(ADMIN_ID, UserRole.admin)
        before = self.record("approved", reason="Skipping submission.")
        self.assertEqual(before.status_code, 422)
        with self.Session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(ExecutionGateStatusHistory)), 0)

    def test_recording_the_status_it_already_has_is_refused(self):
        self.act_as(ADMIN_ID, UserRole.admin)
        self.assertEqual(self.record("pending_review", reason="No change.").status_code, 409)

    def test_an_unknown_status_and_an_unknown_gate_are_refused(self):
        self.act_as(ADMIN_ID, UserRole.admin)
        self.assertEqual(self.record("maybe", reason="Made up.").status_code, 422)
        self.assertEqual(self.record("approved", gate_id=uuid.uuid4()).status_code, 404)

    def test_recording_an_outcome_without_a_reason_is_refused(self):
        self.act_as(ADMIN_ID, UserRole.admin)
        for reason in ("", "   "):
            with self.subTest(reason=repr(reason)):
                self.assertEqual(self.record("submitted", reason=reason).status_code, 422)

    # ---- the history read ---------------------------------------------------

    def test_a_rejection_reason_is_readable_by_any_project_member(self):
        """Covers AE6. The rejection reason is what a site team needs, so it
        is not gated behind the authority to record one."""
        self.advance_to("submitted")
        self.act_as(ADMIN_ID, UserRole.admin)
        self.assertEqual(self.record("rejected", reason="Fire strategy drawing missing.").status_code, 200)

        self.act_as(SUPERVISOR_ID, UserRole.supervisor)
        response = self.client.get(
            f"/api/v2/projects/{self.project_id}/execution-gates/{self.gate_id}/status-history")
        self.assertEqual(response.status_code, 200, response.text)
        entries = response.json()
        self.assertEqual(entries[-1]["new_status"], "rejected")
        self.assertEqual(entries[-1]["reason"], "Fire strategy drawing missing.")

    def test_a_non_member_is_refused_the_history(self):
        self.act_as(OTHER_PM_ID, UserRole.project_manager)
        response = self.client.get(
            f"/api/v2/projects/{self.project_id}/execution-gates/{self.gate_id}/status-history")
        self.assertEqual(response.status_code, 403, response.text)

    def test_the_gate_list_reports_the_current_status(self):
        self.advance_to("approved")
        self.act_as(SUPERVISOR_ID, UserRole.supervisor)
        response = self.client.get(f"/api/v2/projects/{self.project_id}/execution-gates")
        self.assertEqual(response.status_code, 200, response.text)
        rows = response.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["original_code"], "E001")
        self.assertEqual(rows[0]["status"], "approved")


if __name__ == "__main__":
    unittest.main()
