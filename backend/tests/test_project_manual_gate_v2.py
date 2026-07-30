from __future__ import annotations
import unittest, uuid
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
from app.project_models import V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectExternalGateTask, V2ProjectMembership, V2ProjectTask
from app.routes.projects_v2 import router
from app.template_models import V2Template, V2TemplateTask, V2TemplateVersion, V2TemplateExternalGate

@compiles(JSONB, "sqlite")
def jsonb_sqlite(_type, _compiler, **_kw): return "JSON"

ADMIN=uuid.uuid4(); PM=uuid.uuid4(); PM_EMP=uuid.uuid4()

class ManualGateTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite+pysqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool)
        @event.listens_for(self.engine,'connect')
        def attach(conn,_):
            conn.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            conn.create_function('btrim',1,lambda v:v.strip() if v is not None else None)
        tables=[User.__table__,EmployeeProfile.__table__,V2Template.__table__,V2TemplateVersion.__table__,V2TemplateTask.__table__,V2TemplateExternalGate.__table__,V2Project.__table__,V2ProjectMembership.__table__,V2ProjectTask.__table__,V2ProjectExternalGate.__table__,V2ProjectExternalGateTask.__table__,V2AuditEvent.__table__]
        for t in tables: t.create(self.engine)
        self.Session=sessionmaker(bind=self.engine,expire_on_commit=False)
        self.actor=User(id=ADMIN,name='Admin',email='a@x',role=UserRole.admin,active=True)
        with self.Session.begin() as s:
            s.add_all([self.actor,User(id=PM,name='PM',email='p@x',role=UserRole.project_manager,active=True)])
            s.add(EmployeeProfile(id=PM_EMP,user_id=PM,employee_code='PM1',designation='PM',availability='available'))
            tpl=V2Template(code='W45',name='Workved'); s.add(tpl); s.flush()
            ver=V2TemplateVersion(template_id=tpl.id,version_no=1,status='published',duration_days=45,content_hash='x',is_current_published=True,created_by=ADMIN,published_by=ADMIN,published_at=datetime.now(timezone.utc)); s.add(ver); s.flush()
            tt=V2TemplateTask(template_version_id=ver.id,code='T001',sequence_no=1,title='Task',schedule_classification='execution',planned_start_day=1,planned_end_day=1,phase='P',category='C',applicability='mandatory',evidence_required=False); s.add(tt); s.flush()
            pr=V2Project(code='P1',name='P',client_name='C',site_address='M',start_date=date(2026,8,1),template_version_id=ver.id,status='draft',created_by=ADMIN); s.add(pr); s.flush()
            s.add(V2ProjectMembership(project_id=pr.id,employee_id=PM_EMP,project_role='project_manager',assigned_by=ADMIN,assignment_reason='owner'))
            task=V2ProjectTask(project_id=pr.id,template_version_id=ver.id,template_task_id=tt.id,original_code='T001',template_sequence=1,title='Task',schedule_classification='execution',planned_start_day=1,planned_end_day=1,phase='P',category='C',applicability='mandatory',source_type='template',lifecycle_status='draft',included=True,decision_state='included'); s.add(task); s.flush()
            other=V2Project(code='P2',name='Other',client_name='C',site_address='M',start_date=date(2026,8,1),template_version_id=ver.id,status='draft',created_by=ADMIN); s.add(other); s.flush()
            other_task=V2ProjectTask(project_id=other.id,template_version_id=ver.id,template_task_id=None,original_code='MANUAL-001',template_sequence=1,title='Other',schedule_classification='execution',planned_start_day=1,planned_end_day=1,phase='P',category='C',applicability='mandatory',source_type='project_manual',lifecycle_status='draft',included=True,decision_state='included'); s.add(other_task); s.flush()
            self.project_id=pr.id; self.task_id=task.id; self.other_task_id=other_task.id; self.template_id=tpl.id
        app=FastAPI(); app.include_router(router)
        def db_override():
            with self.Session() as s: yield s
        app.dependency_overrides[get_db]=db_override; app.dependency_overrides[current_user]=lambda:self.actor
        self.client=TestClient(app)
    def tearDown(self): self.client.close(); self.engine.dispose()
    def payload(self, tasks=None, blocking=True):
        return {'title':'Landlord approval','external_party':'Landlord','required_by_type':'project_day','required_by_day':5,'affected_project_task_ids':tasks if tasks is not None else [str(self.task_id)],'blocking':blocking,'impact':'Blocks execution','reason':'Project-specific approval'}
    def test_create_pm_owner_mapping_and_template_unchanged(self):
        r=self.client.post(f'/api/v2/projects/{self.project_id}/gates',json=self.payload()); self.assertEqual(r.status_code,201,r.text)
        with self.Session() as s:
            gate=s.scalar(select(V2ProjectExternalGate)); self.assertEqual(gate.source_type,'project_manual'); self.assertEqual(gate.accountable_pm_user_id,PM); self.assertIsNone(gate.template_gate_id)
            self.assertEqual(s.scalar(select(func.count()).select_from(V2ProjectExternalGateTask)),1)
            self.assertEqual(s.scalar(select(func.count()).select_from(V2TemplateExternalGate)),0)
            self.assertEqual(s.scalar(select(V2AuditEvent.reason)),'Project-specific approval')
    def test_blocking_without_task_rejected(self):
        r=self.client.post(f'/api/v2/projects/{self.project_id}/gates',json=self.payload([],True)); self.assertEqual(r.status_code,422)
    def test_cross_project_task_rejected(self):
        r=self.client.post(f'/api/v2/projects/{self.project_id}/gates',json=self.payload([str(self.other_task_id)])); self.assertEqual(r.status_code,422)
    def test_active_project_rejected(self):
        with self.Session.begin() as s: s.get(V2Project,self.project_id).status='active'
        self.assertEqual(self.client.post(f'/api/v2/projects/{self.project_id}/gates',json=self.payload()).status_code,409)

if __name__=='__main__': unittest.main()
