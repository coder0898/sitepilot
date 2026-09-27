"""Telegram T2: onboarding and assignment messages with Acknowledge buttons
(app/services/telegram_assignment_render.py, telegram_ack_callback.py).

Internal people get English messages with [Acknowledge Assignment] /
[Acknowledge]; vendor contacts get English + Hindi with
[Acknowledge / स्वीकार करें]. A press is a receipt only: it sets
`acknowledged_at` (or, for a vendor task, records the same acknowledgement a
typed ACCEPT does) and never touches a task's lifecycle.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.execution_models import Task, TaskSupportAssignment, TelegramInboundUpdate
from app.project_models import V2ProjectMembership
from app.services.telegram_ack_callback import PRIVATE_ONLY, STALE, UNLINKED, TelegramAckCallbackService
from app.services.telegram_message import ack_callback
from app.services.telegram_render import render_telegram
from app.vendor_models import ProjectVendor, TaskVendorAssignment, V2Vendor, V2VendorContact, VendorAcknowledgement
from tests.test_telegram_task_callback import EMPLOYEE_CHAT, OTHER_CHAT, UNLINKED_CHAT, TaskButtonHarness

VENDOR_CHAT, OTHER_VENDOR_CHAT = "800", "801"


class TelegramAckHarness(TaskButtonHarness):
    def setUp(self):
        super().setUp()
        for table in (
            V2Vendor.__table__, ProjectVendor.__table__, TaskVendorAssignment.__table__, VendorAcknowledgement.__table__,
        ):
            table.create(self.engine)
        with self.session.begin():
            self.vendor, self.vendor_contact = self._vendor("Acme Electricals", VENDOR_CHAT)
            self.other_vendor, self.other_vendor_contact = self._vendor("Other Works", OTHER_VENDOR_CHAT)
            self.mapping = ProjectVendor(project_id=self.project.id, vendor_id=self.vendor.id, mapped_by=self.admin[0].id)
            self.session.add(self.mapping)
            self.session.flush()
            self.vendor_assignment = TaskVendorAssignment(
                task_id=self.task.id, project_id=self.project.id, vendor_id=self.vendor.id, assigned_by=self.pm[0].id,
            )
            self.session.add(self.vendor_assignment)
            self.session.flush()
        self.support = self.session.scalar(select(TaskSupportAssignment).where(TaskSupportAssignment.task_id == self.task.id))
        self.employee_membership = self.session.scalar(
            select(V2ProjectMembership).where(
                V2ProjectMembership.project_id == self.project.id,
                V2ProjectMembership.employee_id == self.employee[1].id,
            )
        )
        self.session.commit()

    def _vendor(self, name, chat_id):
        vendor = V2Vendor(name=name, contact_person="Ramesh", phone=f"+91{chat_id}")
        self.session.add(vendor)
        self.session.flush()
        contact = V2VendorContact(
            vendor_id=vendor.id, name="Ramesh", phone=f"+91{chat_id}", telegram_chat_id=chat_id,
            active_channel="telegram", is_primary=True,
        )
        self.session.add(contact)
        self.session.flush()
        return vendor, contact

    def ack(self, chat_id, data, *, chat_type="private", from_id=None) -> bool:
        self.update_id += 1
        self.session.add(TelegramInboundUpdate(update_id=self.update_id, chat_id=chat_id, callback_data=data, raw_payload={}))
        self.session.commit()
        return TelegramAckCallbackService(self.session).handle(
            update_id=self.update_id, chat_id=chat_id, chat_type=chat_type,
            from_id=from_id if from_id is not None else chat_id, message_id=42,
            callback_query_id=f"cb{self.update_id}", data=data,
        )

    def toast(self) -> str:
        return self.calls("answerCallbackQuery")[-1]["text"]

    def fresh(self, model, row_id):
        self.session.expire_all()
        return self.session.get(model, row_id)


class AssignmentRenderTests(TelegramAckHarness):
    def _project_payload(self):
        return {"project_id": str(self.project.id), "project_name": self.project.name}

    def test_project_activated_offers_acknowledge_assignment_until_acknowledged(self):
        message = render_telegram(self.session, "project.activated", self._project_payload(), self.employee[1].id)
        self.assertIn("Welcome to PRJ-A", message.text)
        self.assertIn("Your role: Internal Employee", message.text)
        [[button]] = message.button_rows()
        self.assertEqual(button, {"text": "Acknowledge Assignment", "callback_data": ack_callback("pm", self.employee_membership.id)})

        self.assertTrue(self.ack(EMPLOYEE_CHAT, button["callback_data"]))
        again = render_telegram(self.session, "project.activated", self._project_payload(), self.employee[1].id)
        self.assertEqual(again.button_rows(), [])

    def test_member_added_welcomes_the_new_member_and_informs_everyone_else(self):
        payload = {"project_id": str(self.project.id), "employee_id": str(self.employee[1].id), "project_role": "internal_employee"}
        welcome = render_telegram(self.session, "project.member_added", payload, self.employee[1].id)
        self.assertIn("Added to Project Team", welcome.text)
        self.assertEqual(welcome.button_rows()[0][0]["callback_data"], ack_callback("pm", self.employee_membership.id))

        others = render_telegram(self.session, "project.member_added", payload, self.supervisor[1].id)
        self.assertIn("New Team Member", others.text)
        self.assertIn("Member: Rohan", others.text)
        self.assertEqual(others.button_rows(), [])

    def test_support_assigned_offers_acknowledge_before_the_task_button(self):
        payload = {
            "task_id": str(self.task.id), "project_id": str(self.project.id), "assignment_id": str(self.support.id),
            "employee_id": str(self.employee[1].id), "responsibility": "Execution",
        }
        message = render_telegram(self.session, "task.support_assigned", payload, self.employee[1].id)
        self.assertIn("Task Assigned to You", message.text)
        self.assertIn("T001", message.text)
        rows = message.button_rows()
        self.assertEqual(rows[0][0], {"text": "Acknowledge", "callback_data": ack_callback("sa", self.support.id)})
        self.assertEqual(rows[1][0]["text"], "Mark Task Ready")

        self.ack(EMPLOYEE_CHAT, ack_callback("sa", self.support.id))
        again = render_telegram(self.session, "task.support_assigned", payload, self.employee[1].id)
        self.assertNotIn("Acknowledge", [row[0]["text"] for row in again.button_rows()])

    def test_vendor_gets_bilingual_project_assignment_with_acknowledge(self):
        message = render_telegram(self.session, "project.activated", self._project_payload(), None, self.vendor_contact.id)
        self.assertIn("Project Assignment / प्रोजेक्ट असाइनमेंट", message.text)
        self.assertIn("कृपया पुष्टि करें", message.text)
        [[button]] = message.button_rows()
        self.assertEqual(button, {"text": "Acknowledge / स्वीकार करें", "callback_data": ack_callback("pv", self.mapping.id)})

    def test_vendor_mapped_welcomes_that_vendor_and_informs_other_vendors(self):
        payload = {"project_id": str(self.project.id), "vendor_id": str(self.vendor.id)}
        own = render_telegram(self.session, "project.vendor_mapped", payload, None, self.vendor_contact.id)
        self.assertEqual(own.button_rows()[0][0]["callback_data"], ack_callback("pv", self.mapping.id))

        other = render_telegram(self.session, "project.vendor_mapped", payload, None, self.other_vendor_contact.id)
        self.assertIn("प्रोजेक्ट में नया वेंडर जोड़ा गया", other.text)
        self.assertEqual(other.button_rows(), [])

        internal = render_telegram(self.session, "project.vendor_mapped", payload, self.supervisor[1].id)
        self.assertIn("Vendor Added to Project", internal.text)
        self.assertIn("Acme Electricals", internal.text)

    def test_vendor_task_assignment_is_bilingual_with_acknowledge_and_typed_decline(self):
        payload = {
            "task_id": str(self.task.id), "project_id": str(self.project.id),
            "assignment_id": str(self.vendor_assignment.id), "vendor_id": str(self.vendor.id),
        }
        message = render_telegram(self.session, "task.vendor_assigned", payload, None, self.vendor_contact.id)
        self.assertIn("New Task Assigned / नया कार्य सौंपा गया", message.text)
        self.assertIn("T001 - Task T001", message.text)
        [[button]] = message.button_rows()
        self.assertEqual(button, {"text": "Acknowledge / स्वीकार करें", "callback_data": ack_callback("va", self.vendor_assignment.id)})
        self.assertIn(f"DECLINE {self.vendor_assignment.id.hex[:8]}", message.text_for_buttons())

        internal = render_telegram(self.session, "task.vendor_assigned", payload, self.pm[1].id)
        self.assertIn("Vendor Assigned to Task", internal.text)
        self.assertNotIn("ACCEPT", internal.text_for_buttons())
        self.assertEqual(internal.button_rows(), [])


class AcknowledgePressTests(TelegramAckHarness):
    def test_member_acknowledges_their_project_assignment_once(self):
        data = ack_callback("pm", self.employee_membership.id)
        self.assertTrue(self.ack(EMPLOYEE_CHAT, data))
        self.assertIsNotNone(self.fresh(V2ProjectMembership, self.employee_membership.id).acknowledged_at)
        self.assertIn("Assignment Acknowledged", self.last_reply())
        self.assertTrue(self.calls("editMessageReplyMarkup"))
        self.assertEqual(self.last_inbound().processing_status, "processed")

        self.assertFalse(self.ack(EMPLOYEE_CHAT, data))
        self.assertEqual(self.toast(), "Already acknowledged")

    def test_one_press_acknowledges_every_active_role_on_the_project(self):
        with self.session.begin():
            self._member(self.project, self.employee, "site_supervisor")
        self.ack(EMPLOYEE_CHAT, ack_callback("pm", self.employee_membership.id))
        self.session.expire_all()
        rows = self.session.scalars(select(V2ProjectMembership).where(
            V2ProjectMembership.project_id == self.project.id, V2ProjectMembership.employee_id == self.employee[1].id,
        )).all()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row.acknowledged_at is not None for row in rows))

    def test_someone_else_cannot_acknowledge_a_membership(self):
        self.assertFalse(self.ack(OTHER_CHAT, ack_callback("pm", self.employee_membership.id)))
        self.assertIsNone(self.fresh(V2ProjectMembership, self.employee_membership.id).acknowledged_at)
        self.assertIn(STALE, self.last_reply())
        self.assertEqual(self.last_inbound().processing_status, "rejected")

    def test_ended_membership_is_no_longer_available(self):
        with self.session.begin():
            self.session.get(V2ProjectMembership, self.employee_membership.id).ends_at = datetime.now(timezone.utc)
        self.assertFalse(self.ack(EMPLOYEE_CHAT, ack_callback("pm", self.employee_membership.id)))
        self.assertIn(STALE, self.last_reply())

    def test_assignee_acknowledges_task_without_changing_its_status(self):
        self.assertTrue(self.ack(EMPLOYEE_CHAT, ack_callback("sa", self.support.id)))
        self.assertIsNotNone(self.fresh(TaskSupportAssignment, self.support.id).acknowledged_at)
        self.assertEqual(self.fresh(Task, self.task.id).lifecycle_status, "planned")
        self.assertIn("Task Acknowledged", self.last_reply())

    def test_non_assignee_cannot_acknowledge_a_task_assignment(self):
        self.assertFalse(self.ack(OTHER_CHAT, ack_callback("sa", self.support.id)))
        self.assertIsNone(self.fresh(TaskSupportAssignment, self.support.id).acknowledged_at)

    def test_group_chat_and_other_presser_are_refused(self):
        data = ack_callback("sa", self.support.id)
        self.assertFalse(self.ack(EMPLOYEE_CHAT, data, chat_type="group"))
        self.assertIn(PRIVATE_ONLY, self.last_reply())
        self.assertFalse(self.ack(EMPLOYEE_CHAT, data, from_id="12345"))
        self.assertIsNone(self.fresh(TaskSupportAssignment, self.support.id).acknowledged_at)

    def test_unlinked_chat_is_refused(self):
        self.assertFalse(self.ack(UNLINKED_CHAT, ack_callback("pm", self.employee_membership.id)))
        self.assertIn(UNLINKED, self.last_reply())

    def test_vendor_acknowledges_project_assignment_in_both_languages(self):
        data = ack_callback("pv", self.mapping.id)
        self.assertTrue(self.ack(VENDOR_CHAT, data))
        self.assertIsNotNone(self.fresh(ProjectVendor, self.mapping.id).acknowledged_at)
        self.assertIn("स्वीकार किया गया", self.last_reply())
        self.assertEqual(self.toast(), "Acknowledged / स्वीकार किया गया")

        self.assertFalse(self.ack(VENDOR_CHAT, data))
        self.assertEqual(self.toast(), "Already acknowledged / पहले ही स्वीकार किया जा चुका है")

    def test_other_vendor_cannot_acknowledge_the_mapping(self):
        self.assertFalse(self.ack(OTHER_VENDOR_CHAT, ack_callback("pv", self.mapping.id)))
        self.assertIsNone(self.fresh(ProjectVendor, self.mapping.id).acknowledged_at)
        self.assertIn("यह बटन अब उपलब्ध नहीं है", self.last_reply())

    def test_employee_chat_cannot_press_a_vendor_button(self):
        self.assertFalse(self.ack(EMPLOYEE_CHAT, ack_callback("pv", self.mapping.id)))
        self.assertIn(UNLINKED, self.last_reply())

    def test_vendor_task_acknowledgement_matches_typed_accept(self):
        data = ack_callback("va", self.vendor_assignment.id)
        self.assertTrue(self.ack(VENDOR_CHAT, data))
        self.assertEqual(self.fresh(TaskVendorAssignment, self.vendor_assignment.id).status, "acknowledged")
        [record] = self.session.scalars(select(VendorAcknowledgement)).all()
        self.assertEqual((record.response, record.channel, record.recorded_by), ("accepted", "telegram", self.pm[0].id))
        self.assertEqual(self.fresh(Task, self.task.id).lifecycle_status, "planned")
        self.assertIn("Task / कार्य: T001 - Task T001", self.last_reply())

        self.assertFalse(self.ack(VENDOR_CHAT, data))
        self.assertEqual(self.toast(), "Already acknowledged / पहले ही स्वीकार किया जा चुका है")
        self.assertEqual(len(self.session.scalars(select(VendorAcknowledgement)).all()), 1)

    def test_other_vendor_cannot_acknowledge_a_task(self):
        self.assertFalse(self.ack(OTHER_VENDOR_CHAT, ack_callback("va", self.vendor_assignment.id)))
        self.assertEqual(self.fresh(TaskVendorAssignment, self.vendor_assignment.id).status, "pending_ack")

    def test_the_web_app_reads_back_when_it_was_acknowledged(self):
        from app.routes.projects_v2 import membership_json
        from app.schemas.execution_tasks import TaskSupportAssignmentOut

        self.assertIsNone(membership_json(self.session, self.employee_membership)["acknowledged_at"])
        self.ack(EMPLOYEE_CHAT, ack_callback("pm", self.employee_membership.id))
        self.ack(EMPLOYEE_CHAT, ack_callback("sa", self.support.id))
        self.assertIsNotNone(membership_json(self.session, self.fresh(V2ProjectMembership, self.employee_membership.id))["acknowledged_at"])
        support = TaskSupportAssignmentOut.model_validate(self.fresh(TaskSupportAssignment, self.support.id))
        self.assertIsNotNone(support.acknowledged_at)

    def test_malformed_button_is_stale(self):
        self.assertFalse(self.ack(EMPLOYEE_CHAT, f"a1:zz:{uuid.uuid4().hex}"))
        self.assertIn(STALE, self.last_reply())
