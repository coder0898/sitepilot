"""U1: the external-gate status column holds the full approval lifecycle.

Two of these tests - the D1 and D3 regressions - are green *before* the
fix as well as after, and that is the point. The harness builds its tables
from ORM metadata, and the ORM never carried the strict auto-named
constraints that break those inserts in Postgres. They are kept because
they are the assertions to run against a real database, and marked so that
nobody reads a green run here as confirmation the production defect is
closed. See the header of
supabase/migrations/202608120001_v2_project_external_gate_status.sql.
"""
from __future__ import annotations
import unittest, uuid
from datetime import date, datetime, timezone
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import EmployeeProfile, User, UserRole
from app.project_models import (
    V2Project,
    V2ProjectExternalGate,
    V2ProjectExternalGateTask,
    V2ProjectTask,
    V2ProjectTaskDependency,
)
from app.template_models import V2Template, V2TemplateTask, V2TemplateVersion, V2TemplateExternalGate

@compiles(JSONB, "sqlite")
def jsonb_sqlite(_type, _compiler, **_kw): return "JSON"

ADMIN = uuid.uuid4(); PM = uuid.uuid4(); PM_EMP = uuid.uuid4()

# KTD3: the five values that are actually persisted. 'pending' is the API
# and UI spelling of 'pending_review' and is never stored.
PERSISTED_STATUSES = ('not_required', 'pending_review', 'submitted', 'approved', 'rejected')

class GateStatusSchemaTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        @event.listens_for(self.engine, 'connect')
        def attach(conn, _):
            conn.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            conn.create_function('btrim', 1, lambda v: v.strip() if v is not None else None)
        tables = [User.__table__, EmployeeProfile.__table__, V2Template.__table__, V2TemplateVersion.__table__,
                  V2TemplateTask.__table__, V2TemplateExternalGate.__table__, V2Project.__table__, V2ProjectTask.__table__,
                  V2ProjectExternalGate.__table__, V2ProjectExternalGateTask.__table__, V2ProjectTaskDependency.__table__]
        for t in tables: t.create(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Session.begin() as s:
            s.add_all([User(id=ADMIN, name='Admin', email='a@x', role=UserRole.admin, active=True),
                       User(id=PM, name='PM', email='p@x', role=UserRole.project_manager, active=True)])
            s.add(EmployeeProfile(id=PM_EMP, user_id=PM, employee_code='PM1', designation='PM', availability='available'))
            tpl = V2Template(code='W45', name='Workved'); s.add(tpl); s.flush()
            ver = V2TemplateVersion(template_id=tpl.id, version_no=1, status='published', duration_days=45, content_hash='x',
                                    is_current_published=True, created_by=ADMIN, published_by=ADMIN,
                                    published_at=datetime.now(timezone.utc)); s.add(ver); s.flush()
            gate_tpl = V2TemplateExternalGate(template_version_id=ver.id, code='E001', sequence_no=1, approval_name='Landlord',
                                              mapping_classification='exact'); s.add(gate_tpl); s.flush()
            pr = V2Project(code='P1', name='P', client_name='C', site_address='M', start_date=date(2026, 8, 1),
                           template_version_id=ver.id, status='draft', created_by=ADMIN); s.add(pr); s.flush()
            self.project_id = pr.id; self.version_id = ver.id; self.template_gate_id = gate_tpl.id
            self.task_ids = []
            for n in (1, 2):
                tt = V2TemplateTask(template_version_id=ver.id, code=f'T00{n}', sequence_no=n, schedule_classification='execution',
                                    title=f'Task {n}', planned_start_day=n, planned_end_day=n, phase='P', category='C',
                                    applicability='mandatory', evidence_required=False); s.add(tt); s.flush()
                pt = V2ProjectTask(project_id=pr.id, template_version_id=ver.id, template_task_id=tt.id, original_code=f'T00{n}',
                                   template_sequence=n, title=f'Task {n}', schedule_classification='execution', planned_start_day=n,
                                   planned_end_day=n, phase='P', category='C', applicability='mandatory', source_type='template',
                                   lifecycle_status='draft', included=True, decision_state='included'); s.add(pt); s.flush()
                self.task_ids.append(pt.id)

    def tearDown(self): self.engine.dispose()

    def gate(self, **overrides):
        fields = dict(project_id=self.project_id, template_version_id=self.version_id, template_gate_id=self.template_gate_id,
                      original_code='E001', template_sequence=1, approval_name='Landlord', mapping_classification='exact',
                      accountable_pm_user_id=PM)
        fields.update(overrides)
        return V2ProjectExternalGate(**fields)

    def test_every_persisted_lifecycle_value_is_accepted(self):
        for index, status in enumerate(PERSISTED_STATUSES):
            with self.subTest(status=status):
                with self.Session.begin() as s:
                    s.add(self.gate(original_code=f'E{index:03d}', template_gate_id=None, template_version_id=None,
                                    source_type='project_manual', status=status))
                with self.Session() as s:
                    stored = s.scalar(select(V2ProjectExternalGate.status).where(V2ProjectExternalGate.original_code == f'E{index:03d}'))
                    self.assertEqual(stored, status)

    def test_a_value_outside_the_five_is_rejected(self):
        # 'pending' is the API spelling, deliberately not a stored value -
        # persisting it would give the column two names for one state.
        for status in ('pending', 'in_review', 'PENDING_REVIEW', ''):
            with self.subTest(status=status):
                with self.assertRaises(IntegrityError):
                    with self.Session.begin() as s:
                        s.add(self.gate(original_code=f'X-{status or "empty"}', template_gate_id=None, template_version_id=None,
                                        source_type='project_manual', status=status))

    def test_an_existing_row_is_untouched_and_has_no_recorder(self):
        """The column default is unchanged, so a gate created before this
        unit reads back exactly as it did and carries no recorder."""
        with self.Session.begin() as s:
            s.add(self.gate())
        with self.Session() as s:
            gate = s.scalar(select(V2ProjectExternalGate))
            self.assertEqual(gate.status, 'pending_review')
            self.assertIsNone(gate.status_recorded_by_user_id)
            self.assertIsNone(gate.status_recorded_at)

    def test_the_recorder_columns_round_trip(self):
        recorded = datetime(2026, 8, 12, 9, 30, tzinfo=timezone.utc)
        with self.Session.begin() as s:
            s.add(self.gate(status='approved', status_recorded_by_user_id=PM, status_recorded_at=recorded))
        with self.Session() as s:
            gate = s.scalar(select(V2ProjectExternalGate))
            self.assertEqual(gate.status, 'approved')
            self.assertEqual(gate.status_recorded_by_user_id, PM)
            self.assertIsNotNone(gate.status_recorded_at)

    def test_d1_a_manual_gate_inserts(self):
        """POSTGRES-ONLY PROOF. Green here before and after the fix, because
        this harness never had project_external_gates_source_type_check.
        Run it against a real database or it proves nothing."""
        with self.Session.begin() as s:
            s.add(self.gate(source_type='project_manual', template_gate_id=None, template_version_id=None,
                            creation_reason='Project-specific approval'))
        with self.Session() as s:
            self.assertEqual(s.scalar(select(V2ProjectExternalGate.source_type)), 'project_manual')

    def test_d3_a_manual_dependency_inserts(self):
        """POSTGRES-ONLY PROOF. Same blind spot on a second table -
        project_task_dependencies_source_type_check."""
        with self.Session.begin() as s:
            s.add(V2ProjectTaskDependency(project_id=self.project_id, template_version_id=None, template_dependency_id=None,
                                          predecessor_project_task_id=self.task_ids[0], successor_project_task_id=self.task_ids[1],
                                          dependency_type='finish_to_start', template_sequence=1, source_type='project_manual',
                                          lifecycle_status='draft', reason='Site-specific sequencing'))
        with self.Session() as s:
            self.assertEqual(s.scalar(select(V2ProjectTaskDependency.source_type)), 'project_manual')

if __name__ == '__main__':
    unittest.main()
