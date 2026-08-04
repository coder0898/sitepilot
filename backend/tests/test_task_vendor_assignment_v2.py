from __future__ import annotations

import ast
import inspect
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
from app.database import get_db
from app.execution_models import BaselineTask, ProjectBaseline, Task, TaskDependency
from app.models import EmployeeProfile, User, UserRole
from app.project_models import (
    V2AuditEvent,
    V2Project,
    V2ProjectExternalGate,
    V2ProjectMembership,
    V2ProjectTask,
    V2ProjectTaskDependency,
)
from app.routes.project_vendors_v2 import router as project_vendors_router
from app.routes.projects_v2 import router as projects_router
from app.template_models import V2Template, V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion
from app.vendor_models import ProjectVendor, TaskVendorAssignment, V2CapabilityCategory, V2Vendor, V2VendorCapability


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")


class TaskVendorAssignmentApiTests(unittest.TestCase):
    """Phase 2 U2: task vendor delegation (R3), against real execution tasks
    produced by U1's baseline-lock activation flow.

    Follows the same SQLite-ATTACHed-schema harness pattern as
    test_task_support_assignment_v2.py / test_task_blockers_delays_v2.py.
    """

    def setUp(self):
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
            TaskDependency.__table__,
            V2Vendor.__table__,
            V2CapabilityCategory.__table__,
            V2VendorCapability.__table__,
            ProjectVendor.__table__,
            TaskVendorAssignment.__table__,
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

    def act_as(self, user: User) -> None:
        self._current_actor = user

    def act_as_admin(self) -> None:
        self.act_as(User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True))

    def act_as_pm(self) -> None:
        self.act_as(User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True))

    # ---- seeding -------------------------------------------------------

    def _seed(self):
        """Seeds a 1-task template: T001 (work/standard, category
        'Electrical'), plus four vendors covering the happy/mismatch/
        unmapped/inactive scenarios."""
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
                evidence_required=False, duration_days=1, phase="Setup", category="Electrical",
            ))
            session.flush()
            self.published_version_id = published.id

            electrical = V2CapabilityCategory(name="Electrical")
            plumbing = V2CapabilityCategory(name="Plumbing")
            session.add_all([electrical, plumbing])
            session.flush()

            vendor_electrical = V2Vendor(
                id=uuid.uuid4(), name="Electrical Co", contact_person="Ravi", phone="9000000001",
                status="active", engagement_type="main",
            )
            vendor_plumbing = V2Vendor(
                id=uuid.uuid4(), name="Plumbing Co", contact_person="Meena", phone="9000000002",
                status="active", engagement_type="main",
            )
            vendor_unmapped = V2Vendor(
                id=uuid.uuid4(), name="Unmapped Electrical Co", contact_person="Kiran", phone="9000000003",
                status="active", engagement_type="main",
            )
            vendor_soon_inactive = V2Vendor(
                id=uuid.uuid4(), name="Soon Inactive Co", contact_person="Sunil", phone="9000000004",
                status="active", engagement_type="main",
            )
            session.add_all([vendor_electrical, vendor_plumbing, vendor_unmapped, vendor_soon_inactive])
            session.flush()

            session.add_all([
                V2VendorCapability(vendor_id=vendor_electrical.id, category_id=electrical.id),
                V2VendorCapability(vendor_id=vendor_plumbing.id, category_id=plumbing.id),
                V2VendorCapability(vendor_id=vendor_unmapped.id, category_id=electrical.id),
                V2VendorCapability(vendor_id=vendor_soon_inactive.id, category_id=electrical.id),
            ])

            self.vendor_electrical_id = vendor_electrical.id
            self.vendor_plumbing_id = vendor_plumbing.id
            self.vendor_unmapped_id = vendor_unmapped.id
            self.vendor_soon_inactive_id = vendor_soon_inactive.id

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

    def map_vendor(self, project_id, vendor_id):
        self.act_as_pm()
        return self.client.post(
            f"/api/v2/projects/{project_id}/vendors", json={"vendor_id": str(vendor_id)},
        )

    def assign_vendor(self, project_id, task_id, vendor_id):
        self.act_as_pm()
        return self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/vendor-assignment",
            json={"vendor_id": str(vendor_id)},
        )

    # ---- happy path -----------------------------------------------------

    def test_pm_assigns_mapped_matching_capability_vendor_to_task(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")

        map_response = self.map_vendor(project["id"], self.vendor_electrical_id)
        self.assertEqual(map_response.status_code, 200, map_response.text)

        response = self.assign_vendor(project["id"], task.id, self.vendor_electrical_id)

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["task_id"], str(task.id))
        self.assertEqual(body["vendor_id"], str(self.vendor_electrical_id))
        self.assertEqual(body["status"], "pending_ack")

    # ---- edge cases -----------------------------------------------------

    def test_capability_mismatch_rejected(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")

        map_response = self.map_vendor(project["id"], self.vendor_plumbing_id)
        self.assertEqual(map_response.status_code, 200, map_response.text)

        response = self.assign_vendor(project["id"], task.id, self.vendor_plumbing_id)

        self.assertEqual(response.status_code, 422, response.text)

    def test_unmapped_vendor_rejected(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")

        # Deliberately never mapped via map_vendor().
        response = self.assign_vendor(project["id"], task.id, self.vendor_unmapped_id)

        self.assertIn(response.status_code, (404, 422), response.text)

    # ---- error paths ------------------------------------------------------

    def test_inactive_vendor_rejected_even_if_previously_mapped(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")

        map_response = self.map_vendor(project["id"], self.vendor_soon_inactive_id)
        self.assertEqual(map_response.status_code, 200, map_response.text)

        with self.Session.begin() as session:
            vendor = session.get(V2Vendor, self.vendor_soon_inactive_id)
            vendor.status = "inactive"

        response = self.assign_vendor(project["id"], task.id, self.vendor_soon_inactive_id)

        self.assertEqual(response.status_code, 422, response.text)

    # ---- integration: non-interference with Phase 1 accountability -------

    def test_assignment_does_not_touch_lifecycle_status_or_accountability_code(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        status_before = task.lifecycle_status

        map_response = self.map_vendor(project["id"], self.vendor_electrical_id)
        self.assertEqual(map_response.status_code, 200, map_response.text)

        response = self.assign_vendor(project["id"], task.id, self.vendor_electrical_id)
        self.assertEqual(response.status_code, 200, response.text)

        task_after = self.task_by_code(project["id"], "T001")
        self.assertEqual(task_after.lifecycle_status, status_before)

        # Structural proof (per the plan): this unit's new service/route
        # files must not *import* Phase 1's accountability-resolution
        # services at all - parsed via `ast` (not a plain substring check)
        # so that mentioning "task_lifecycle" in prose/docstrings (as this
        # module's own header comment does, to explain the constraint)
        # doesn't produce a false positive.
        import app.routes.project_vendors_v2 as project_vendors_route_module
        import app.services.project_vendor as project_vendor_service_module
        import app.services.task_vendor_assignment as task_vendor_assignment_service_module

        forbidden_module_fragments = ("task_lifecycle", "task_verification")
        for module in (
            project_vendors_route_module,
            project_vendor_service_module,
            task_vendor_assignment_service_module,
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
