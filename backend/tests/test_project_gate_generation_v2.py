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
from app.template_models import V2Template, V2TemplateExternalGate, V2TemplateExternalGateTask, V2TemplateTask, V2TemplateVersion

@compiles(JSONB, "sqlite")
def jsonb_sqlite(_type, _compiler, **_kw): return "JSON"

ADMIN_ID=uuid.UUID('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1')
PM_ID=uuid.UUID('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2')
PM_EMP=uuid.UUID('cccccccc-cccc-4ccc-8ccc-ccccccccccc3')

class GateGenerationTests(unittest.TestCase):
  def setUp(self):
    self.engine=create_engine('sqlite+pysqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool)
    @event.listens_for(self.engine,'connect')
    def attach(conn,_):
      conn.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
      conn.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)
    tables=[User.__table__,EmployeeProfile.__table__,V2Template.__table__,V2TemplateVersion.__table__,V2TemplateTask.__table__,V2TemplateExternalGate.__table__,V2TemplateExternalGateTask.__table__,V2Project.__table__,V2ProjectTask.__table__,V2ProjectMembership.__table__,V2ProjectExternalGate.__table__,V2ProjectExternalGateTask.__table__,V2AuditEvent.__table__]
    for t in tables: t.create(self.engine)
    self.Session=sessionmaker(bind=self.engine,expire_on_commit=False); self._seed()
    app=FastAPI(); app.include_router(router)
    def db_override():
      with self.Session() as s: yield s
    app.dependency_overrides[get_db]=db_override
    app.dependency_overrides[current_user]=lambda: User(id=ADMIN_ID,name='Admin',email='admin@test',role=UserRole.admin,active=True)
    self.client=TestClient(app)
  def tearDown(self): self.client.close(); self.engine.dispose()
  def _seed(self):
    with self.Session.begin() as s:
      s.add_all([User(id=ADMIN_ID,name='Admin',email='admin@test',role=UserRole.admin,active=True),User(id=PM_ID,name='PM Owner',email='pm@test',role=UserRole.project_manager,active=True)])
      s.add(EmployeeProfile(id=PM_EMP,user_id=PM_ID,employee_code='PM1',designation='PM',availability='available'))
      template=V2Template(code='W45',name='Workved'); s.add(template); s.flush()
      ver=V2TemplateVersion(template_id=template.id,version_no=1,status='published',duration_days=45,content_hash='x',is_current_published=True,created_by=ADMIN_ID,published_by=ADMIN_ID,published_at=datetime.now(timezone.utc)); s.add(ver); s.flush()
      tasks=[]
      for i in range(1,100):
        t=V2TemplateTask(template_version_id=ver.id,code=f'T{i:03d}',sequence_no=i,title=f'Task {i}',schedule_classification='pre_activation' if i<=7 else 'execution',planned_start_day=None if i<=7 else min(i-7,45),planned_end_day=None if i<=7 else min(i-7,45),phase='P',category='C',applicability='mandatory',evidence_required=False)
        s.add(t); tasks.append(t)
      s.flush()
      gates=[]
      for i in range(1,33):
        kind='exact' if i<=10 else ('broad_text' if i<=20 else 'unmapped')
        g=V2TemplateExternalGate(template_version_id=ver.id,code=f'E{i:03d}',approval_name=f'Gate {i}',description='desc',external_party='Client',required_by_type='before_task',required_by_value='T001',impact='impact',mapping_classification=kind,broad_mapping_text=f'Broad scope {i}' if kind=='broad_text' else None,requires_configuration=kind!='exact',sequence_no=i)
        s.add(g); gates.append(g)
      s.flush()
      for i,g in enumerate(gates[:10]): s.add(V2TemplateExternalGateTask(gate_id=g.id,template_task_id=tasks[i].id))
      project=V2Project(code='PRJ1',name='P',client_name='C',site_address='Mumbai',start_date=date(2026,8,1),template_version_id=ver.id,status='draft',created_by=ADMIN_ID); s.add(project); s.flush()
      s.add(V2ProjectMembership(project_id=project.id,employee_id=PM_EMP,project_role='project_manager',assigned_by=ADMIN_ID,assignment_reason='owner'))
      s.add_all([V2ProjectTask(project_id=project.id,template_version_id=ver.id,template_task_id=t.id,original_code=t.code,template_sequence=t.sequence_no,title=t.title,schedule_classification=t.schedule_classification,planned_start_day=t.planned_start_day,planned_end_day=t.planned_end_day,phase=t.phase,category=t.category,applicability=t.applicability,source_type='template',lifecycle_status='draft',included=True,decision_state='pending_review') for t in tasks])
      self.project_id=project.id; self.template_id=template.id
  def post(self): return self.client.post(f'/api/v2/projects/{self.project_id}/generate-gates')
  def test_expected_count_source_pm_and_mapping_semantics(self):
    r=self.post(); self.assertEqual(r.status_code,200,r.text); self.assertEqual(r.json()['generated_gate_count'],32); self.assertEqual(r.json()['exact_mapping_count'],10)
    with self.Session() as s:
      rows=list(s.scalars(select(V2ProjectExternalGate).order_by(V2ProjectExternalGate.template_sequence)))
      self.assertEqual(len(rows),32); self.assertTrue(all(x.status=='pending_review' and x.accountable_pm_user_id==PM_ID and x.template_gate_id for x in rows))
      self.assertEqual(rows[10].mapping_classification,'broad_text'); self.assertEqual(rows[10].broad_mapping_text,'Broad scope 11')
      self.assertEqual(s.scalar(select(func.count()).select_from(V2ProjectExternalGateTask)),10)
      links=list(s.scalars(select(V2ProjectExternalGateTask)))
      project_task_ids=set(s.scalars(select(V2ProjectTask.id)))
      self.assertTrue(all(x.project_task_id in project_task_ids for x in links))
      self.assertEqual(s.get(V2Project,self.project_id).status,'draft')
  def test_retry_no_duplicates_and_single_audit(self):
    self.assertEqual(self.post().status_code,200); r=self.post(); self.assertTrue(r.json()['no_op'])
    with self.Session() as s:
      self.assertEqual(s.scalar(select(func.count()).select_from(V2ProjectExternalGate)),32)
      self.assertEqual(s.scalar(select(func.count()).select_from(V2AuditEvent).where(V2AuditEvent.action=='PROJECT_GATES_GENERATED')),1)

  def test_retry_rejects_partial_exact_mapping_snapshot(self):
    self.assertEqual(self.post().status_code,200)
    with self.Session.begin() as s:
      link=s.scalar(select(V2ProjectExternalGateTask))
      s.delete(link)
    response=self.post()
    self.assertEqual(response.status_code,409,response.text)
    self.assertIn('exact task mappings',response.json()['detail'])

  def test_active_project_rejected(self):
    with self.Session.begin() as s: s.get(V2Project,self.project_id).status='active'
    self.assertEqual(self.post().status_code,409)
  def test_missing_pm_rejected(self):
    with self.Session.begin() as s: s.query(V2ProjectMembership).delete()
    self.assertEqual(self.post().status_code,422)
  def test_rollback(self):
    def broken(session): raise RuntimeError('commit failed')
    # Patch Session class method used by request sessions.
    cls=type(self.Session())
    orig=cls.commit; cls.commit=lambda _s: (_ for _ in ()).throw(RuntimeError('commit failed'))
    try:
      with self.assertRaises(RuntimeError): self.post()
    finally: cls.commit=orig
    with self.Session() as s:
      self.assertEqual(s.scalar(select(func.count()).select_from(V2ProjectExternalGate)),0)
      self.assertEqual(s.scalar(select(func.count()).select_from(V2AuditEvent).where(V2AuditEvent.action=='PROJECT_GATES_GENERATED')),0)

if __name__=='__main__': unittest.main()
