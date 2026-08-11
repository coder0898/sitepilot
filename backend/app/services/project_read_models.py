"""Bulk read models for the Projects split view.

Deliberately built on top of `ProjectVisibilityService.summarize` rather
than beside it: U1's docstring states that no parallel aggregation logic
exists elsewhere, and a second definition of "blocked" or "overdue" is
exactly the drift that promise exists to prevent. The cost is one
summarize() per visible project, the same N-call shape
`admin_visibility_v2.projects_overview` already accepts at Release 1
scale. Two things summarize() does not compute - the per-phase rollup and
the project's last audit timestamp - are added here as set-based queries
over every visible project at once.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.execution_models import Task
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership
from app.schemas.project_read_models import AttentionItemOut, PhaseProgressOut, ProjectSummaryOut
from app.services.project_visibility import ProjectVisibilityService

UNPHASED_LABEL = "Unphased"


def _pct(part: int, whole: int) -> int:
    return round(part / whole * 100) if whole else 0


def _aware(value: datetime | None) -> datetime | None:
    """SQLite drops tzinfo on read where Postgres does not - mirrors
    ProjectVisibilityService._aware so due-date maths cannot raise on the
    test harness."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _due_label(due_at: datetime | None, now: datetime) -> str | None:
    due = _aware(due_at)
    if due is None:
        return None
    hours = (due - now).total_seconds() / 3600
    if hours < -24:
        return f"{int(abs(hours) // 24)}d over"
    if hours < 0:
        return "overdue"
    if hours < 24:
        return "due today"
    return f"due {int(hours // 24)}d"


