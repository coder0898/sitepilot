from __future__ import annotations

import inspect
import unittest
import uuid
from datetime import date

from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.message_dispatch as message_dispatch_module
from app.execution_models import MessageDelivery, OutboxEvent, ProjectExternalApproval, Task
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectExternalGate, V2ProjectMembership
from app.services.message_dispatch import MessageDispatchService
from app.services.message_templates import DEFAULT_TEMPLATE, TemplateSpec, render_components, resolve
from app.template_models import V2Template, V2TemplateVersion
from app.vendor_models import V2Vendor, V2VendorContact


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
INTERNAL_EMPLOYEE_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")


class MessageDeliveryDispatchTests(unittest.TestCase):
    """Phase 2 U5: message delivery tracking + sandbox provider adapter (R7).

    Exercises `MessageDispatchService.process_pending` directly against a
    SQLite in-memory harness (ATTACHed `siteops_v2` schema), following the
    same pattern established in test_outbox_emission_v2.py. This unit's
    entry point (`process_pending`) is an internal dispatch process, not a
    user-facing route, so tests call the service directly rather than via
    the FastAPI TestClient.
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
            # V2ProjectExternalGate's broad_mapping_text CHECK constraint
            # calls btrim() (a Postgres-ism) - SQLite has no such builtin,
            # so it must be registered here, same as
            # test_project_gate_assignment_v2.py / test_inbound_message_matching_v2.py.
            dbapi_connection.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)

        for table in (
            User.__table__,
            EmployeeProfile.__table__,
            V2Template.__table__,
            V2TemplateVersion.__table__,
            V2Project.__table__,
            V2ProjectMembership.__table__,
            V2ProjectExternalGate.__table__,
            ProjectExternalApproval.__table__,
            Task.__table__,
            OutboxEvent.__table__,
            MessageDelivery.__table__,
            V2Vendor.__table__,
            V2VendorContact.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()

    def tearDown(self):
        self.engine.dispose()

    # ---- seeding ---------------------------------------------------------

    def _seed(self):
        with self.Session.begin() as session:
            pm = User(
                id=PM_ID, name="PM", email="pm@example.com", phone="9000000010",
                role=UserRole.project_manager, active=True,
            )
            supervisor = User(
                id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com", phone="9000000020",
                role=UserRole.supervisor, active=True,
            )
            admin = User(
                id=ADMIN_ID, name="Admin", email="admin@example.com", phone="9000000050",
                role=UserRole.admin, active=True,
            )
            internal_employee = User(
                id=INTERNAL_EMPLOYEE_ID, name="Internal", email="internal@example.com", phone="9000000060",
                role=UserRole.internal_employee, active=True,
            )
            session.add_all([pm, supervisor, admin, internal_employee])
            session.flush()

            pm_employee = EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available")
            supervisor_employee = EmployeeProfile(
                user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor", availability="available",
            )
            admin_employee = EmployeeProfile(
                user_id=ADMIN_ID, employee_code="ADM-001", designation="Admin", availability="available",
            )
            internal_employee_profile = EmployeeProfile(
                user_id=INTERNAL_EMPLOYEE_ID, employee_code="INT-001", designation="Internal Employee", availability="available",
            )
            session.add_all([pm_employee, supervisor_employee, admin_employee, internal_employee_profile])
            session.flush()
            self.pm_employee_id = pm_employee.id
            self.supervisor_employee_id = supervisor_employee.id
            self.admin_employee_id = admin_employee.id
            self.internal_employee_employee_id = internal_employee_profile.id

            project = V2Project(
                code="PRJ-001", name="Test Project", client_name="Client", site_address="Site",
                start_date=date(2026, 8, 1), status="active", created_by=PM_ID,
            )
            session.add(project)
            session.flush()
            self.project_id = project.id

            session.add_all([
                V2ProjectMembership(
                    project_id=project.id, employee_id=pm_employee.id, project_role="project_manager",
                    assigned_by=PM_ID, assignment_reason="seed",
                ),
                V2ProjectMembership(
                    project_id=project.id, employee_id=supervisor_employee.id, project_role="site_supervisor",
                    assigned_by=PM_ID, assignment_reason="seed",
                ),
                V2ProjectMembership(
                    project_id=project.id, employee_id=internal_employee_profile.id, project_role="internal_employee",
                    assigned_by=PM_ID, assignment_reason="seed",
                ),
            ])

            # A second project with ONLY a PM membership - used to isolate
            # the retry test to exactly one recipient.
            project2 = V2Project(
                code="PRJ-002", name="Test Project 2", client_name="Client", site_address="Site",
                start_date=date(2026, 8, 1), status="active", created_by=PM_ID,
            )
            session.add(project2)
            session.flush()
            self.project2_id = project2.id
            session.add(V2ProjectMembership(
                project_id=project2.id, employee_id=pm_employee.id, project_role="project_manager",
                assigned_by=PM_ID, assignment_reason="seed",
            ))

            task = Task(
                project_id=project.id, baseline_id=uuid.uuid4(), baseline_task_id=uuid.uuid4(),
                original_code="T001", template_sequence=1, title="Task 1",
                schedule_classification="execution", applicability="mandatory",
                evidence_required=False, lifecycle_status="planned",
            )
            session.add(task)
            session.flush()
            self.task_id = task.id

            vendor = V2Vendor(
                name="Electrical Co", contact_person="Ravi", phone="9000000030",
                status="active", engagement_type="main",
            )
            session.add(vendor)
            session.flush()
            self.vendor_id = vendor.id

            contact = V2VendorContact(vendor_id=vendor.id, name="Ravi", phone="9000000040", is_primary=True)
            session.add(contact)
            session.flush()
            self.vendor_contact_id = contact.id

    # ---- helpers -----------------------------------------------------

    def _create_event(self, session, *, event_type, aggregate_type, aggregate_id, payload=None, key=None) -> uuid.UUID:
        ev = OutboxEvent(
            event_type=event_type, aggregate_type=aggregate_type, aggregate_id=aggregate_id,
            payload=payload or {}, idempotency_key=key or f"test:{uuid.uuid4()}", status="pending",
        )
        session.add(ev)
        session.flush()
        return ev.id

    def _deliveries_for(self, event_id: uuid.UUID) -> list[MessageDelivery]:
        with self.Session() as session:
            return list(session.scalars(
                select(MessageDelivery).where(MessageDelivery.outbox_event_id == event_id)
            ).all())

    def _make_gate_approval(self, *, assigned_to_user_id=None) -> uuid.UUID:
        with self.Session.begin() as session:
            gate = V2ProjectExternalGate(
                project_id=self.project_id, original_code="E001", template_sequence=1,
                approval_name="Fire NOC", mapping_classification="exact",
                applicability_state="applicable", blocking=True,
                accountable_pm_user_id=PM_ID, source_type="project_manual",
            )
            session.add(gate)
            session.flush()
            approval = ProjectExternalApproval(
                project_id=self.project_id, project_gate_id=gate.id,
                status="assigned" if assigned_to_user_id else "unassigned",
                assigned_to_user_id=assigned_to_user_id,
                assigned_by=ADMIN_ID if assigned_to_user_id else None,
            )
            session.add(approval)
            session.flush()
            return approval.id

    def _set_phone(self, user_id: uuid.UUID, phone: str | None) -> None:
        with self.Session() as session:
            user = session.get(User, user_id)
            user.phone = phone
            session.add(user)
            session.commit()

    # ---- 1. happy path: task event -> PM + Supervisor both dispatched -----

    def test_task_event_dispatches_to_pm_and_supervisor(self):
        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="task.status_changed", aggregate_type="task",
                aggregate_id=self.task_id, payload={"target_status": "ready"}, key="test:1",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        self.assertEqual(len(deliveries), 2)
        for delivery in deliveries:
            self.assertEqual(delivery.status, "sent")
            self.assertIsNotNone(delivery.provider_message_id)
            self.assertEqual(delivery.attempt_count, 1)
            # `MessageDelivery.template` now stores the registry-mapped Meta
            # template name, not the raw `event_type` string (Phase 1a).
            self.assertEqual(delivery.template, "task_status_update")
        recipient_ids = {d.recipient_employee_id for d in deliveries}
        self.assertEqual(recipient_ids, {self.pm_employee_id, self.supervisor_employee_id})

    # ---- 2. happy path: vendor_assigned adds the vendor's primary contact -

    def test_vendor_assigned_event_adds_vendor_contact_recipient(self):
        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="task.vendor_assigned", aggregate_type="task",
                aggregate_id=self.task_id,
                payload={
                    "task_id": str(self.task_id), "project_id": str(self.project_id),
                    "assignment_id": str(uuid.uuid4()), "vendor_id": str(self.vendor_id),
                },
                key="test:2",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        self.assertEqual(len(deliveries), 3)

        vendor_rows = [d for d in deliveries if d.recipient_vendor_contact_id is not None]
        self.assertEqual(len(vendor_rows), 1)
        self.assertEqual(vendor_rows[0].recipient_vendor_contact_id, self.vendor_contact_id)
        self.assertEqual(vendor_rows[0].recipient_phone, "9000000040")
        self.assertEqual(vendor_rows[0].status, "sent")

        employee_rows = [d for d in deliveries if d.recipient_employee_id is not None]
        self.assertEqual({d.recipient_employee_id for d in employee_rows}, {self.pm_employee_id, self.supervisor_employee_id})

    # ---- 3. edge case: retry after a failed delivery ----------------------

    def test_retry_after_missing_phone_corrected_increments_attempt_count_single_row(self):
        self._set_phone(PM_ID, "")

        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="project.role_change_requested", aggregate_type="project",
                aggregate_id=self.project2_id, payload={}, key="test:3",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0].status, "failed")
        self.assertEqual(deliveries[0].attempt_count, 1)
        self.assertEqual(deliveries[0].failure_code, "missing_phone")

        with self.Session() as session:
            outbox_event = session.get(OutboxEvent, event_id)
            self.assertEqual(outbox_event.status, "dispatched")

        # Correct the phone, then run process_pending() again - the event
        # is 'dispatched' but still carries a 'failed' delivery, so it is
        # re-selected for retry.
        self._set_phone(PM_ID, "9000000099")

        with self.Session() as session:
            processed_again = MessageDispatchService(session).process_pending()
        self.assertEqual(processed_again, 1)

        deliveries = self._deliveries_for(event_id)
        self.assertEqual(len(deliveries), 1, "retry must update the existing row, not create a second one")
        self.assertEqual(deliveries[0].attempt_count, 2)
        self.assertEqual(deliveries[0].status, "sent")
        self.assertIsNotNone(deliveries[0].provider_message_id)
        self.assertEqual(deliveries[0].recipient_phone, "9000000099")

    # ---- 4. error path: one recipient's missing phone doesn't block others

    def test_recipient_without_phone_does_not_block_other_recipients(self):
        self._set_phone(SUPERVISOR_ID, None)

        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="task.status_changed", aggregate_type="task",
                aggregate_id=self.task_id, payload={"target_status": "ready"}, key="test:4",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        self.assertEqual(len(deliveries), 2)

        by_employee = {d.recipient_employee_id: d for d in deliveries}
        supervisor_delivery = by_employee[self.supervisor_employee_id]
        pm_delivery = by_employee[self.pm_employee_id]

        self.assertEqual(supervisor_delivery.status, "failed")
        self.assertEqual(supervisor_delivery.failure_code, "missing_phone")
        self.assertIsNotNone(supervisor_delivery.failure_reason)

        self.assertEqual(pm_delivery.status, "sent")
        self.assertIsNotNone(pm_delivery.provider_message_id)

    # ---- 5. Super Admin can never be selected as a recipient --------------

    def test_super_admin_role_string_never_used_as_an_included_recipient_filter(self):
        """Structural proof (BR-004/R7): `_resolve_recipients` (and its
        helpers) only ever query
        `V2ProjectMembership.project_role in (project_manager,
        site_supervisor)`. `project_role` itself can never hold
        `'super_admin'` (see app.project_models.V2ProjectMembership), so a
        Super Admin - who acts on projects without being a project member -
        structurally cannot be resolved as a notification recipient.

        This is asserted two ways: (a) by inspecting `_ACCOUNTABLE_ROLES`,
        the sole role allow-list `_resolve_pm_supervisor_recipients` uses,
        and (b) by grepping the module source to confirm 'super_admin'
        never appears as an included filter value (only ever, if at all,
        in prose/comments)."""
        self.assertEqual(
            set(message_dispatch_module._ACCOUNTABLE_ROLES), {"project_manager", "site_supervisor"},
        )
        self.assertNotIn("super_admin", message_dispatch_module._ACCOUNTABLE_ROLES)

        source = inspect.getsource(message_dispatch_module)
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "super_admin" in line:
                # The only place 'super_admin' may appear in code (not a
                # comment/docstring line) is inside a string literal used
                # purely for prose - never as a `==`/`in (...)` filter
                # value compared against project_role. Fail loudly if a
                # code line uses it as a filter.
                self.assertNotRegex(
                    line, r"project_role\s*(==|in)\s*.*super_admin",
                    f"'super_admin' used as a project_role filter: {line!r}",
                )

        # End-to-end: even though a super_admin actor drives most of this
        # codebase's mutation routes, they are never themselves resolved as
        # a message recipient because they hold no V2ProjectMembership row
        # with project_role in ('project_manager', 'site_supervisor').
        with self.Session() as session:
            recipients = MessageDispatchService(session)._resolve_pm_supervisor_recipients(self.project_id)
        self.assertTrue(all(r.employee_id in (self.pm_employee_id, self.supervisor_employee_id) for r in recipients))

    # ---- 6. verification: dispatched events are a safe no-op to reprocess -

    def test_process_pending_marks_dispatched_and_rerun_is_a_safe_no_op(self):
        with self.Session() as session:
            event_id_1 = self._create_event(
                session, event_type="task.status_changed", aggregate_type="task",
                aggregate_id=self.task_id, payload={"target_status": "ready"}, key="test:6a",
            )
            event_id_2 = self._create_event(
                session, event_type="project.role_change_requested", aggregate_type="project",
                aggregate_id=self.project_id, payload={}, key="test:6b",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 2)

        with self.Session() as session:
            for event_id in (event_id_1, event_id_2):
                outbox_event = session.get(OutboxEvent, event_id)
                self.assertEqual(outbox_event.status, "dispatched")

        rows_after_first_run = len(self._deliveries_for(event_id_1)) + len(self._deliveries_for(event_id_2))

        with self.Session() as session:
            processed_again = MessageDispatchService(session).process_pending()
        self.assertEqual(processed_again, 0, "already-dispatched events with no failed deliveries must not be re-selected")

        rows_after_second_run = len(self._deliveries_for(event_id_1)) + len(self._deliveries_for(event_id_2))
        self.assertEqual(rows_after_first_run, rows_after_second_run)

    # ---- 7. Phase 1a: template registry fallback + component rendering ----

    def test_unmapped_event_type_falls_back_to_default_template_not_the_raw_string(self):
        spec = resolve("some.event.type.nobody.registered")
        self.assertEqual(spec, DEFAULT_TEMPLATE)
        self.assertEqual(spec.meta_template_name, "generic_notification")
        self.assertNotEqual(spec.meta_template_name, "some.event.type.nobody.registered")

        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="some.event.type.nobody.registered", aggregate_type="project",
                aggregate_id=self.project_id, payload={}, key="test:7a",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        self.assertTrue(deliveries)
        for delivery in deliveries:
            self.assertEqual(delivery.template, "generic_notification")

    def test_render_components_builds_meta_body_parameters_shape_from_payload(self):
        spec = TemplateSpec("sample_template", "en", ("task_id", "target_status"))
        payload = {"task_id": "T001", "target_status": "ready", "unused_key": "ignored"}

        components = render_components(spec, payload)

        self.assertEqual(
            components,
            [{"type": "body", "parameters": [
                {"type": "text", "text": "T001"},
                {"type": "text", "text": "ready"},
            ]}],
        )

    def test_render_components_missing_payload_key_renders_as_empty_string(self):
        spec = TemplateSpec("sample_template", "en", ("missing_key",))
        components = render_components(spec, {})
        self.assertEqual(components, [{"type": "body", "parameters": [{"type": "text", "text": ""}]}])

    # ---- 8. Phase 1b: project_external_approval recipient resolution ------

    def test_project_external_approval_assigned_event_resolves_admin_and_assignee(self):
        approval_id = self._make_gate_approval(assigned_to_user_id=INTERNAL_EMPLOYEE_ID)

        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="project_external_approval.assigned", aggregate_type="project_external_approval",
                aggregate_id=approval_id,
                payload={"approval_id": str(approval_id), "assigned_to_user_id": str(INTERNAL_EMPLOYEE_ID)},
                key="test:8a",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        recipient_employee_ids = {d.recipient_employee_id for d in deliveries}
        self.assertEqual(recipient_employee_ids, {self.internal_employee_employee_id, self.admin_employee_id})
        for delivery in deliveries:
            self.assertEqual(delivery.status, "sent")

    def test_project_external_approval_unassigned_gate_resolves_only_admin(self):
        # No assignee yet - `_resolve_gate_assignee_recipient` returns []
        # (genuinely unresolvable), so only Admin is a recipient.
        approval_id = self._make_gate_approval()

        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="project_external_approval.submitted", aggregate_type="project_external_approval",
                aggregate_id=approval_id, payload={"approval_id": str(approval_id)}, key="test:8b",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        recipient_employee_ids = {d.recipient_employee_id for d in deliveries}
        self.assertEqual(recipient_employee_ids, {self.admin_employee_id})

    def test_task_approval_recorded_event_resolves_admin_as_cc_alongside_pm_supervisor(self):
        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="task.approval_recorded", aggregate_type="task",
                aggregate_id=self.task_id, payload={"decision": "approved"}, key="test:8c",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        recipient_employee_ids = {d.recipient_employee_id for d in deliveries}
        self.assertEqual(
            recipient_employee_ids,
            {self.pm_employee_id, self.supervisor_employee_id, self.admin_employee_id},
        )

    def test_task_status_changed_event_does_not_resolve_admin(self):
        # task.status_changed is NOT in _ADMIN_CC_TASK_EVENTS - only PM/
        # Supervisor are resolved, same as before Phase 1b.
        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="task.status_changed", aggregate_type="task",
                aggregate_id=self.task_id, payload={"target_status": "ready"}, key="test:8d",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        recipient_employee_ids = {d.recipient_employee_id for d in deliveries}
        self.assertEqual(recipient_employee_ids, {self.pm_employee_id, self.supervisor_employee_id})
        self.assertNotIn(self.admin_employee_id, recipient_employee_ids)


if __name__ == "__main__":
    unittest.main()
