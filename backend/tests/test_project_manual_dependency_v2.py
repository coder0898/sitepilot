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
from app.project_models import V2Project, V2ProjectTask, V2ProjectTaskDependency
from app.routes.dependencies_v2 import router
from app.template_models import V2Template, V2TemplateVersion

@compiles(JSONB, "sqlite")
def jsonb_sqlite(_type, _compiler, **_kw): return "JSON"

ADMIN=uuid.uuid4()

class ManualDependencyAuthorityTests(unittest.TestCase):
    """Adding a manual dependency is an org-admin call: Admin or Super Admin."""
    def setUp(self):
        self.engine=create_engine('sqlite+pysqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool)
        @event.listens_for(self.engine,'connect')
        def attach(conn,_):
            conn.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            conn.create_function('btrim',1,lambda v:v.strip() if v is not None else None)
        tables=[User.__table__,V2Template.__table__,V2TemplateVersion.__table__,V2Project.__table__,V2ProjectTask.__table__,V2ProjectTaskDependency.__table__]
        for t in tables: t.create(self.engine)
        self.Session=sessionmaker(bind=self.engine,expire_on_commit=False)
        self.actor=User(id=ADMIN,name='Admin',email='a@x',role=UserRole.admin,active=True)
        with self.Session.begin() as s:
            s.add(self.actor)
            tpl=V2Template(code='W45',name='Workved'); s.add(tpl); s.flush()
            ver=V2TemplateVersion(template_id=tpl.id,version_no=1,status='published',duration_days=45,content_hash='x',is_current_published=True,created_by=ADMIN,published_by=ADMIN,published_at=datetime.now(timezone.utc)); s.add(ver); s.flush()
            pr=V2Project(code='P1',name='P',client_name='C',site_address='M',start_date=date(2026,8,1),template_version_id=ver.id,status='draft',created_by=ADMIN); s.add(pr); s.flush()
            tasks=[V2ProjectTask(project_id=pr.id,template_version_id=ver.id,template_task_id=None,original_code=f'MANUAL-00{n}',template_sequence=n,title=f'Task {n}',schedule_classification='execution',planned_start_day=n,planned_end_day=n,phase='P',category='C',applicability='mandatory',source_type='project_manual',lifecycle_status='draft',included=True,decision_state='included') for n in (1,2)]
            s.add_all(tasks); s.flush()
            self.project_id=pr.id; self.first_id=tasks[0].id; self.second_id=tasks[1].id
        app=FastAPI(); app.include_router(router)
        def db_override():
            with self.Session() as s: yield s
        app.dependency_overrides[get_db]=db_override; app.dependency_overrides[current_user]=lambda:self.actor
        self.client=TestClient(app)
    def tearDown(self): self.client.close(); self.engine.dispose()
    def add(self):
        return self.client.post(f'/api/v2/projects/{self.project_id}/dependencies',json={'predecessor_project_task_id':str(self.first_id),'successor_project_task_id':str(self.second_id),'dependency_type':'finish_to_start','reason':'Site sequencing'})
    def count(self):
        with self.Session() as s: return s.scalar(select(func.count()).select_from(V2ProjectTaskDependency))
    def test_super_admin_can_add_a_manual_dependency(self):
        self.actor=User(id=uuid.uuid4(),name='Super Admin',email='sa@x',role=UserRole.super_admin,active=True)
        r=self.add(); self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.count(),1)
    def test_other_roles_cannot_add_a_manual_dependency(self):
        for role in (UserRole.project_manager,UserRole.supervisor,UserRole.internal_employee):
            with self.subTest(role=role):
                self.actor=User(id=uuid.uuid4(),name=role.value,email=f'{role.value}@x',role=role,active=True)
                r=self.add(); self.assertEqual(r.status_code,403,r.text)
                self.assertIn('Only Admin',r.json()['detail'])
        self.assertEqual(self.count(),0)

if __name__=='__main__': unittest.main()
