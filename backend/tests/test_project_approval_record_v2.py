"""U4/U1 (plan: External Approval Gate Assignment & Evidence Lifecycle): the
execution-layer external approval record.

Pins the runtime contract the readiness engine depends on: an approval that
was instantiated from a planning-layer gate is `unassigned` until an Admin
assigns it, a decided approval always carries who decided and when, and
every status past `unassigned` names an assignee.

The planning-layer `siteops_v2.project_external_gates.status` is deliberately
NOT what these tests exercise. That column is a Draft-time review marker;
this table answers the separate runtime question of whether the approval has
actually been granted.

These assertions run against SQLite built from ORM metadata, so they prove
the *model's* declared shape. The migration carries the authoritative
Postgres constraints - see its own verification for those.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.execution_models import EXTERNAL_APPROVAL_STATUSES, ProjectExternalApproval
from app.models import User
from app.project_models import V2Project, V2ProjectExternalGate
from app.template_models import V2Template, V2TemplateExternalGate, V2TemplateVersion


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


DECIDED_STATUSES = ("approved", "rejected")
PRE_DECISION_STATUSES = ("unassigned", "assigned", "submitted")


class ProjectExternalApprovalTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            # The gate tables' broad-text CHECK uses Postgres's btrim(), which
            # SQLite has no builtin for. Same shim as
            # test_task_lifecycle_transitions_v2.py.
            dbapi_connection.create_function(
                "btrim", 1, lambda value: value.strip() if value is not None else None
            )

        # ProjectExternalApproval carries FKs to users, projects and the
        # planning-layer gate, so those tables must exist before it can be
        # created - even though this unit only ever writes its own table.
        for table in (
            User.__table__,
            V2Template.__table__,
            V2TemplateVersion.__table__,
            V2TemplateExternalGate.__table__,
            V2Project.__table__,
            V2ProjectExternalGate.__table__,
            ProjectExternalApproval.__table__,
        ):
            table.create(bind=self.engine, checkfirst=True)
        self.Session = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _approval(self, **overrides) -> ProjectExternalApproval:
        values = {
            "id": uuid.uuid4(),
            "project_id": uuid.uuid4(),
            # Overridable: the gate-link test supplies its own id so it can
            # assert the approval points back at that exact gate.
            "project_gate_id": uuid.uuid4(),
        }
        values.update(overrides)
        approval = ProjectExternalApproval(**values)
        self.db.add(approval)
        self.db.commit()
        self.db.refresh(approval)
        return approval

    def test_the_five_statuses_are_exactly_the_assign_submit_decide_lifecycle(self):
        self.assertEqual(
            EXTERNAL_APPROVAL_STATUSES,
            ("unassigned", "assigned", "submitted", "approved", "rejected"),
        )

    def test_a_new_approval_defaults_to_unassigned(self):
        approval = self._approval()
        self.assertEqual(approval.status, "unassigned")

    def test_a_new_approval_links_back_to_the_gate_it_came_from(self):
        gate_id = uuid.uuid4()
        approval = self._approval(project_gate_id=gate_id)
        self.assertEqual(approval.project_gate_id, gate_id)

    def test_an_unassigned_approval_has_neither_decider_nor_decision_timestamp(self):
        approval = self._approval()
        self.assertIsNone(approval.decided_by)
        self.assertIsNone(approval.decided_at)

    def test_an_unassigned_approval_has_no_assignee(self):
        approval = self._approval()
        self.assertIsNone(approval.assigned_to_user_id)
        self.assertIsNone(approval.assigned_by)
        self.assertIsNone(approval.assigned_at)

    def test_each_of_the_five_statuses_persists_and_reads_back(self):
        decided_at = datetime(2026, 8, 13, 9, 15, tzinfo=timezone.utc)
        decider = uuid.uuid4()
        assignee = uuid.uuid4()
        assigner = uuid.uuid4()
        for status in EXTERNAL_APPROVAL_STATUSES:
            with self.subTest(status=status):
                decided = status in DECIDED_STATUSES
                approval = self._approval(
                    status=status,
                    assigned_to_user_id=None if status == "unassigned" else assignee,
                    assigned_by=None if status == "unassigned" else assigner,
                    assigned_at=None if status == "unassigned" else datetime(2026, 8, 14, tzinfo=timezone.utc),
                    decided_by=decider if decided else None,
                    decided_at=decided_at if decided else None,
                )
                reloaded = self.db.get(ProjectExternalApproval, approval.id)
                self.assertEqual(reloaded.status, status)

    def test_a_decided_approval_records_both_decider_and_timestamp(self):
        decider = uuid.uuid4()
        assignee = uuid.uuid4()
        decided_at = datetime(2026, 8, 13, 9, 15, tzinfo=timezone.utc)
        approval = self._approval(
            status="approved", assigned_to_user_id=assignee, assigned_by=decider,
            assigned_at=decided_at, decided_by=decider, decided_at=decided_at,
        )
        self.assertEqual(approval.decided_by, decider)
        self.assertEqual(approval.decided_at.year, 2026)
        self.assertEqual(approval.decided_at.hour, 9)

    def test_a_rejection_reason_persists_independently_of_the_decision_pair(self):
        """rejection_reason survives the rejected -> assigned reset that
        clears decided_by/decided_at (see project_gate_decision.py) - it is
        not gated by the same completeness check."""
        approval = self._approval(
            status="assigned",
            assigned_to_user_id=uuid.uuid4(), assigned_by=uuid.uuid4(),
            assigned_at=datetime(2026, 8, 14, tzinfo=timezone.utc),
            rejection_reason="Fire NOC refused by the authority.",
        )
        self.assertIsNone(approval.decided_by)
        self.assertIsNone(approval.decided_at)
        self.assertEqual(approval.rejection_reason, "Fire NOC refused by the authority.")

    def test_a_status_outside_the_five_is_rejected(self):
        with self.assertRaises(IntegrityError):
            self._approval(status="pending")
        self.db.rollback()

    def test_an_unassigned_approval_may_not_carry_a_decider(self):
        """Unassigned means undecided; a decider on an unassigned row would
        make the readiness engine and the audit trail disagree."""
        with self.assertRaises(IntegrityError):
            self._approval(status="unassigned", decided_by=uuid.uuid4())
        self.db.rollback()

    def test_a_decided_approval_may_not_omit_its_decision_metadata(self):
        with self.assertRaises(IntegrityError):
            self._approval(status="approved", assigned_to_user_id=uuid.uuid4())
        self.db.rollback()

        with self.assertRaises(IntegrityError):
            self._approval(status="rejected", assigned_to_user_id=uuid.uuid4(), decided_by=uuid.uuid4())
        self.db.rollback()

    def test_an_unassigned_approval_may_not_carry_an_assignee(self):
        with self.assertRaises(IntegrityError):
            self._approval(status="unassigned", assigned_to_user_id=uuid.uuid4())
        self.db.rollback()

    def test_a_status_past_unassigned_must_carry_an_assignee(self):
        for status in ("assigned", "submitted"):
            with self.subTest(status=status):
                with self.assertRaises(IntegrityError):
                    self._approval(status=status)
                self.db.rollback()

    def test_model_declares_the_status_completeness_and_assignment_check_constraints(self):
        names = {c.name for c in ProjectExternalApproval.__table__.constraints if c.name}
        for name in (
            "ck_v2_project_external_approvals_status",
            "ck_v2_project_external_approvals_decision_completeness",
            "ck_v2_project_external_approvals_assignment_completeness",
            "uq_v2_project_external_approvals_gate",
        ):
            self.assertIn(name, names)

    def test_the_table_lives_in_the_v2_schema_with_the_expected_columns(self):
        columns = {
            c["name"]
            for c in inspect(self.engine).get_columns("project_external_approvals", schema="siteops_v2")
        }
        self.assertEqual(
            columns,
            {
                "id", "project_id", "project_gate_id", "status",
                "assigned_to_user_id", "assigned_by", "assigned_at", "rejection_reason",
                "decided_by", "decided_at", "created_at", "updated_at",
                # U8 copies these three from the planning-layer gate at
                # activation, so readiness can answer what an approval covers
                # and whether it gates work without reading the planning
                # tables (KTD8).
                "blocking", "coverage_state", "coverage_text",
                # Phase 5: resolved from the gate's required_by_type/value
                # at activation (project_gate_due_date.py). Nullable - see
                # that module's docstring for when it is legitimately unset.
                "due_at",
            },
        )


if __name__ == "__main__":
    unittest.main()
