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
from app.models import EmployeeProfile, User, UserRole
from app.project_models import (
    V2AuditEvent,
    V2Project,
    V2ProjectExternalGate,
    V2ProjectExternalGateApplicabilityDecision,
    V2ProjectExternalGateTask,
    V2ProjectMembership,
    V2ProjectTask,
)
from app.execution_models import (
    BaselineTask,
    ProjectBaseline,
    ProjectExternalApproval,
    ProjectExternalApprovalTask,
    Task,
)
from app.routes.projects_v2 import router
from app.template_models import V2Template, V2TemplateExternalGate, V2TemplateTask, V2TemplateVersion


@compiles(JSONB, "sqlite")
def jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
OTHER_PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb3")
SUPERVISOR_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")
PM_EMP = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")


class ProjectGateApplicabilityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach(conn, _):
            conn.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            conn.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)

        tables = [
            User.__table__,
            EmployeeProfile.__table__,
            V2Template.__table__,
            V2TemplateVersion.__table__,
            V2TemplateTask.__table__,
            V2TemplateExternalGate.__table__,
            V2Project.__table__,
            V2ProjectMembership.__table__,
            V2ProjectTask.__table__,
            V2ProjectExternalGate.__table__,
            V2ProjectExternalGateTask.__table__,
            V2ProjectExternalGateApplicabilityDecision.__table__,
            V2AuditEvent.__table__,
            # Deciding a gate on an ACTIVE project now instantiates its
            # runtime approval in the same transaction, so this harness needs
            # the execution layer that instantiation reads and writes.
            ProjectBaseline.__table__,
            BaselineTask.__table__,
            Task.__table__,
            ProjectExternalApproval.__table__,
            ProjectExternalApprovalTask.__table__,
        ]
        for table in tables:
            table.create(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.users = self._seed()
        self.actor = self.users["admin"]
        app = FastAPI()
        app.include_router(router)

        def db_override():
            with self.Session() as session:
                yield session

        app.dependency_overrides[get_db] = db_override
        app.dependency_overrides[current_user] = lambda: self.actor
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def _seed(self):
        users = {
            "admin": User(id=ADMIN_ID, name="Admin", email="admin@test", role=UserRole.admin, active=True),
            "pm": User(id=PM_ID, name="Assigned PM", email="pm@test", role=UserRole.project_manager, active=True),
            "other_pm": User(id=OTHER_PM_ID, name="Other PM", email="other@test", role=UserRole.project_manager, active=True),
            "supervisor": User(id=SUPERVISOR_ID, name="Supervisor", email="sup@test", role=UserRole.supervisor, active=True),
        }
        with self.Session.begin() as session:
            session.add_all(users.values())
            session.add(EmployeeProfile(id=PM_EMP, user_id=PM_ID, employee_code="PM1", designation="PM", availability="available"))
            template = V2Template(code="W45", name="Workved")
            session.add(template)
            session.flush()
            version = V2TemplateVersion(
                template_id=template.id,
                version_no=1,
                status="published",
                duration_days=45,
                content_hash="gate-applicability-test",
                is_current_published=True,
                created_by=ADMIN_ID,
                published_by=ADMIN_ID,
                published_at=datetime.now(timezone.utc),
            )
            session.add(version)
            session.flush()
            source_gate = V2TemplateExternalGate(
                template_version_id=version.id,
                code="E001",
                approval_name="Society approval",
                mapping_classification="unmapped",
                requires_configuration=True,
                sequence_no=1,
            )
            session.add(source_gate)
            source_task = V2TemplateTask(
                template_version_id=version.id, code="T001", sequence_no=1, title="Task",
                schedule_classification="pre_activation", applicability="mandatory", evidence_required=False,
            )
            session.add(source_task)
            session.flush()
            project = V2Project(
                code="PRJ1",
                name="Project",
                client_name="Client",
                site_address="Mumbai",
                start_date=date(2026, 8, 1),
                template_version_id=version.id,
                status="draft",
                created_by=ADMIN_ID,
            )
            session.add(project)
            session.flush()
            session.add(V2ProjectTask(
                project_id=project.id, template_version_id=version.id, template_task_id=source_task.id,
                original_code="T001", template_sequence=1, title="Task", schedule_classification="pre_activation",
                applicability="mandatory", source_type="template", lifecycle_status="draft", included=True,
                decision_state="pending_review",
            ))
            session.add(V2ProjectMembership(
                project_id=project.id,
                employee_id=PM_EMP,
                project_role="project_manager",
                assigned_by=ADMIN_ID,
                assignment_reason="Owner",
            ))
            gate = V2ProjectExternalGate(
                project_id=project.id,
                template_version_id=version.id,
                template_gate_id=source_gate.id,
                original_code="E001",
                template_sequence=1,
                approval_name="Society approval",
                mapping_classification="unmapped",
                requires_configuration=True,
                status="pending_review",
                applicability_state="pending_review",
                source_type="template",
                accountable_pm_user_id=PM_ID,
            )
            session.add(gate)
            session.flush()
            self.project_id = project.id
            self.gate_id = gate.id
            self.template_version_id = version.id
        return users

    def decide(self, decision, reason=None):
        body = {"decision": decision}
        if reason is not None:
            body["reason"] = reason
        return self.client.post(
            f"/api/v2/projects/{self.project_id}/gates/{self.gate_id}/applicability-decisions",
            json=body,
        )

    def test_applicable_decision_records_actor_time_and_keeps_gate(self):
        response = self.decide("applicable")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["applicability_state"], "applicable")
        with self.Session() as session:
            gate = session.get(V2ProjectExternalGate, self.gate_id)
            self.assertIsNotNone(gate)
            self.assertEqual(gate.applicability_state, "applicable")
            decision = session.scalar(select(V2ProjectExternalGateApplicabilityDecision))
            self.assertEqual(decision.actor_user_id, ADMIN_ID)
            self.assertTrue(decision.decided_at)
            self.assertEqual(decision.reason, "Gate confirmed applicable.")

    def test_not_applicable_requires_reason_and_does_not_delete_gate(self):
        missing = self.decide("not_applicable", "  ")
        self.assertEqual(missing.status_code, 422, missing.text)
        response = self.decide("not_applicable", "Approval not needed for this site.")
        self.assertEqual(response.status_code, 200, response.text)
        with self.Session() as session:
            gate = session.get(V2ProjectExternalGate, self.gate_id)
            self.assertIsNotNone(gate)
            self.assertEqual(gate.applicability_state, "not_applicable")
            self.assertEqual(session.scalar(select(func.count()).select_from(V2ProjectExternalGate)), 1)

    def test_history_is_append_only_newest_first(self):
        self.assertEqual(self.decide("not_applicable", "Not needed").status_code, 200)
        self.assertEqual(self.decide("applicable", "Requirement restored").status_code, 200)
        response = self.client.get(
            f"/api/v2/projects/{self.project_id}/gates/{self.gate_id}/applicability-decisions"
        )
        self.assertEqual(response.status_code, 200, response.text)
        history = response.json()
        self.assertEqual([item["decision"] for item in history], ["applicable", "not_applicable"])
        self.assertEqual(history[0]["previous_state"], "not_applicable")
        self.assertEqual(history[0]["actor_name"], "Admin")
        with self.Session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(V2ProjectExternalGateApplicabilityDecision)), 2)
            self.assertEqual(session.scalar(select(func.count()).select_from(V2AuditEvent).where(V2AuditEvent.action == "PROJECT_GATE_APPLICABILITY_DECIDED")), 2)

    def test_no_role_other_than_admin_can_decide_gate_applicability(self):
        """Whether an external approval applies is Admin's call. The assigned
        PM still reads the gate list; they just cannot decide it."""
        self.actor = self.users["pm"]
        response = self.decide("applicable", "PM confirmed")
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("Only Admin", response.json()["detail"])
        users_extra = {
            "super_admin": User(id=uuid.uuid4(), name="Super Admin", email="sa@test", role=UserRole.super_admin, active=True),
            "internal": User(id=uuid.uuid4(), name="Internal", email="int@test", role=UserRole.internal_employee, active=True),
        }
        for role, user in users_extra.items():
            self.users[role] = user
        for role in ("other_pm", "supervisor", "super_admin", "internal"):
            with self.subTest(role=role):
                self.actor = self.users[role]
                self.assertEqual(self.decide("not_applicable", "Denied").status_code, 403)

    def test_deciding_on_an_active_project_leaves_tasks_and_template_untouched(self):
        """Applicability used to be Draft-only, which left a one-way door:
        activation never required the gates to be reviewed, so a project could
        go live with every gate `pending_review` and then nobody could ever
        decide them - and since approvals are instantiated only from
        APPLICABLE gates, such a project could never have an external approval
        at all. The decision is now permitted on an active project; what must
        still never happen is this decision reaching back into the template or
        the project's task applicability.
        """
        with self.Session.begin() as session:
            session.get(V2Project, self.project_id).status = "active"

        response = self.decide("applicable", "Confirmed on site")
        self.assertEqual(response.status_code, 200, response.text)

        with self.Session() as session:
            gate = session.get(V2ProjectExternalGate, self.gate_id)
            source = session.get(V2TemplateExternalGate, gate.template_gate_id)
            self.assertEqual(gate.applicability_state, "applicable")
            # The template is shared across every project and must never be
            # touched by one project's decision.
            self.assertEqual(source.mapping_classification, "unmapped")
            task = session.scalar(select(V2ProjectTask).where(V2ProjectTask.project_id == self.project_id))
            self.assertTrue(task.included)
            self.assertEqual(task.decision_state, "pending_review")

    def test_an_active_projects_gate_gets_its_runtime_approval_immediately(self):
        """A decision that said "applicable" while no approval appeared would
        be the same silent dead end this change exists to remove."""
        with self.Session.begin() as session:
            session.get(V2Project, self.project_id).status = "active"
            session.add(ProjectBaseline(project_id=self.project_id, task_count=1, locked_by=ADMIN_ID))

        self.assertEqual(self.decide("applicable", "Confirmed on site").status_code, 200)

        with self.Session() as session:
            approval = session.scalar(
                select(ProjectExternalApproval).where(ProjectExternalApproval.project_gate_id == self.gate_id)
            )
            self.assertIsNotNone(approval, "an applicable gate on an active project must yield a runtime approval")
            self.assertEqual(approval.status, "pending")
            self.assertEqual(approval.project_id, self.project_id)

    def test_deciding_the_same_gate_twice_creates_only_one_approval(self):
        with self.Session.begin() as session:
            session.get(V2Project, self.project_id).status = "active"
            session.add(ProjectBaseline(project_id=self.project_id, task_count=1, locked_by=ADMIN_ID))

        self.assertEqual(self.decide("applicable", "First").status_code, 200)
        self.assertEqual(self.decide("applicable", "Again").status_code, 200)

        with self.Session() as session:
            approvals = list(session.scalars(
                select(ProjectExternalApproval).where(ProjectExternalApproval.project_gate_id == self.gate_id)
            ).all())
        self.assertEqual(len(approvals), 1)

    def test_a_gate_that_already_has_an_approval_cannot_be_ruled_out(self):
        """Cascading a not-applicable decision into an instantiated approval
        would either delete one that may already carry a recorded decision, or
        orphan it behind a gate that says it does not apply. Refusing is the
        only honest option, and it names the action that does work."""
        with self.Session.begin() as session:
            session.get(V2Project, self.project_id).status = "active"
            session.add(ProjectBaseline(project_id=self.project_id, task_count=1, locked_by=ADMIN_ID))
        self.assertEqual(self.decide("applicable", "Confirmed").status_code, 200)

        response = self.decide("not_applicable", "Changed my mind")

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("Reject the approval instead", response.text)
        with self.Session() as session:
            gate = session.get(V2ProjectExternalGate, self.gate_id)
            self.assertEqual(gate.applicability_state, "applicable")

    def test_a_draft_project_decision_instantiates_nothing_yet(self):
        """A draft has no execution layer to attach an approval to; it gets
        one at its own activation, which is U8's job and not this one's."""
        self.assertEqual(self.decide("applicable", "Confirmed").status_code, 200)
        with self.Session() as session:
            self.assertIsNone(session.scalar(
                select(ProjectExternalApproval).where(ProjectExternalApproval.project_gate_id == self.gate_id)
            ))

    def test_an_archived_project_is_still_refused(self):
        with self.Session.begin() as session:
            session.get(V2Project, self.project_id).status = "archived"
        response = self.decide("applicable", "Attempt")
        self.assertEqual(response.status_code, 409, response.text)
        with self.Session() as session:
            self.assertEqual(session.get(V2ProjectExternalGate, self.gate_id).applicability_state, "pending_review")


if __name__ == "__main__":
    unittest.main()