class ProjectReadModelService:
    def __init__(self, db: Session):
        self.db = db

    # ---- scoping ---------------------------------------------------------

    def visible_projects(self, actor: User) -> list[V2Project]:
        """Same access model as `projects_v2.list_projects`: Admin and Super
        Admin see everything, everyone else sees only projects they hold an
        active membership on. Archived projects are excluded - they are
        closed business and would otherwise pad every rollup forever."""
        statement = select(V2Project).where(V2Project.status != "archived").order_by(V2Project.updated_at.desc())
        if actor.role not in {UserRole.super_admin, UserRole.admin}:
            employee_id = self.db.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == actor.id))
            if not employee_id:
                return []
            visible_ids = select(V2ProjectMembership.project_id).where(
                V2ProjectMembership.employee_id == employee_id,
                V2ProjectMembership.ends_at.is_(None),
            )
            statement = statement.where(V2Project.id.in_(visible_ids))
        return list(self.db.scalars(statement).all())

    # ---- pieces summarize() does not cover -------------------------------

    def _phases_by_project(self, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[PhaseProgressOut]]:
        if not project_ids:
            return {}
        # Ordered by the phase's earliest template sequence so phases come
        # back in schedule order (Planning, Civil, MEP, ...) rather than
        # alphabetically, which would be meaningless to read.
        rows = self.db.execute(
            select(
                Task.project_id,
                Task.phase,
                func.count(Task.id),
                func.sum(case((Task.lifecycle_status == "completed", 1), else_=0)),
                func.min(Task.template_sequence),
            )
            .where(Task.project_id.in_(project_ids))
            .group_by(Task.project_id, Task.phase)
            .order_by(Task.project_id, func.min(Task.template_sequence))
        ).all()

        phases: dict[uuid.UUID, list[PhaseProgressOut]] = {}
        for project_id, phase, total, completed, _sequence in rows:
            completed = int(completed or 0)
            phases.setdefault(project_id, []).append(
                PhaseProgressOut(
                    phase=phase or UNPHASED_LABEL,
                    total=int(total),
                    completed=completed,
                    pct=_pct(completed, int(total)),
                )
            )
        return phases

    def _last_activity_by_project(self, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime]:
        if not project_ids:
            return {}
        rows = self.db.execute(
            select(V2AuditEvent.project_id, func.max(V2AuditEvent.occurred_at))
            .where(V2AuditEvent.project_id.in_(project_ids))
            .group_by(V2AuditEvent.project_id)
        ).all()
        return {project_id: occurred_at for project_id, occurred_at in rows if project_id is not None}

    # ---- public read models ---------------------------------------------

    def summaries(self, actor: User) -> list[ProjectSummaryOut]:
        projects = self.visible_projects(actor)
        project_ids = [project.id for project in projects]
        phases = self._phases_by_project(project_ids)
        last_activity = self._last_activity_by_project(project_ids)
        visibility = ProjectVisibilityService(self.db)

        results = []
        for project in projects:
            summary = visibility.summarize(project.id, actor)
            results.append(ProjectSummaryOut(
                project_id=project.id,
                progress_pct=_pct(summary.completed_count, summary.total_count),
                total_count=summary.total_count,
                completed_count=summary.completed_count,
                blocked_count=len(summary.blocked_tasks),
                delayed_count=len(summary.delayed_tasks),
                overdue_count=len(summary.overdue_tasks),
                no_update_count=len(summary.no_update_tasks),
                pending_approvals=len(summary.pending_approvals),
                pending_verifications=len(summary.pending_verifications),
                last_activity_at=last_activity.get(project.id),
                phases=phases.get(project.id, []),
            ))
        return results

    def attention(self, actor: User) -> list[AttentionItemOut]:
        """One flat, already-prioritised feed across every visible project.

        Ordering is severity-first so the client never has to re-rank:
        critical (something is already late), then decisions waiting on this
        actor, then setup that will block a future activation.
        """
        now = datetime.now(timezone.utc)
        visibility = ProjectVisibilityService(self.db)
        items: list[AttentionItemOut] = []

        for project in self.visible_projects(actor):
            label = project.name

            if project.status == "draft":
                # A draft cannot activate without a locked baseline, and the
                # baseline needs at least one included task - the four-item
                # setup checklist does not cover this, so surface it here.
                task_count = self.db.scalar(
                    select(func.count(Task.id)).where(Task.project_id == project.id)
                ) or 0
                if task_count == 0:
                    items.append(AttentionItemOut(
                        id=f"{project.id}:setup-tasks", group="Setup incomplete", severity="warning",
                        title="Tasks not generated", subtitle=f"{label} · cannot activate",
                        project_id=project.id, project_code=project.code, pane="overview",
                    ))
                if not project.target_handover_date:
                    items.append(AttentionItemOut(
                        id=f"{project.id}:setup-handover", group="Setup incomplete", severity="warning",
                        title="Target handover date missing", subtitle=f"{label} · required to activate",
                        project_id=project.id, project_code=project.code, pane="overview",
                    ))
                continue

            summary = visibility.summarize(project.id, actor)

            if summary.overdue_tasks:
                items.append(AttentionItemOut(
                    id=f"{project.id}:overdue", group="Running late", severity="critical",
                    title=f"{len(summary.overdue_tasks)} task{'s' if len(summary.overdue_tasks) != 1 else ''} overdue",
                    subtitle=label, project_id=project.id, project_code=project.code, pane="dashboard",
                ))
            if summary.blocked_tasks:
                items.append(AttentionItemOut(
                    id=f"{project.id}:blocked", group="Running late", severity="critical",
                    title=f"{len(summary.blocked_tasks)} task{'s' if len(summary.blocked_tasks) != 1 else ''} blocked",
                    subtitle=label, project_id=project.id, project_code=project.code, pane="dashboard",
                ))
            if summary.delayed_tasks:
                items.append(AttentionItemOut(
                    id=f"{project.id}:delayed", group="Running late", severity="warning",
                    title=f"{len(summary.delayed_tasks)} task{'s' if len(summary.delayed_tasks) != 1 else ''} delayed",
                    subtitle=label, project_id=project.id, project_code=project.code, pane="dashboard",
                ))

            for gate in summary.approval_gates_at_risk:
                items.append(AttentionItemOut(
                    id=f"{gate.id}:gate", group="Needs a decision", severity="decision",
                    title=gate.title, subtitle=f"{label} · approval gate",
                    project_id=project.id, project_code=project.code, pane="external-gates",
                    due_label=_due_label(gate.due_at, now),
                ))
            if summary.pending_approvals:
                items.append(AttentionItemOut(
                    id=f"{project.id}:approvals", group="Needs a decision", severity="decision",
                    title=f"{len(summary.pending_approvals)} task{'s' if len(summary.pending_approvals) != 1 else ''} awaiting approval",
                    subtitle=label, project_id=project.id, project_code=project.code, pane="dashboard",
                ))
            if summary.pending_verifications:
                items.append(AttentionItemOut(
                    id=f"{project.id}:verifications", group="Needs a decision", severity="decision",
                    title=f"{len(summary.pending_verifications)} task{'s' if len(summary.pending_verifications) != 1 else ''} awaiting verification",
                    subtitle=label, project_id=project.id, project_code=project.code, pane="dashboard",
                ))

        severity_rank = {"critical": 0, "decision": 1, "warning": 2}
        items.sort(key=lambda item: (severity_rank[item.severity], item.subtitle, item.title))
        return items
