from __future__ import annotations

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
from app.execution_models import (
    BaselineTask,
    FileObject,
    OutboxEvent,
    ProjectBaseline,
    Task,
    TaskApprovalDecision,
    TaskDependency,
    TaskEvidence,
    TaskProgressUpdate,
    TaskVerification,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership, V2ProjectTask, V2ProjectTaskDependency
from app.routes.execution_tasks_v2 import router as execution_tasks_router
from app.routes.projects_v2 import router as projects_router
from app.template_models import V2Template, V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
OUTSIDER_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")
SECOND_PM_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")


class TaskVerificationApprovalApiTests(unittest.TestCase):
    """U4: Supervisor verification and PM approval decisions (BR-008),
    against real execution tasks produced by U1's baseline-lock activation
    flow. Follows the same SQLite-ATTACHed-schema harness pattern as
    test_task_lifecycle_transitions_v2.py / test_task_progress_evidence_v2.py.
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
            V2AuditEvent.__table__,
            ProjectBaseline.__table__,
            BaselineTask.__table__,
            Task.__table__,
            TaskDependency.__table__,
            TaskProgressUpdate.__table__,
            FileObject.__table__,
            TaskEvidence.__table__,
            TaskVerification.__table__,
            TaskApprovalDecision.__table__,
            OutboxEvent.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()

        self.app = FastAPI()
        self.app.include_router(projects_router)
        self.app.include_router(execution_tasks_router)

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

    def act_as_supervisor(self) -> None:
        self.act_as(User(
            id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com",
            role=UserRole.supervisor, active=True,
        ))

    def act_as_pm(self) -> None:
        self.act_as(User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True))

    def act_as_outsider(self) -> None:
        self.act_as(User(
            id=OUTSIDER_ID, name="Outsider", email="outsider@example.com",
            role=UserRole.supervisor, active=True,
        ))

    # ---- seeding -------------------------------------------------------

    def _seed(self):
        """Seeds a 5-task template:
        T001 (work, standard), T002 (work, class_a), T003 (approval_gate,
        class_a) all standalone, plus T004 (work, standard) depending on
        T002 (blocking finish_to_start) - used for the predecessor-unblock
        integration test. A second PM (SECOND_PM_ID) is also seeded (but
        not given project membership at project-creation time) so tests
        can add them as a project member later for the fallback-verifier
        scenario.
        """
        with self.Session.begin() as session:
            admin = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
            pm = User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True)
            supervisor = User(
                id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com",
                role=UserRole.supervisor, active=True,
            )
            outsider = User(
                id=OUTSIDER_ID, name="Outsider", email="outsider@example.com",
                role=UserRole.supervisor, active=True,
            )
            second_pm = User(
                id=SECOND_PM_ID, name="PM Two", email="pm2@example.com",
                role=UserRole.project_manager, active=True,
            )
            session.add_all([admin, pm, supervisor, outsider, second_pm])
            session.flush()
            session.add_all([
                EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                EmployeeProfile(
                    user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor", availability="available",
                ),
                EmployeeProfile(
                    user_id=OUTSIDER_ID, employee_code="OUT-001", designation="Supervisor", availability="available",
                ),
                EmployeeProfile(
                    user_id=SECOND_PM_ID, employee_code="PM-002", designation="PM", availability="available",
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

            specs = [
                ("T001", "work", "standard"),
                ("T002", "work", "class_a"),
                ("T003", "approval_gate", "class_a"),
                ("T004", "work", "standard"),
            ]
            template_tasks = []
            for i, (code, kind, klass) in enumerate(specs, start=1):
                template_tasks.append(V2TemplateTask(
                    template_version_id=published.id, code=code, sequence_no=i, title=f"Task {code}",
                    schedule_classification="execution", planned_start_day=i, planned_end_day=i,
                    applicability="mandatory", task_class=klass, task_kind=kind,
                    evidence_required=False, duration_days=1, phase="Setup", category="Site",
                ))
            session.add_all(template_tasks)
            session.flush()

            # T002 (class_a work) blocks T004 (standard work) - used to
            # test that a Class A predecessor only unblocks once PM-approved
            # (not merely Supervisor-verified).
            session.add(V2TemplateTaskDependency(
                template_version_id=published.id,
                predecessor_task_id=template_tasks[1].id,
                successor_task_id=template_tasks[3].id,
                dependency_type="finish_to_start", blocking=True,
                rule_text="T002 blocks T004", sequence_no=1,
            ))
            self.published_version_id = published.id

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

    def tasks_by_code(self, project_id: str) -> dict[str, Task]:
        with self.Session() as session:
            rows = session.scalars(select(Task).where(Task.project_id == uuid.UUID(project_id))).all()
            return {t.original_code: t for t in rows}

    def transition(self, project_id: str, task_id, target_status: str, reason: str | None = None):
        body: dict = {"target_status": target_status}
        if reason is not None:
            body["reason"] = reason
        return self.client.post(f"/api/v2/projects/{project_id}/tasks/{task_id}/status", json=body)

    def submit_progress(self, project_id: str, task_id, note="Work done."):
        return self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/progress", data={"note": note},
        )

    def verify(self, project_id: str, task_id, decision: str, remarks: str | None = None):
        body: dict = {"decision": decision}
        if remarks is not None:
            body["remarks"] = remarks
        return self.client.post(f"/api/v2/projects/{project_id}/tasks/{task_id}/verify", json=body)

    def approve(self, project_id: str, task_id, decision: str, remarks: str | None = None):
        body: dict = {"decision": decision}
        if remarks is not None:
            body["remarks"] = remarks
        return self.client.post(f"/api/v2/projects/{project_id}/tasks/{task_id}/approve", json=body)

    def drive_to_submitted(self, project_id: str, task_id):
        self.act_as_supervisor()
        for target in ("ready", "in_progress"):
            r = self.transition(project_id, task_id, target)
            self.assertEqual(r.status_code, 200, r.text)
        sp = self.submit_progress(project_id, task_id)
        self.assertEqual(sp.status_code, 200, sp.text)
        r = self.transition(project_id, task_id, "submitted")
        self.assertEqual(r.status_code, 200, r.text)

    # ---- happy paths ----------------------------------------------------

    def test_supervisor_verifies_standard_work_task_and_it_completes(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.drive_to_submitted(project["id"], t001.id)

        self.act_as_supervisor()
        r = self.verify(project["id"], t001.id, "verified")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["task"]["lifecycle_status"], "completed")

        with self.Session() as session:
            self.assertEqual(session.get(Task, t001.id).lifecycle_status, "completed")
            verifications = session.scalars(
                select(TaskVerification).where(TaskVerification.task_id == t001.id)
            ).all()
            self.assertEqual(len(verifications), 1)
            self.assertEqual(verifications[0].decision, "verified")

    def test_class_a_work_requires_verification_then_pm_approval_to_complete(self):
        project = self.activate_project()
        t002 = self.tasks_by_code(project["id"])["T002"]
        self.drive_to_submitted(project["id"], t002.id)

        self.act_as_supervisor()
        r = self.verify(project["id"], t002.id, "verified")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["task"]["lifecycle_status"], "verified")

        self.act_as_pm()
        approve_response = self.approve(project["id"], t002.id, "approved")
        self.assertEqual(approve_response.status_code, 200, approve_response.text)
        self.assertEqual(approve_response.json()["task"]["lifecycle_status"], "completed")
        self.assertIsNotNone(approve_response.json()["verification_id"])

        with self.Session() as session:
            self.assertEqual(session.get(Task, t002.id).lifecycle_status, "completed")

    def test_pm_approves_approval_gate_directly_without_verification(self):
        project = self.activate_project()
        t003 = self.tasks_by_code(project["id"])["T003"]
        self.drive_to_submitted(project["id"], t003.id)

        with self.Session() as session:
            self.assertEqual(
                session.scalar(select(TaskVerification).where(TaskVerification.task_id == t003.id)), None,
            )

        self.act_as_pm()
        r = self.approve(project["id"], t003.id, "approved")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["task"]["lifecycle_status"], "completed")
        self.assertIsNone(r.json()["verification_id"])

    # ---- edge cases: role gating -----------------------------------------

    def test_non_supervisor_cannot_verify(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.drive_to_submitted(project["id"], t001.id)

        self.act_as_outsider()
        r = self.verify(project["id"], t001.id, "verified")
        self.assertEqual(r.status_code, 403, r.text)

    def test_non_pm_cannot_approve_class_a_or_gate(self):
        project = self.activate_project()
        t002 = self.tasks_by_code(project["id"])["T002"]
        self.drive_to_submitted(project["id"], t002.id)
        self.act_as_supervisor()
        r = self.verify(project["id"], t002.id, "verified")
        self.assertEqual(r.status_code, 200, r.text)

        self.act_as_outsider()
        approve_response = self.approve(project["id"], t002.id, "approved")
        self.assertEqual(approve_response.status_code, 403, approve_response.text)

        t003 = self.tasks_by_code(project["id"])["T003"]
        self.drive_to_submitted(project["id"], t003.id)
        self.act_as_outsider()
        gate_response = self.approve(project["id"], t003.id, "approved")
        self.assertEqual(gate_response.status_code, 403, gate_response.text)

    def test_verifying_task_not_in_submitted_status_is_rejected(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        # T001 still "planned" - never driven to submitted.
        self.act_as_supervisor()
        r = self.verify(project["id"], t001.id, "verified")
        self.assertEqual(r.status_code, 409, r.text)

    # ---- rejection ---------------------------------------------------------

    def test_rejection_without_reason_is_rejected_with_reason_reopens_task(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.drive_to_submitted(project["id"], t001.id)

        self.act_as_supervisor()
        no_reason = self.verify(project["id"], t001.id, "rejected")
        self.assertEqual(no_reason.status_code, 422, no_reason.text)

        with_reason = self.verify(project["id"], t001.id, "rejected", remarks="Rework the finish.")
        self.assertEqual(with_reason.status_code, 200, with_reason.text)
        self.assertEqual(with_reason.json()["task"]["lifecycle_status"], "in_progress")

        with self.Session() as session:
            self.assertEqual(session.get(Task, t001.id).lifecycle_status, "in_progress")

    def test_approval_rejection_without_reason_is_rejected_with_reason_reopens_task(self):
        project = self.activate_project()
        t003 = self.tasks_by_code(project["id"])["T003"]
        self.drive_to_submitted(project["id"], t003.id)

        self.act_as_pm()
        no_reason = self.approve(project["id"], t003.id, "rejected")
        self.assertEqual(no_reason.status_code, 422, no_reason.text)

        with_reason = self.approve(project["id"], t003.id, "rejected", remarks="Missing signature.")
        self.assertEqual(with_reason.status_code, 200, with_reason.text)
        self.assertEqual(with_reason.json()["task"]["lifecycle_status"], "in_progress")

    # ---- fallback verifier cannot also approve ------------------------------

    def test_fallback_pm_verifier_cannot_also_approve_but_a_different_actor_can(self):
        project = self.activate_project()
        t002 = self.tasks_by_code(project["id"])["T002"]
        self.drive_to_submitted(project["id"], t002.id)

        # PM verifies as a Supervisor fallback (not the active Supervisor) -
        # the project's active PM is a permitted verifier per
        # TaskVerificationService._require_verifier, but is not the active
        # Supervisor, so this is the "fallback verifier" case BR-008 flags.
        self.act_as_pm()
        r = self.verify(project["id"], t002.id, "verified")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["task"]["lifecycle_status"], "verified")

        # The same PM cannot also record this task's approval decision.
        same_pm = self.approve(project["id"], t002.id, "approved")
        self.assertEqual(same_pm.status_code, 409, same_pm.text)

        # A different authorized actor (Admin) can.
        self.act_as_admin()
        different_actor = self.approve(project["id"], t002.id, "approved")
        self.assertEqual(different_actor.status_code, 200, different_actor.text)
        self.assertEqual(different_actor.json()["task"]["lifecycle_status"], "completed")

    # ---- integration: predecessor decision unblocks successor ---------------

    def test_class_a_predecessor_only_unblocks_successor_once_pm_approved(self):
        project = self.activate_project()
        tasks = self.tasks_by_code(project["id"])
        t002, t004 = tasks["T002"], tasks["T004"]

        self.drive_to_submitted(project["id"], t002.id)
        self.act_as_supervisor()
        r = self.verify(project["id"], t002.id, "verified")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["task"]["lifecycle_status"], "verified")

        # T002 is merely "verified" (Supervisor-verified, not yet
        # PM-approved) - per BR-008, Class A predecessors require PM
        # approval (completed), so T004 must still be blocked.
        self.act_as_supervisor()
        ready = self.transition(project["id"], t004.id, "ready")
        self.assertEqual(ready.status_code, 200, ready.text)
        still_blocked = self.transition(project["id"], t004.id, "in_progress")
        self.assertEqual(still_blocked.status_code, 409, still_blocked.text)

        # PM approves T002 -> completed.
        self.act_as_pm()
        approve_response = self.approve(project["id"], t002.id, "approved")
        self.assertEqual(approve_response.status_code, 200, approve_response.text)
        self.assertEqual(approve_response.json()["task"]["lifecycle_status"], "completed")

        # Now T004 unblocks.
        self.act_as_supervisor()
        unblocked = self.transition(project["id"], t004.id, "in_progress")
        self.assertEqual(unblocked.status_code, 200, unblocked.text)
        self.assertEqual(unblocked.json()["lifecycle_status"], "in_progress")


if __name__ == "__main__":
    unittest.main()
