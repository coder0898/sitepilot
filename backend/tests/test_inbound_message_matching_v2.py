from __future__ import annotations

import ast
import hashlib
import hmac
import inspect
import json
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
from app.execution_models import BaselineTask, InboundMessage, OutboxEvent, ProjectBaseline, Task, TaskDependency
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
from app.routes.whatsapp_webhook_v2 import router as whatsapp_webhook_router
from app.template_models import V2Template, V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion
from app.vendor_models import (
    ProjectVendor,
    TaskVendorAssignment,
    V2CapabilityCategory,
    V2Vendor,
    V2VendorCapability,
    V2VendorContact,
    VendorAcknowledgement,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
OUTSIDER_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")

SUPERVISOR_PHONE = "9000000011"
UNKNOWN_PHONE = "9999999999"
VENDOR_ELECTRICAL_CONTACT_PHONE = "9100000001"
VENDOR_OTHER_CONTACT_PHONE = "9100000002"
AMBIGUOUS_PHONE = "9200000001"

WEBHOOK_SECRET = "test-webhook-secret"


class InboundMessageMatchingApiTests(unittest.TestCase):
    """Phase 2 U6: inbound WhatsApp message matching (R8/R9).

    Follows the same SQLite-ATTACHed-schema harness pattern as
    test_vendor_acknowledgement_v2.py / test_task_lifecycle_transitions_v2.py.
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
            V2VendorContact.__table__,
            ProjectVendor.__table__,
            TaskVendorAssignment.__table__,
            VendorAcknowledgement.__table__,
            InboundMessage.__table__,
            OutboxEvent.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()

        self._original_webhook_secret = settings.whatsapp_webhook_secret
        settings.whatsapp_webhook_secret = WEBHOOK_SECRET

        self.app = FastAPI()
        self.app.include_router(projects_router)
        self.app.include_router(project_vendors_router)
        self.app.include_router(whatsapp_webhook_router)

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
        settings.whatsapp_webhook_secret = self._original_webhook_secret

    def act_as_admin(self) -> None:
        self._current_actor = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)

    def act_as_pm(self) -> None:
        self._current_actor = User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True)

    # ---- seeding -------------------------------------------------------

    def _seed(self):
        """Seeds a 1-task template: T001 (work/standard, category
        'Electrical'). PM (phone unset), Supervisor (phone
        SUPERVISOR_PHONE). Two vendors, each with one contact: vendor
        'Electrical Co' (contact phone VENDOR_ELECTRICAL_CONTACT_PHONE) and
        vendor 'Other Co' (contact phone VENDOR_OTHER_CONTACT_PHONE) - used
        to prove a vendor contact cannot reference an assignment belonging
        to a different vendor. An OUTSIDER employee and a second vendor
        contact both share AMBIGUOUS_PHONE, to exercise the "matches more
        than one identity" case.
        """
        with self.Session.begin() as session:
            admin = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
            pm = User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True)
            supervisor = User(
                id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com",
                role=UserRole.supervisor, active=True, phone=SUPERVISOR_PHONE,
            )
            outsider = User(
                id=OUTSIDER_ID, name="Outsider", email="outsider@example.com",
                role=UserRole.supervisor, active=True, phone=AMBIGUOUS_PHONE,
            )
            session.add_all([admin, pm, supervisor, outsider])
            session.flush()
            session.add_all([
                EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                EmployeeProfile(
                    user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor", availability="available",
                ),
                EmployeeProfile(
                    user_id=OUTSIDER_ID, employee_code="OUT-001", designation="Supervisor", availability="available",
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
            vendor_other = V2Vendor(
                id=uuid.uuid4(), name="Other Co", contact_person="Sunil", phone="9000000002",
                status="active", engagement_type="main",
            )
            session.add_all([vendor_electrical, vendor_other])
            session.flush()
            session.add(V2VendorCapability(vendor_id=vendor_electrical.id, category_id=electrical.id))
            self.vendor_electrical_id = vendor_electrical.id
            self.vendor_other_id = vendor_other.id

            vendor_electrical_contact = V2VendorContact(
                vendor_id=vendor_electrical.id, name="Ravi", phone=VENDOR_ELECTRICAL_CONTACT_PHONE, is_primary=True,
            )
            vendor_other_contact = V2VendorContact(
                vendor_id=vendor_other.id, name="Sunil", phone=VENDOR_OTHER_CONTACT_PHONE, is_primary=True,
            )
            # A second vendor contact sharing AMBIGUOUS_PHONE with the
            # OUTSIDER employee above - proves cross-table ambiguity is
            # detected, not just same-table duplicate matches.
            ambiguous_vendor_contact = V2VendorContact(
                vendor_id=vendor_other.id, name="Ambiguous", phone=AMBIGUOUS_PHONE, is_primary=False,
            )
            session.add_all([vendor_electrical_contact, vendor_other_contact, ambiguous_vendor_contact])

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

    def map_and_assign_vendor(self, project_id, task_id, vendor_id) -> str:
        self.act_as_pm()
        map_response = self.client.post(
            f"/api/v2/projects/{project_id}/vendors", json={"vendor_id": str(vendor_id)},
        )
        self.assertEqual(map_response.status_code, 200, map_response.text)
        assign_response = self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/vendor-assignment",
            json={"vendor_id": str(vendor_id)},
        )
        self.assertEqual(assign_response.status_code, 200, assign_response.text)
        return assign_response.json()["id"]

    def assignment_ref(self, assignment_id: str) -> str:
        return assignment_id.replace("-", "")[:8]

    # ---- webhook helpers -------------------------------------------------

    def post_inbound(self, payload: dict, secret: str | None = None, header: str | None = ...):
        raw_body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if header is ...:
            signing_secret = secret if secret is not None else WEBHOOK_SECRET
            digest = hmac.new(signing_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
            headers["X-Hub-Signature-256"] = f"sha256={digest}"
        elif header is not None:
            headers["X-Hub-Signature-256"] = header
        return self.client.post("/api/v2/whatsapp/inbound", content=raw_body, headers=headers)

    def inbound_rows(self) -> list[InboundMessage]:
        with self.Session() as session:
            return list(session.scalars(select(InboundMessage)).all())

    def acknowledgement_rows(self) -> list[VendorAcknowledgement]:
        with self.Session() as session:
            return list(session.scalars(select(VendorAcknowledgement)).all())

    # ---- happy paths ------------------------------------------------------

    def test_vendor_contact_accept_produces_identical_acknowledgement_row(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        assignment_id = self.map_and_assign_vendor(project["id"], task.id, self.vendor_electrical_id)
        ref = self.assignment_ref(assignment_id)

        response = self.post_inbound({
            "provider_message_id": "wamid.accept-1",
            "sender_phone": VENDOR_ELECTRICAL_CONTACT_PHONE,
            "message_text": f"ACCEPT {ref}",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].processing_status, "processed")
        self.assertEqual(rows[0].matched_identity_type, "vendor_contact")

        acks = self.acknowledgement_rows()
        self.assertEqual(len(acks), 1)
        self.assertEqual(acks[0].task_vendor_assignment_id, uuid.UUID(assignment_id))
        self.assertEqual(acks[0].response, "accepted")
        self.assertEqual(acks[0].channel, "whatsapp")
        # Same downstream state VendorAcknowledgementService always
        # produces on 'accepted': the parent assignment resolves.
        with self.Session() as session:
            assignment = session.get(TaskVendorAssignment, uuid.UUID(assignment_id))
            self.assertEqual(assignment.status, "acknowledged")

    def test_employee_status_transition_produces_identical_lifecycle_change(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        self.assertEqual(task.lifecycle_status, "planned")

        response = self.post_inbound({
            "provider_message_id": "wamid.status-1",
            "sender_phone": SUPERVISOR_PHONE,
            "message_text": f"STATUS {task.original_code} ready",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].processing_status, "processed", rows[0].rejection_reason)
        self.assertEqual(rows[0].matched_identity_type, "employee")

        with self.Session() as session:
            refreshed = session.get(Task, task.id)
            self.assertEqual(refreshed.lifecycle_status, "ready")
            audit_rows = session.scalars(
                select(V2AuditEvent).where(V2AuditEvent.entity_id == task.id)
            ).all()
            self.assertTrue(any(row.action == "TASK_STATUS_CHANGED" for row in audit_rows))
            outbox_rows = session.scalars(
                select(OutboxEvent).where(OutboxEvent.aggregate_id == task.id)
            ).all()
            self.assertTrue(len(outbox_rows) >= 1)

    # ---- the signature gate -----------------------------------------------

    def test_missing_signature_rejected_before_any_db_write(self):
        response = self.post_inbound(
            {
                "provider_message_id": "wamid.no-sig",
                "sender_phone": SUPERVISOR_PHONE,
                "message_text": "STATUS T001 ready",
            },
            header=None,
        )
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(self.inbound_rows(), [])

    def test_invalid_signature_rejected_before_any_db_write(self):
        response = self.post_inbound(
            {
                "provider_message_id": "wamid.bad-sig",
                "sender_phone": SUPERVISOR_PHONE,
                "message_text": "STATUS T001 ready",
            },
            header="sha256=" + ("0" * 64),
        )
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(self.inbound_rows(), [])

    def test_signature_computed_with_wrong_secret_rejected(self):
        response = self.post_inbound(
            {
                "provider_message_id": "wamid.wrong-secret",
                "sender_phone": SUPERVISOR_PHONE,
                "message_text": "STATUS T001 ready",
            },
            secret="not-the-real-secret",
        )
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(self.inbound_rows(), [])

    # ---- identity-matching edge cases --------------------------------------

    def test_unrecognized_phone_number_is_unmatched_with_no_state_mutation(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")

        response = self.post_inbound({
            "provider_message_id": "wamid.unknown-phone",
            "sender_phone": UNKNOWN_PHONE,
            "message_text": f"STATUS {task.original_code} ready",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].processing_status, "unmatched")
        self.assertIsNone(rows[0].matched_identity_type)
        self.assertEqual(rows[0].rejection_reason, "No identity matched this phone number.")

        with self.Session() as session:
            refreshed = session.get(Task, task.id)
            self.assertEqual(refreshed.lifecycle_status, "planned")

    def test_phone_matching_multiple_identities_is_unmatched_never_auto_resolved(self):
        response = self.post_inbound({
            "provider_message_id": "wamid.ambiguous",
            "sender_phone": AMBIGUOUS_PHONE,
            "message_text": "STATUS T001 ready",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].processing_status, "unmatched")
        self.assertIsNone(rows[0].matched_identity_type)
        self.assertIsNone(rows[0].matched_identity_id)
        self.assertIn("more than one identity", rows[0].rejection_reason)

    def test_vendor_contact_referencing_other_vendors_assignment_is_rejected(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        assignment_id = self.map_and_assign_vendor(project["id"], task.id, self.vendor_electrical_id)
        ref = self.assignment_ref(assignment_id)

        response = self.post_inbound({
            "provider_message_id": "wamid.wrong-vendor",
            "sender_phone": VENDOR_OTHER_CONTACT_PHONE,
            "message_text": f"ACCEPT {ref}",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(rows[0].rejection_reason, "This assignment does not belong to your vendor.")
        self.assertEqual(self.acknowledgement_rows(), [])

        with self.Session() as session:
            assignment = session.get(TaskVendorAssignment, uuid.UUID(assignment_id))
            self.assertEqual(assignment.status, "pending_ack")

    # ---- identity-type command scoping (BR-015) ----------------------------

    def test_vendor_contact_sending_employee_only_command_is_rejected(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")

        response = self.post_inbound({
            "provider_message_id": "wamid.vendor-status",
            "sender_phone": VENDOR_ELECTRICAL_CONTACT_PHONE,
            "message_text": f"STATUS {task.original_code} ready",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(rows[0].rejection_reason, "This command is not available for your identity type.")
        with self.Session() as session:
            refreshed = session.get(Task, task.id)
            self.assertEqual(refreshed.lifecycle_status, "planned")

    def test_employee_sending_vendor_only_command_is_rejected(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        assignment_id = self.map_and_assign_vendor(project["id"], task.id, self.vendor_electrical_id)
        ref = self.assignment_ref(assignment_id)

        response = self.post_inbound({
            "provider_message_id": "wamid.employee-accept",
            "sender_phone": SUPERVISOR_PHONE,
            "message_text": f"ACCEPT {ref}",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(rows[0].rejection_reason, "This command is not available for your identity type.")
        self.assertEqual(self.acknowledgement_rows(), [])

    # ---- duplicate delivery -------------------------------------------------

    def test_duplicate_provider_message_id_is_processed_exactly_once(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        assignment_id = self.map_and_assign_vendor(project["id"], task.id, self.vendor_electrical_id)
        ref = self.assignment_ref(assignment_id)

        payload = {
            "provider_message_id": "wamid.dup-1",
            "sender_phone": VENDOR_ELECTRICAL_CONTACT_PHONE,
            "message_text": f"ACCEPT {ref}",
        }
        first = self.post_inbound(payload)
        self.assertEqual(first.status_code, 200, first.text)

        second = self.post_inbound(payload)
        self.assertEqual(second.status_code, 200, second.text)

        rows = self.inbound_rows()
        self.assertEqual(len(rows), 1)

        acks = self.acknowledgement_rows()
        self.assertEqual(len(acks), 1)

    # ---- proof: no parallel business logic ---------------------------------

    def test_no_duplicated_business_logic_in_new_files(self):
        """Static-inspection proof (not just behavioral): the new files
        call the SAME TaskLifecycleService.transition /
        VendorAcknowledgementService.record_acknowledgement methods Phase
        1/Phase 2 U3's portal routes call, and never directly assign
        Task.lifecycle_status or TaskVendorAssignment.status themselves."""
        import app.routes.whatsapp_webhook_v2 as webhook_route_module
        import app.services.inbound_message as inbound_service_module

        for module in (webhook_route_module, inbound_service_module):
            source = inspect.getsource(module)
            self.assertNotIn(".lifecycle_status =", source, f"{module.__name__} must not directly assign lifecycle_status.")
            self.assertNotIn("assignment.status =", source, f"{module.__name__} must not directly assign assignment status.")

        service_source = inspect.getsource(inbound_service_module)
        self.assertIn("TaskLifecycleService(self.db).transition(", service_source)
        self.assertIn("VendorAcknowledgementService(self.db).record_acknowledgement(", service_source)

        # AST-level proof: no direct attribute assignment to `.status` or
        # `.lifecycle_status` anywhere in the service module.
        tree = ast.parse(service_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr in ("lifecycle_status", "status"):
                        self.fail(f"Direct mutating assignment to .{target.attr} found in inbound_message.py")


if __name__ == "__main__":
    unittest.main()
