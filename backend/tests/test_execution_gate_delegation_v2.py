"""U13: Admin delegates the chasing of an external approval.

The authority split is the whole point. External approvals are Admin's
responsibility, so Admin alone records what an external authority decided.
Chasing one is legwork, so Admin hands that to an Internal Employee - who
may then say "I lodged it", and nothing more.
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
SUPER_ADMIN_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5")
EMPLOYEE_ID = uuid.UUID("ffffffff-ffff-4fff-8fff-fffffffffff6")
OTHER_EMPLOYEE_ID = uuid.UUID("abcdefab-cdef-4bcd-8bcd-abcdefabcde7")
UNASSIGNED_EMPLOYEE_ID = uuid.UUID("bcdefabc-defa-4cde-8cde-bcdefabcdef8")
START = date(2026, 8, 1)


class ExecutionGateDelegationTests(unittest.TestCase):
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
                self.user(SUPERVISOR_ID, UserRole.supervisor), self.user(SUPER_ADMIN_ID, UserRole.super_admin),
                self.user(EMPLOYEE_ID, UserRole.internal_employee),
                self.user(OTHER_EMPLOYEE_ID, UserRole.internal_employee),
                self.user(UNASSIGNED_EMPLOYEE_ID, UserRole.internal_employee),
            ])
            session.flush()
            for user_id, code in ((PM_ID, "PM-001"), (SUPERVISOR_ID, "SUP-001"), (EMPLOYEE_ID, "EMP-001"),
                                  (OTHER_EMPLOYEE_ID, "EMP-002"), (UNASSIGNED_EMPLOYEE_ID, "EMP-003")):
                session.add(EmployeeProfile(user_id=user_id, employee_code=code, designation="Staff", availability="available"))
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
        # Both Internal Employees are project members; the third deliberately is not.
        with self.Session.begin() as session:
            for user_id in (EMPLOYEE_ID, OTHER_EMPLOYEE_ID):
                employee_id = session.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == user_id))
                session.add(V2ProjectMembership(
                    project_id=uuid.UUID(pid), employee_id=employee_id, project_role="internal_employee",
                    assigned_by=ADMIN_ID, assignment_reason="Approval chasing."))
        return pid

    # ---- helpers ----------------------------------------------------------

    @property
    def gate_id(self):
        with self.Session() as session:
            return session.scalar(select(ExecutionGate.id).where(
                ExecutionGate.project_id == uuid.UUID(self.project_id)))

    def gate(self):
        with self.Session() as session:
            return session.get(ExecutionGate, self.gate_id)

    def employee_id_for(self, user_id):
        with self.Session() as session:
            return session.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == user_id))

    def delegate(self, user_id=EMPLOYEE_ID, instruction="Chase the landlord for the signed letter."):
        return self.client.post(
            f"/api/v2/projects/{self.project_id}/execution-gates/{self.gate_id}/delegations",
            json={"employee_id": str(self.employee_id_for(user_id)), "instruction": instruction})

    def record(self, status, reason="Recorded."):
        return self.client.post(
            f"/api/v2/projects/{self.project_id}/execution-gates/{self.gate_id}/status",
            json={"status": status, "reason": reason})

    # ---- who may delegate --------------------------------------------------

    def test_admin_delegates_an_approval_to_an_internal_employee(self):
        response = self.delegate()
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["status"], "active")
        self.assertEqual(body["instruction"], "Chase the landlord for the signed letter.")
        self.assertIsNone(body["ends_at"])

        with self.Session() as session:
            audit = session.scalar(select(V2AuditEvent).where(V2AuditEvent.action == "PROJECT_GATE_DELEGATED"))
            self.assertIsNotNone(audit)
            self.assertEqual(audit.reason, "Chase the landlord for the signed letter.")

    def test_a_super_admin_may_delegate_too(self):
        self.act_as(SUPER_ADMIN_ID, UserRole.super_admin)
        self.assertEqual(self.delegate().status_code, 201)

    def test_a_pm_supervisor_and_internal_employee_cannot_delegate(self):
        """Delegating is an act of ownership, and external approvals are
        Admin's to own."""
        for user_id, role in ((PM_ID, UserRole.project_manager), (SUPERVISOR_ID, UserRole.supervisor),
                              (EMPLOYEE_ID, UserRole.internal_employee)):
            with self.subTest(role=role):
                self.act_as(user_id, role)
                refused = self.delegate()
                self.assertEqual(refused.status_code, 403, refused.text)
                self.assertIn("Only Admin", refused.json()["detail"])

    def test_the_delegate_must_be_an_active_internal_employee_on_this_project(self):
        refused = self.delegate(UNASSIGNED_EMPLOYEE_ID)
        self.assertEqual(refused.status_code, 422, refused.text)
        self.assertIn("not an active Internal Employee member", refused.json()["detail"])

    def test_a_pm_cannot_be_made_a_delegate(self):
        """Chasing an approval is Internal Employee work. The PM is already
        named on the gate as the person the delay lands on."""
        refused = self.delegate(PM_ID)
        self.assertEqual(refused.status_code, 422, refused.text)
        self.assertIn("active Internal Employee", refused.json()["detail"])

    def test_delegating_the_same_employee_twice_is_refused(self):
        self.assertEqual(self.delegate().status_code, 201)
        self.assertEqual(self.delegate().status_code, 409)

    def test_two_different_employees_may_chase_the_same_approval(self):
        self.assertEqual(self.delegate(EMPLOYEE_ID).status_code, 201)
        self.assertEqual(self.delegate(OTHER_EMPLOYEE_ID).status_code, 201)

    def test_an_instruction_is_required(self):
        for instruction in ("", "   "):
            with self.subTest(instruction=repr(instruction)):
                self.assertEqual(self.delegate(instruction=instruction).status_code, 422)

    def test_delegation_never_moves_accountability(self):
        """The gate's accountable PM is untouched - a delegate chases, the
        PM is who escalation still reaches."""
        before = self.gate().accountable_pm_user_id
        self.assertEqual(self.delegate().status_code, 201)
        self.assertEqual(self.gate().accountable_pm_user_id, before)
        self.assertEqual(before, PM_ID)

    # ---- what a delegate may then do ---------------------------------------

    def test_a_delegate_records_submission_and_resubmission(self):
        self.assertEqual(self.delegate().status_code, 201)
        self.act_as(EMPLOYEE_ID, UserRole.internal_employee)
        submitted = self.record("submitted", reason="Lodged with the landlord's agent on Tuesday.")
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.assertEqual(self.gate().status, "submitted")

        self.act_as(ADMIN_ID, UserRole.admin)
        self.assertEqual(self.record("rejected", reason="Drawings missing.").status_code, 200)

        self.act_as(EMPLOYEE_ID, UserRole.internal_employee)
        resubmitted = self.record("submitted", reason="Re-lodged with the fire strategy attached.")
        self.assertEqual(resubmitted.status_code, 200, resubmitted.text)

    def test_a_delegate_cannot_approve_or_reject(self):
        """The line: "I lodged it" is theirs to state, "the landlord
        approved" is not."""
        self.assertEqual(self.delegate().status_code, 201)
        self.act_as(EMPLOYEE_ID, UserRole.internal_employee)
        self.assertEqual(self.record("submitted", reason="Lodged.").status_code, 200)
        for outcome in ("approved", "rejected"):
            with self.subTest(outcome=outcome):
                refused = self.record(outcome, reason="The landlord said so.")
                self.assertEqual(refused.status_code, 403, refused.text)
                self.assertIn("Only Admin", refused.json()["detail"])
                self.assertEqual(self.gate().status, "submitted")

    def test_a_delegate_cannot_reach_not_required(self):
        self.assertEqual(self.delegate().status_code, 201)
        self.act_as(EMPLOYEE_ID, UserRole.internal_employee)
        self.assertEqual(self.record("not_required", reason="Seems unnecessary.").status_code, 403)
        self.assertEqual(self.gate().status, "pending_review")

    def test_an_internal_employee_who_is_not_delegated_cannot_record_anything(self):
        self.act_as(OTHER_EMPLOYEE_ID, UserRole.internal_employee)
        refused = self.record("submitted", reason="Lodged it myself.")
        self.assertEqual(refused.status_code, 403, refused.text)
        self.assertEqual(self.gate().status, "pending_review")

    def test_ending_a_delegation_removes_the_ability_to_record(self):
        created = self.delegate()
        self.assertEqual(created.status_code, 201)
        delegation_id = created.json()["id"]

        ended = self.client.post(
            f"/api/v2/projects/{self.project_id}/execution-gates/{self.gate_id}/delegations/{delegation_id}/end",
            json={"reason": "Handed to the site team."})
        self.assertEqual(ended.status_code, 200, ended.text)
        self.assertEqual(ended.json()["status"], "ended")
        self.assertIsNotNone(ended.json()["ends_at"])

        self.act_as(EMPLOYEE_ID, UserRole.internal_employee)
        self.assertEqual(self.record("submitted", reason="Lodged.").status_code, 403)

    def test_only_admin_can_end_a_delegation(self):
        delegation_id = self.delegate().json()["id"]
        self.act_as(PM_ID, UserRole.project_manager)
        refused = self.client.post(
            f"/api/v2/projects/{self.project_id}/execution-gates/{self.gate_id}/delegations/{delegation_id}/end",
            json={"reason": "Taking it back."})
        self.assertEqual(refused.status_code, 403, refused.text)

    def test_ending_an_already_ended_delegation_is_refused(self):
        delegation_id = self.delegate().json()["id"]
        url = f"/api/v2/projects/{self.project_id}/execution-gates/{self.gate_id}/delegations/{delegation_id}/end"
        self.assertEqual(self.client.post(url, json={"reason": "Done."}).status_code, 200)
        self.assertEqual(self.client.post(url, json={"reason": "Again."}).status_code, 409)

    # ---- reading -----------------------------------------------------------

    def test_any_project_member_can_see_who_is_chasing_an_approval(self):
        """Exactly what a PM watching their handover date needs to know."""
        self.assertEqual(self.delegate().status_code, 201)
        self.act_as(PM_ID, UserRole.project_manager)
        response = self.client.get(
            f"/api/v2/projects/{self.project_id}/execution-gates/{self.gate_id}/delegations")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["instruction"], "Chase the landlord for the signed letter.")

    def test_an_ended_delegation_stays_on_the_record(self):
        delegation_id = self.delegate().json()["id"]
        self.client.post(
            f"/api/v2/projects/{self.project_id}/execution-gates/{self.gate_id}/delegations/{delegation_id}/end",
            json={"reason": "Reassigned."})
        rows = self.client.get(
            f"/api/v2/projects/{self.project_id}/execution-gates/{self.gate_id}/delegations").json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "ended")
        self.assertEqual(rows[0]["end_reason"], "Reassigned.")
        with self.Session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(V2AuditEvent).where(
                V2AuditEvent.action == "PROJECT_GATE_DELEGATION_ENDED")), 1)


if __name__ == "__main__":
    unittest.main()
