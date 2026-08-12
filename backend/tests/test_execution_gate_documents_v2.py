"""U14 (R13): documents attached to an external approval.

The status lifecycle records that the landlord approved. This records the
letter that says so - and keeps it out of any publicly reachable directory,
because a signed NOC is not something to leave on a guessable URL.
"""
from __future__ import annotations

import tempfile
import unittest
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

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
    ExecutionGateDocument, ExecutionGateStatusHistory, ExecutionGateTask, FileObject,
    ProjectBaseline, Task, TaskDependency,
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
EMPLOYEE_ID = uuid.UUID("ffffffff-ffff-4fff-8fff-fffffffffff6")
OTHER_EMPLOYEE_ID = uuid.UUID("abcdefab-cdef-4bcd-8bcd-abcdefabcde7")
START = date(2026, 8, 1)

PDF_BYTES = b"%PDF-1.4 signed landlord letter"


class ExecutionGateDocumentTests(unittest.TestCase):
    def setUp(self):
        self._storage = tempfile.TemporaryDirectory()
        self._settings_patch = mock.patch("app.services.execution_gate_document.settings")
        settings_mock = self._settings_patch.start()
        settings_mock.evidence_upload_dir = self._storage.name
        self.addCleanup(self._settings_patch.stop)
        self.addCleanup(self._storage.cleanup)

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
                      ExecutionGateStatusHistory.__table__, ExecutionGateDelegation.__table__,
                      FileObject.__table__, ExecutionGateDocument.__table__):
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
                self.user(SUPERVISOR_ID, UserRole.supervisor),
                self.user(EMPLOYEE_ID, UserRole.internal_employee),
                self.user(OTHER_EMPLOYEE_ID, UserRole.internal_employee),
            ])
            session.flush()
            for user_id, code in ((PM_ID, "PM-001"), (SUPERVISOR_ID, "SUP-001"),
                                  (EMPLOYEE_ID, "EMP-001"), (OTHER_EMPLOYEE_ID, "EMP-002")):
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

    def employee_id_for(self, user_id):
        with self.Session() as session:
            return session.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == user_id))

    def make_delegate(self, user_id=EMPLOYEE_ID):
        previous = self._actor
        self.act_as(ADMIN_ID, UserRole.admin)
        response = self.client.post(
            f"/api/v2/projects/{self.project_id}/execution-gates/{self.gate_id}/delegations",
            json={"employee_id": str(self.employee_id_for(user_id)), "instruction": "Chase the landlord."})
        self.assertEqual(response.status_code, 201, response.text)
        self._actor = previous

    def attach(self, document_type="outcome", content=PDF_BYTES, content_type="application/pdf",
               filename="landlord-letter.pdf", caption=None):
        data = {"document_type": document_type}
        if caption is not None:
            data["caption"] = caption
        return self.client.post(
            f"/api/v2/projects/{self.project_id}/execution-gates/{self.gate_id}/documents",
            data=data, files={"file": (filename, content, content_type)})

    def documents(self):
        return self.client.get(
            f"/api/v2/projects/{self.project_id}/execution-gates/{self.gate_id}/documents")

    # ---- attaching ---------------------------------------------------------

    def test_admin_attaches_an_outcome_document(self):
        response = self.attach(caption="Signed letter from the landlord's agent.")
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["document_type"], "outcome")
        self.assertEqual(body["original_filename"], "landlord-letter.pdf")
        self.assertEqual(body["mime_type"], "application/pdf")
        self.assertEqual(body["size_bytes"], len(PDF_BYTES))
        self.assertEqual(body["caption"], "Signed letter from the landlord's agent.")

        with self.Session() as session:
            audit = session.scalar(select(V2AuditEvent).where(
                V2AuditEvent.action == "PROJECT_GATE_DOCUMENT_ATTACHED"))
            self.assertIsNotNone(audit)

    def test_a_delegate_can_attach_the_paperwork_they_received(self):
        """The delegate lodged the application and receives what comes back.
        Requiring Admin to upload a letter they never saw would just mean it
        never gets attached."""
        self.make_delegate()
        self.act_as(EMPLOYEE_ID, UserRole.internal_employee)
        response = self.attach(document_type="submission", filename="lodgement-receipt.pdf")
        self.assertEqual(response.status_code, 201, response.text)

    def test_attaching_a_document_does_not_let_a_delegate_decide_the_outcome(self):
        """Evidence and decision stay separate: the delegate can put the
        landlord's letter on the record and still cannot mark it approved."""
        self.make_delegate()
        self.act_as(EMPLOYEE_ID, UserRole.internal_employee)
        self.assertEqual(self.attach(document_type="outcome").status_code, 201)
        refused = self.client.post(
            f"/api/v2/projects/{self.project_id}/execution-gates/{self.gate_id}/status",
            json={"status": "submitted", "reason": "Lodged."})
        self.assertEqual(refused.status_code, 200, "submission is theirs to record")
        approved = self.client.post(
            f"/api/v2/projects/{self.project_id}/execution-gates/{self.gate_id}/status",
            json={"status": "approved", "reason": "The letter says so."})
        self.assertEqual(approved.status_code, 403)

    def test_a_pm_supervisor_and_undelegated_employee_cannot_attach(self):
        for user_id, role in ((PM_ID, UserRole.project_manager), (SUPERVISOR_ID, UserRole.supervisor),
                              (OTHER_EMPLOYEE_ID, UserRole.internal_employee)):
            with self.subTest(role=role):
                self.act_as(user_id, role)
                refused = self.attach()
                self.assertEqual(refused.status_code, 403, refused.text)

    def test_an_ended_delegation_removes_the_ability_to_attach(self):
        self.make_delegate()
        with self.Session() as session:
            delegation_id = session.scalar(select(ExecutionGateDelegation.id))
        self.act_as(ADMIN_ID, UserRole.admin)
        self.assertEqual(self.client.post(
            f"/api/v2/projects/{self.project_id}/execution-gates/{self.gate_id}/delegations/{delegation_id}/end",
            json={"reason": "Handed on."}).status_code, 200)
        self.act_as(EMPLOYEE_ID, UserRole.internal_employee)
        self.assertEqual(self.attach().status_code, 403)

    def test_the_file_type_and_size_are_policed(self):
        self.assertEqual(self.attach(content_type="text/html", filename="x.html").status_code, 422)
        self.assertEqual(self.attach(content=b"").status_code, 422)
        oversized = b"x" * (10 * 1024 * 1024 + 1)
        self.assertEqual(self.attach(content=oversized).status_code, 422)

    def test_an_unknown_document_type_is_refused(self):
        self.assertEqual(self.attach(document_type="whatever").status_code, 422)

    def test_every_valid_document_type_is_accepted(self):
        for index, document_type in enumerate(("submission", "outcome", "supporting")):
            with self.subTest(document_type=document_type):
                response = self.attach(document_type=document_type, filename=f"doc-{index}.pdf")
                self.assertEqual(response.status_code, 201, response.text)

    # ---- reading -----------------------------------------------------------

    def test_any_project_member_can_list_and_download(self):
        """A blocked crew asking what the fire officer said should not need
        Admin to open the PDF for them."""
        self.assertEqual(self.attach(caption="Signed letter.").status_code, 201)
        self.act_as(SUPERVISOR_ID, UserRole.supervisor)

        listed = self.documents()
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(len(listed.json()), 1)
        document_id = listed.json()[0]["id"]

        downloaded = self.client.get(
            f"/api/v2/projects/{self.project_id}/execution-gates/{self.gate_id}/documents/{document_id}/download")
        self.assertEqual(downloaded.status_code, 200, downloaded.text)
        self.assertEqual(downloaded.content, PDF_BYTES)
        self.assertIn("landlord-letter.pdf", downloaded.headers["content-disposition"])
        self.assertEqual(downloaded.headers["x-content-type-options"], "nosniff")

    def test_the_listing_never_exposes_the_storage_key(self):
        """The bytes are reachable only through the authenticated download
        route - a storage key in the payload would be half a public URL."""
        self.assertEqual(self.attach().status_code, 201)
        self.assertNotIn("storage_key", self.documents().text)

    def test_the_bytes_land_in_the_private_evidence_store(self):
        self.assertEqual(self.attach().status_code, 201)
        with self.Session() as session:
            file_object = session.scalar(select(FileObject))
        stored = Path(self._storage.name) / file_object.storage_key
        self.assertTrue(stored.is_file())
        self.assertEqual(stored.read_bytes(), PDF_BYTES)
        self.assertTrue(file_object.storage_key.startswith("gate-"))

    def test_a_non_member_is_refused_the_listing(self):
        outsider = uuid.UUID("99999999-aaaa-4aaa-8aaa-999999999991")
        with self.Session.begin() as session:
            session.add(self.user(outsider, UserRole.supervisor))
        self.act_as(outsider, UserRole.supervisor)
        self.assertEqual(self.documents().status_code, 403)

    def test_a_document_id_from_another_gate_does_not_resolve(self):
        self.assertEqual(self.attach().status_code, 201)
        with self.Session() as session:
            document_id = session.scalar(select(ExecutionGateDocument.id))
        missing = self.client.get(
            f"/api/v2/projects/{self.project_id}/execution-gates/{uuid.uuid4()}/documents/{document_id}/download")
        self.assertEqual(missing.status_code, 404)

    def test_a_document_whose_file_vanished_reports_404_rather_than_raising(self):
        self.assertEqual(self.attach().status_code, 201)
        with self.Session() as session:
            document_id = session.scalar(select(ExecutionGateDocument.id))
            file_object = session.scalar(select(FileObject))
        (Path(self._storage.name) / file_object.storage_key).unlink()
        gone = self.client.get(
            f"/api/v2/projects/{self.project_id}/execution-gates/{self.gate_id}/documents/{document_id}/download")
        self.assertEqual(gone.status_code, 404)

    def test_documents_are_listed_oldest_first_with_their_types(self):
        self.assertEqual(self.attach(document_type="submission", filename="a.pdf").status_code, 201)
        self.assertEqual(self.attach(document_type="outcome", filename="b.pdf").status_code, 201)
        rows = self.documents().json()
        self.assertEqual([row["document_type"] for row in rows], ["submission", "outcome"])
        with self.Session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(FileObject)), 2)


if __name__ == "__main__":
    unittest.main()
