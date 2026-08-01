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
from app.models import User, UserRole
from app.project_models import V2AuditEvent,V2Project,V2ProjectTask,V2ProjectTaskDependency
from app.routes.projects_v2 import router
from app.template_models import V2Template,V2TemplateVersion,V2TemplateTask,V2TemplateTaskDependency

@compiles(JSONB,'sqlite')
def jsonb_sqlite(_type,_compiler,**_kw): return 'JSON'
ADMIN=uuid.UUID('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1')

class DependencyGenerationTests(unittest.TestCase):
  def setUp(self):
    self.engine=create_engine('sqlite+pysqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool)
    @event.listens_for(self.engine,'connect')
    def attach(conn,_): conn.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
    for table in [User.__table__,V2Template.__table__,V2TemplateVersion.__table__,V2TemplateTask.__table__,V2TemplateTaskDependency.__table__,V2Project.__table__,V2ProjectTask.__table__,V2ProjectTaskDependency.__table__,V2AuditEvent.__table__]: table.create(self.engine)
    self.Session=sessionmaker(bind=self.engine,expire_on_commit=False); self._seed()
    app=FastAPI(); app.include_router(router)
    def db_override():
      with self.Session() as s: yield s
    app.dependency_overrides[get_db]=db_override
    app.dependency_overrides[current_user]=lambda: User(id=ADMIN,name='Admin',email='a@test',role=UserRole.admin,active=True)
    self.client=TestClient(app)
  def tearDown(self): self.client.close(); self.engine.dispose()
  def _seed(self):
    with self.Session.begin() as s:
      s.add(User(id=ADMIN,name='Admin',email='a@test',role=UserRole.admin,active=True))
      template=V2Template(code='W45',name='W'); s.add(template); s.flush()
      version=V2TemplateVersion(template_id=template.id,version_no=1,status='published',duration_days=45,content_hash='x',is_current_published=True,created_by=ADMIN,published_by=ADMIN,published_at=datetime.now(timezone.utc)); s.add(version); s.flush()
      tasks=[]
      for i in range(1,100):
        task=V2TemplateTask(template_version_id=version.id,code=f'T{i:03d}',sequence_no=i,title=f'Task {i}',schedule_classification='pre_activation' if i<=7 else 'execution',planned_start_day=None if i<=7 else min(i-7,45),planned_end_day=None if i<=7 else min(i-7,45),phase='P',category='C',applicability='conditional' if i==10 else 'mandatory',evidence_required=False)
        s.add(task); tasks.append(task)
      s.flush()
      for i in range(38): s.add(V2TemplateTaskDependency(template_version_id=version.id,predecessor_task_id=tasks[i].id,successor_task_id=tasks[i+1].id,dependency_type='finish_to_start' if i%2==0 else 'start_to_start',blocking=True,rule_text=f'Rule {i+1}',sequence_no=i+1))
      project=V2Project(code='P1',name='P',client_name='C',site_address='M',start_date=date(2026,8,1),template_version_id=version.id,status='draft',created_by=ADMIN); s.add(project); s.flush()
      rows=[]
      for task in tasks:
        included=task.code!='T010'
        rows.append(V2ProjectTask(project_id=project.id,template_version_id=version.id,template_task_id=task.id,original_code=task.code,template_sequence=task.sequence_no,title=task.title,schedule_classification=task.schedule_classification,planned_start_day=task.planned_start_day,planned_end_day=task.planned_end_day,phase='P',category='C',applicability=task.applicability,source_type='template',lifecycle_status='draft',included=included,decision_state='excluded' if not included else 'pending_review'))
      s.add_all(rows); self.project_id=project.id
  def post(self): return self.client.post(f'/api/v2/projects/{self.project_id}/generate-dependencies')
  def test_38_project_owned_dependencies_and_excluded_warning(self):
    r=self.post(); self.assertEqual(r.status_code,200,r.text); self.assertEqual(r.json()['generated_dependency_count'],38); self.assertGreaterEqual(r.json()['excluded_warning_count'],1)
    with self.Session() as s:
      deps=list(s.scalars(select(V2ProjectTaskDependency).order_by(V2ProjectTaskDependency.template_sequence)))
      task_ids=set(s.scalars(select(V2ProjectTask.id)))
      self.assertEqual(len(deps),38); self.assertTrue(all(d.predecessor_project_task_id in task_ids and d.successor_project_task_id in task_ids for d in deps)); self.assertTrue(any(d.excluded_task_warning for d in deps))
  def test_retry_is_noop_without_duplicates(self):
    self.assertEqual(self.post().status_code,200); r=self.post(); self.assertEqual(r.status_code,200); self.assertTrue(r.json()['no_op'])
    with self.Session() as s:
      self.assertEqual(s.scalar(select(func.count()).select_from(V2ProjectTaskDependency)),38)
      self.assertEqual(s.scalar(select(func.count()).select_from(V2AuditEvent).where(V2AuditEvent.action=='PROJECT_DEPENDENCIES_GENERATED')),1)
  def test_list_warning_tracks_current_task_inclusion_without_regeneration(self):
    self.assertEqual(self.post().status_code,200)
    with self.Session.begin() as s:
      task=s.scalar(select(V2ProjectTask).where(V2ProjectTask.original_code=='T001'))
      task.included=False; task.decision_state='excluded'
    response=self.client.get(f'/api/v2/projects/{self.project_id}/dependencies')
    self.assertEqual(response.status_code,200,response.text)
    self.assertTrue(response.json()['items'][0]['excluded_task_warning'])

  def test_active_project_rejected(self):
    with self.Session.begin() as s: s.get(V2Project,self.project_id).status='active'
    self.assertEqual(self.post().status_code,409)
  def test_partial_snapshot_rejected(self):
    self.assertEqual(self.post().status_code,200)
    with self.Session.begin() as s: s.delete(s.scalar(select(V2ProjectTaskDependency)))
    self.assertEqual(self.post().status_code,409)
  def test_rollback(self):
    cls=type(self.Session()); original=cls.commit; cls.commit=lambda _s: (_ for _ in ()).throw(RuntimeError('fail'))
    try:
      with self.assertRaises(RuntimeError): self.post()
    finally: cls.commit=original
    with self.Session() as s: self.assertEqual(s.scalar(select(func.count()).select_from(V2ProjectTaskDependency)),0)

if __name__=='__main__': unittest.main()
