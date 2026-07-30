
import uuid
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.database import get_db
from app.models import User, UserRole
from app.project_models import V2Project, V2ProjectTask, V2ProjectTaskDependency

router = APIRouter(prefix="/api/v2/projects", tags=["v2-project-dependencies"])

class ManualDependencyIn(BaseModel):
    predecessor_project_task_id: uuid.UUID
    successor_project_task_id: uuid.UUID
    dependency_type: str = Field(pattern="^(finish_to_start|start_to_start)$")
    rule_text: str | None = None
    reason: str

def assert_project(db, project_id):
    project = db.get(V2Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found.")
    return project

def can_edit(user):
    return user.role in {UserRole.super_admin, UserRole.admin, UserRole.project_manager}

def ensure_acyclic(db, project_id, start, end):
    seen=set()
    stack=[end]
    while stack:
        node=stack.pop()
        if node == start:
            return False
        if node in seen: continue
        seen.add(node)
        stack.extend(db.scalars(select(V2ProjectTaskDependency.successor_project_task_id).where(
            V2ProjectTaskDependency.project_id==project_id,
            V2ProjectTaskDependency.predecessor_project_task_id==node
        )).all())
    return True

@router.get("/{project_id}/dependencies")
def review_dependencies(project_id: uuid.UUID, db: Session=Depends(get_db), user: User=Depends(current_user),
                        phase: str|None=None, search: str|None=None,
                        source: str|None=None, validation: str|None=None,
                        page:int=1, page_size:int=50):
    assert_project(db, project_id)
    stmt=select(V2ProjectTaskDependency).where(V2ProjectTaskDependency.project_id==project_id)
    if source:
        stmt=stmt.where(V2ProjectTaskDependency.source_type==source)
    rows=list(db.scalars(stmt.order_by(V2ProjectTaskDependency.template_sequence)).all())
    task_ids={x for d in rows for x in (d.predecessor_project_task_id,d.successor_project_task_id)}
    task_map={t.id:t for t in db.scalars(select(V2ProjectTask).where(V2ProjectTask.id.in_(task_ids))).all()}
    items=[]
    for d in rows:
        pre=task_map[d.predecessor_project_task_id]
        suc=task_map[d.successor_project_task_id]
        if search and search.lower() not in ((pre.original_code+" "+suc.original_code).lower()):
            continue
        items.append({
            "id":str(d.id),"predecessor":str(d.predecessor_project_task_id),
            "successor":str(d.successor_project_task_id),
            "predecessor_code":pre.original_code,"successor_code":suc.original_code,
            "type":d.dependency_type,"rule":d.rule_text,
            "source":d.source_type,"validation":"excluded_task_warning" if d.excluded_task_warning else "valid",
            "excluded_flag":d.excluded_task_warning,"reason":d.reason
        })
    return {"total":len(items),"items":items[(page-1)*page_size:page*page_size]}

@router.post("/{project_id}/dependencies")
def create_manual_dependency(project_id:uuid.UUID, payload:ManualDependencyIn, db:Session=Depends(get_db), user:User=Depends(current_user)):
    assert_project(db, project_id)
    if not can_edit(user): raise HTTPException(403,"Not allowed.")
    if payload.predecessor_project_task_id == payload.successor_project_task_id:
        raise HTTPException(422,"Self dependency not allowed.")
    tasks=list(db.scalars(select(V2ProjectTask).where(V2ProjectTask.id.in_([payload.predecessor_project_task_id,payload.successor_project_task_id]))).all())
    if len(tasks)!=2 or any(t.project_id!=project_id or not t.included for t in tasks):
        raise HTTPException(422,"Both tasks must be included tasks in the same project.")
    if not ensure_acyclic(db, project_id, payload.predecessor_project_task_id, payload.successor_project_task_id):
        raise HTTPException(422,"Dependency cycle detected.")
    duplicate=db.scalar(select(V2ProjectTaskDependency).where(
        V2ProjectTaskDependency.project_id==project_id,
        V2ProjectTaskDependency.predecessor_project_task_id==payload.predecessor_project_task_id,
        V2ProjectTaskDependency.successor_project_task_id==payload.successor_project_task_id,
        V2ProjectTaskDependency.dependency_type==payload.dependency_type))
    if duplicate: raise HTTPException(409,"Duplicate dependency.")
    row=V2ProjectTaskDependency(project_id=project_id, predecessor_project_task_id=payload.predecessor_project_task_id,
        successor_project_task_id=payload.successor_project_task_id, dependency_type=payload.dependency_type,
        rule_text=payload.rule_text, source_type="project_manual", reason=payload.reason,
        template_sequence=999999, lifecycle_status="draft", blocking=True, excluded_task_warning=False)
    db.add(row); db.commit(); db.refresh(row)
    return {"id":str(row.id),"source":"project_manual"}
