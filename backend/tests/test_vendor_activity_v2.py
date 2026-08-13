from __future__ import annotations

import ast
import inspect
import shutil
import tempfile
import unittest
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.config import settings
from app.database import get_db
from app.execution_models import BaselineTask, FileObject, OutboxEvent, ProjectBaseline, Task, TaskDependency, ProjectExternalApproval, ProjectExternalApprovalTask
from app.models import EmployeeProfile, User, UserRole
from app.project_models import (
    V2AuditEvent,
    V2Project,
    V2ProjectExternalGate,
    V2ProjectMembership,
    V2ProjectTask,
    V2ProjectTaskDependency,
    V2ProjectExternalGateTask,
)
from app.routes.project_vendors_v2 import router as project_vendors_router
from app.routes.projects_v2 import router as projects_router
from app.template_models import V2Template, V2TemplateExternalGate, V2TemplateExternalGateTask, V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion
from app.vendor_models import (
    ProjectVendor,
    TaskVendorAssignment,
    V2CapabilityCategory,
    V2Vendor,
    V2VendorCapability,
    VendorActivityEvent,
    VendorActivityEvidence,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")

TINY_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
)


class VendorActivityApiTests(unittest.TestCase):
    """Phase 2 U3: vendor-attributable activity/incident capture (R5).

    Follows the same SQLite-ATTACHed-schema harness pattern as
    test_task_progress_evidence_v2.py (evidence upload) and
    test_task_vendor_assignment_v2.py (vendor delegation seed).
    """

    def setUp(self):
        self.evidence_dir = tempfile.mkdtemp(prefix="siteops-vendor-activity-test-")
        self._original_evidence_dir = settings.evidence_upload_dir
        settings.evidence_upload_dir = self.evidence_dir

        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            dbapi_connection.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)

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
            V2ProjectExternalGate.__table__,
            V2AuditEvent.__table__,
            ProjectBaseline.__table__,
            BaselineTask.__table__,
            Task.__table__,
            ProjectExternalApproval.__table__,
            ProjectExternalApprovalTask.__table__,
            TaskDependency.__table__,
            V2Vendor.__table__,
            V2CapabilityCategory.__table__,
            V2VendorCapability.__table__,
            ProjectVendor.__table__,
            TaskVendorAssignment.__table__,
            FileObject.__table__,
            VendorActivityEvent.__table__,
            VendorActivityEvidence.__table__,
            OutboxEvent.__table__,
            V2TemplateExternalGate.__table__,
            V2TemplateExternalGateTask.__table__,
            V2ProjectExternalGateTask.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()

        self.app = FastAPI()
        self.app.include_router(projects_router)
        self.app.include_router(project_vendors_router)

        def override_db():
            with self.Session() as session:
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self._current_actor = User(
            id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True,
        )
        self.app.dependency_overrides[current_user] = lambda: self._current_actor
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        settings.evidence_upload_dir = self._original_evidence_dir
        shutil.rmtree(self.evidence_dir, ignore_errors=True)

    def act_as(self, user: User) -> None:
        self._current_actor = user

    def act_as_admin(self) -> None:
        self.act_as(User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True))

    def act_as_pm(self) -> None:
        self.act_as(User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True))

    def act_as_supervisor(self) -> None:
        self.act_as(User(
            id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com",
            role=UserRole.supervisor, active=True,
        ))

    # ---- seeding -------------------------------------------------------

    def _seed(self):
        with self.Session.begin() as session:
            admin = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
            pm = User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True)
            supervisor = User(
                id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com",
                role=UserRole.supervisor, active=True,
            )
            session.add_all([admin, pm, supervisor])
            session.flush()
            session.add_all([
                EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                EmployeeProfile(
                    user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor", availability="available",
                ),
            ])
            template = V2Template(code="WORKVED-45", name="Workved 45 Day")
            session.add(template)
            session.flush()
            published = V2TemplateVersion(
                template_id=template.id, version_no=1, status="published", duration_days=45,
                content_hash="published-hash", is_current_published=True,
                created_by=ADMIN_ID, published_by=ADMIN_ID, published_at=datetime.now(timezone.utc),
            )
            session.add(published)
            session.flush()
            session.add(V2TemplateTask(
                template_version_id=published.id, code="T001", sequence_no=1, title="Task T001",
                schedule_classification="execution", planned_start_day=1, planned_end_day=1,
                applicability="mandatory", task_class="standard", task_kind="work",
                evidence_required=False, duration_days=1, phase="Electrical", category="Wiring",
            ))
            session.flush()
            self.published_version_id = published.id

            electrical = V2CapabilityCategory(name="Electrical")
            session.add(electrical)
            session.flush()

            vendor_electrical = V2Vendor(
                id=uuid.uuid4(), name="Electrical Co", contact_person="Ravi", phone="9000000001",
                status="active", engagement_type="main",
            )
            session.add(vendor_electrical)
            session.flush()
            session.add(V2VendorCapability(vendor_id=vendor_electrical.id, category_id=electrical.id))
            self.vendor_electrical_id = vendor_electrical.id

    def create_draft(self, **overrides):
        payload = {
            "project_name": "Futurex Fitout",
            "client": "Example Client",
            "location": "Mumbai",
            "proposed_start_date": "2026-08-01",
            "target_handover_date": "2026-09-14",
            "pm_user_id": str(PM_ID),
            "supervisor_user_id": str(SUPERVISOR_ID),
            "template_version_id": str(self.published_version_id),
        }
        payload.update(overrides)
        self.act_as_admin()
        response = self.client.post("/api/v2/projects", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def activate_project(self) -> dict:
        project = self.create_draft()
        response = self.client.post(f"/api/v2/projects/{project['id']}/generate-tasks")
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post(f"/api/v2/projects/{project['id']}/generate-dependencies")
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post(f"/api/v2/projects/{project['id']}/activate", json={"reason": "Go live."})
        self.assertEqual(response.status_code, 200, response.text)
        return project

    def task_by_code(self, project_id: str, code: str) -> Task:
        with self.Session() as session:
            return session.scalar(
                select(Task).where(Task.project_id == uuid.UUID(project_id), Task.original_code == code)
            )

    def map_and_assign_vendor(self, project_id, task_id) -> str:
        self.act_as_pm()
        map_response = self.client.post(
            f"/api/v2/projects/{project_id}/vendors", json={"vendor_id": str(self.vendor_electrical_id)},
        )
        self.assertEqual(map_response.status_code, 200, map_response.text)
        assign_response = self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/vendor-assignment",
            json={"vendor_id": str(self.vendor_electrical_id)},
        )
        self.assertEqual(assign_response.status_code, 200, assign_response.text)
        return assign_response.json()["id"]

    def log_activity(
        self, project_id, task_id, assignment_id, event_type, description="Some activity.",
        responsibility_decision=None, files=None,
    ):
        data = {"event_type": event_type, "description": description}
        if responsibility_decision is not None:
            data["responsibility_decision"] = responsibility_decision
        return self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/vendor-assignment/{assignment_id}/activity",
            data=data,
            files=files,
        )

    # ---- happy path -----------------------------------------------------

    def test_delay_activity_with_responsibility_decision_and_evidence(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        assignment_id = self.map_and_assign_vendor(project["id"], task.id)

        self.act_as_pm()
        response = self.log_activity(
            project["id"], task.id, assignment_id, "delay",
            description="Vendor arrived 3 hours late.",
            responsibility_decision="Vendor responsible - traffic was not a valid excuse.",
            files={"evidence": ("site.png", TINY_PNG_BYTES, "image/png")},
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["event_type"], "delay")
        self.assertEqual(body["responsibility_decision"], "Vendor responsible - traffic was not a valid excuse.")
        self.assertEqual(len(body["evidence"]), 1)

        with self.Session() as session:
            event_row = session.get(VendorActivityEvent, uuid.UUID(body["id"]))
            self.assertIsNotNone(event_row)
            link_rows = session.scalars(
                select(VendorActivityEvidence).where(
                    VendorActivityEvidence.vendor_activity_event_id == event_row.id
                )
            ).all()
            self.assertEqual(len(link_rows), 1)

    def test_evidence_file_is_downloadable_from_its_own_route(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        assignment_id = self.map_and_assign_vendor(project["id"], task.id)

        self.act_as_pm()
        log_response = self.log_activity(
            project["id"], task.id, assignment_id, "presence",
            description="Vendor crew on site.",
            files={"evidence": ("site.png", TINY_PNG_BYTES, "image/png")},
        )
        self.assertEqual(log_response.status_code, 200, log_response.text)
        file_id = log_response.json()["evidence"][0]["file_id"]

        response = self.client.get(
            f"/api/v2/projects/{project['id']}/tasks/{task.id}"
            f"/vendor-assignment/{assignment_id}/activity/{file_id}"
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.content, TINY_PNG_BYTES)
        self.assertIn("site.png", response.headers["content-disposition"])

    def test_evidence_download_rejects_file_from_a_different_assignment(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        assignment_id = self.map_and_assign_vendor(project["id"], task.id)
        self.act_as_pm()
        log_response = self.log_activity(
            project["id"], task.id, assignment_id, "presence",
            description="Vendor crew on site.",
            files={"evidence": ("site.png", TINY_PNG_BYTES, "image/png")},
        )
        file_id = log_response.json()["evidence"][0]["file_id"]

        other_project = self.create_draft(project_name="Other Project")
        response = self.client.post(f"/api/v2/projects/{other_project['id']}/generate-tasks")
        self.assertEqual(response.status_code, 200)
        response = self.client.post(f"/api/v2/projects/{other_project['id']}/generate-dependencies")
        self.assertEqual(response.status_code, 200)
        response = self.client.post(f"/api/v2/projects/{other_project['id']}/activate", json={"reason": "Go live."})
        self.assertEqual(response.status_code, 200)
        other_task = self.task_by_code(other_project["id"], "T001")
        other_assignment_id = self.map_and_assign_vendor(other_project["id"], other_task.id)

        response = self.client.get(
            f"/api/v2/projects/{other_project['id']}/tasks/{other_task.id}"
            f"/vendor-assignment/{other_assignment_id}/activity/{file_id}"
        )

        self.assertEqual(response.status_code, 404, response.text)

    # ---- edge cases -----------------------------------------------------

    def test_incident_without_evidence_still_succeeds(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        assignment_id = self.map_and_assign_vendor(project["id"], task.id)

        self.act_as_pm()
        response = self.log_activity(
            project["id"], task.id, assignment_id, "incident",
            description="Minor safety incident, no injuries.",
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["event_type"], "incident")
        self.assertEqual(body["evidence"], [])

    def test_presence_and_rework_event_types_accepted(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        assignment_id = self.map_and_assign_vendor(project["id"], task.id)

        self.act_as_pm()
        presence_response = self.log_activity(
            project["id"], task.id, assignment_id, "presence", description="Crew of 4 on site.",
        )
        self.assertEqual(presence_response.status_code, 200, presence_response.text)
        self.assertEqual(presence_response.json()["event_type"], "presence")

        rework_response = self.log_activity(
            project["id"], task.id, assignment_id, "rework", description="Conduit routing redone.",
        )
        self.assertEqual(rework_response.status_code, 200, rework_response.text)
        self.assertEqual(rework_response.json()["event_type"], "rework")

    # ---- error paths ------------------------------------------------------

    def test_invalid_event_type_rejected(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        assignment_id = self.map_and_assign_vendor(project["id"], task.id)

        self.act_as_pm()
        response = self.log_activity(
            project["id"], task.id, assignment_id, "sabotage", description="Not a real event type.",
        )

        self.assertEqual(response.status_code, 422, response.text)

    def test_non_pm_non_admin_actor_cannot_log_activity(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        assignment_id = self.map_and_assign_vendor(project["id"], task.id)

        self.act_as_supervisor()
        response = self.log_activity(
            project["id"], task.id, assignment_id, "presence", description="Crew of 4 on site.",
        )

        self.assertEqual(response.status_code, 403, response.text)

    # ---- integration: non-interference with Phase 1 accountability -------

    def test_no_vendor_identity_endpoint_can_mutate_task_lifecycle(self):
        """Exhaustive route inspection (not just one negative test): every
        route this unit adds to `project_vendors_v2.py` is PM-authenticated
        (via `Depends(current_user)` + the service's `_require_pm` gate) -
        there is no vendor-identity-authenticated route at all in this
        module, so none can mutate task lifecycle/verification/approval
        state. Also proves, structurally via `ast` (not a substring check
        that would false-positive on this module's own docstrings), that
        neither the route module nor either new service imports Phase 1's
        accountability-resolution services."""
        import app.routes.project_vendors_v2 as project_vendors_route_module
        import app.services.vendor_acknowledgement as vendor_acknowledgement_service_module
        import app.services.vendor_activity as vendor_activity_service_module

        # Every route on this router must depend on `current_user` (the
        # PM/Admin actor), never on a separate vendor-identity dependency -
        # there is no such dependency defined anywhere in this codebase for
        # this unit to have used.
        for route in project_vendors_route_module.router.routes:
            dependant_call_names = {
                dependency.call.__name__
                for dependency in route.dependant.dependencies
                if getattr(dependency, "call", None) is not None
            }
            self.assertIn(
                "current_user", dependant_call_names,
                f"Route {route.path} must be gated by current_user (PM/Admin), found {dependant_call_names}.",
            )

        route_paths = {route.path for route in project_vendors_route_module.router.routes}
        self.assertIn(
            "/api/v2/projects/{project_id}/tasks/{task_id}/vendor-assignment/{assignment_id}/acknowledge",
            route_paths,
        )
        self.assertIn(
            "/api/v2/projects/{project_id}/tasks/{task_id}/vendor-assignment/{assignment_id}/activity",
            route_paths,
        )

        forbidden_module_fragments = ("task_lifecycle", "task_verification")
        for module in (
            project_vendors_route_module,
            vendor_acknowledgement_service_module,
            vendor_activity_service_module,
        ):
            source = inspect.getsource(module)
            tree = ast.parse(source)
            imported_modules: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_modules.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_modules.append(node.module)
            for imported in imported_modules:
                for forbidden in forbidden_module_fragments:
                    self.assertNotIn(
                        forbidden, imported,
                        f"{module.__name__} must not import {imported} (Phase 1 accountability path).",
                    )


if __name__ == "__main__":
    unittest.main()
