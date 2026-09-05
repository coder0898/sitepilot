"""Plan: WhatsApp Gate Workflow (U8, KTD4/KTD5-KTD9).

`GateEvidenceSessionService` opens, appends to, and closes a
`GateEvidenceSession` - the WhatsApp-side buffer an employee fills with
`GATEOPEN <ref>`, one or more plain-text/attachment messages, and
`GATECLOSE`, before it is ever handed to
`ProjectGateSubmissionService.submit()` (the exact same service a portal
submission would call - KTD17).

Access mirrors `ProjectGateStatusCheckService`/`ProjectGateSubmissionService`
exactly: assignee-only, no Admin/PM fallback - the same framing R8 already
applies to a gate's submission.

Lifecycle (KTD4, KTD6-KTD10):

    NoSession --[GATEOPEN <ref>, approval.status == 'assigned' (KTD8)]--> Open
    Open --[GATECLOSE with nothing accumulated]--> Open (KTD9, session stays open)
    Open --[GATECLOSE with a note and/or attachments]--> NoSession (submit(), KTD17)
    Open --[no message for EVIDENCE_SESSION_SILENCE_DAYS (KTD5)]--> NoSession
        (session + attachments discarded, never submitted - KTD6)
    Open --[employee no longer the assignee at GATECLOSE time (KTD7)]--> Open
        (403, buffered evidence lost, session left open until it separately expires)

At most one open session (`closed_at is null and expired_at is null`) may
exist per employee at a time - enforced at the database level by
`gate_evidence_sessions`' own partial unique index
(`uq_v2_gate_evidence_sessions_employee_open`, see `execution_models.py`),
not just by `open_session`'s own proactive check.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.execution_models import (
    FileObject,
    GateEvidenceSession,
    GateEvidenceSessionAttachment,
    ProjectExternalApproval,
    ProjectExternalApprovalSubmission,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.services.project_gate_submission import ProjectGateSubmissionService

EVIDENCE_SESSION_SILENCE_DAYS = 5
"""KTD5: long enough to survive a weekend inside a multi-day approval wait,
short enough that a genuinely abandoned session does not block the
employee's one-open-session slot indefinitely."""


class GateEvidenceSessionService:
    def __init__(self, db: Session):
        self.db = db

    # ---- access -----------------------------------------------------------
    # Identical shape to ProjectGateSubmissionService/ProjectGateStatusCheckService.

    def _actor_project_roles(self, project_id: uuid.UUID, actor: User) -> set[str]:
        employee = self.db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == actor.id))
        if not employee:
            return set()
        rows = self.db.scalars(
            select(V2ProjectMembership.project_role).where(
                V2ProjectMembership.project_id == project_id,
                V2ProjectMembership.employee_id == employee.id,
                V2ProjectMembership.ends_at.is_(None),
            )
        )
        return set(rows)

    def _require_access(self, project_id: uuid.UUID, actor: User) -> V2Project:
        project = self.db.get(V2Project, project_id)
        if not project:
            raise HTTPException(404, "Project not found.")
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return project
        if self._actor_project_roles(project_id, actor):
            return project
        raise HTTPException(403, "You do not have access to this project.")

    def _get_approval(self, project_id: uuid.UUID, approval_id: uuid.UUID) -> ProjectExternalApproval:
        approval = self.db.scalar(
            select(ProjectExternalApproval).where(
                ProjectExternalApproval.id == approval_id,
                ProjectExternalApproval.project_id == project_id,
            )
        )
        if not approval:
            raise HTTPException(404, "External approval not found for this project.")
        return approval

    def _require_assignee(self, approval: ProjectExternalApproval, actor: User) -> None:
        """Assignee-exclusive - not even Admin/PM may open or close an
        evidence session on the assignee's behalf, matching
        `ProjectGateSubmissionService._require_submitter`'s framing
        literally. Re-run at `close_session` time (KTD7): a reassign in
        between naturally fails this the same way, with no new coupling
        needed between this service and `project_gate_assignment.py`."""
        if approval.assigned_to_user_id != actor.id:
            raise HTTPException(
                403,
                "Only the employee this external approval is assigned to can manage its evidence session.",
            )

    # ---- open ---------------------------------------------------------------

    def _has_open_session(self, employee_id: uuid.UUID) -> bool:
        return self.db.scalar(
            select(GateEvidenceSession.id).where(
                GateEvidenceSession.employee_id == employee_id,
                GateEvidenceSession.closed_at.is_(None),
                GateEvidenceSession.expired_at.is_(None),
            )
        ) is not None

    @staticmethod
    def _open_session_conflict() -> HTTPException:
        return HTTPException(
            409,
            "You already have an open evidence session for another gate. Send GATECLOSE to finish it before opening a new one.",
        )

    def open_session(self, project_id: uuid.UUID, approval_id: uuid.UUID, actor: User) -> GateEvidenceSession:
        project = self._require_access(project_id, actor)
        approval = self._get_approval(project.id, approval_id)
        self._require_assignee(approval, actor)

        if approval.status != "assigned":
            raise HTTPException(
                409,
                f"This external approval is {approval.status}; only an assigned gate can accept an evidence session.",
            )

        # Proactive check first (AE2) - a friendly rejection for the common
        # case without ever touching the database's own constraint. The
        # partial unique index below is the actual enforcement; this is
        # just a faster, clearer path to the same answer.
        if self._has_open_session(actor.id):
            raise self._open_session_conflict()

        session = GateEvidenceSession(approval_id=approval.id, employee_id=actor.id)
        self.db.add(session)
        try:
            self.db.commit()
        except IntegrityError:
            # Lost race: another open_session call for the same employee
            # committed between our proactive check and our own commit.
            # `uq_v2_gate_evidence_sessions_employee_open` raised - treated
            # as a benign rejection, mirroring
            # `EscalationTracking._commit_new_tracking`'s exact precedent
            # (escalation.py), never surfaced as an unhandled 500.
            self.db.rollback()
            raise self._open_session_conflict()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(session)
        return session

    # ---- append -------------------------------------------------------------
    # Both methods only add()/flush() - never commit. The caller (U10's
    # inbound message processing) owns the surrounding transaction, the same
    # discipline `OutboxService.emit` follows.

    def append_text(self, session: GateEvidenceSession, text: str) -> GateEvidenceSession:
        session.note = text if session.note is None else f"{session.note}\n{text}"
        session.last_activity_at = datetime.now(timezone.utc)
        self.db.add(session)
        self.db.flush()
        return session

    def append_attachment(self, session: GateEvidenceSession, file_object: FileObject) -> GateEvidenceSessionAttachment:
        attachment = GateEvidenceSessionAttachment(session_id=session.id, file_id=file_object.id)
        self.db.add(attachment)
        session.last_activity_at = datetime.now(timezone.utc)
        self.db.add(session)
        self.db.flush()
        return attachment

    # ---- close ----------------------------------------------------------------

    def close_session(
        self, project_id: uuid.UUID, session: GateEvidenceSession, actor: User,
    ) -> ProjectExternalApprovalSubmission:
        approval = self._get_approval(project_id, session.approval_id)
        # KTD7: this is where a reassigned-away employee's GATECLOSE fails -
        # no new coupling to project_gate_assignment.py's reassign/unassign.
        self._require_assignee(approval, actor)

        attachment_file_ids = list(
            self.db.scalars(
                select(GateEvidenceSessionAttachment.file_id).where(
                    GateEvidenceSessionAttachment.session_id == session.id
                )
            )
        )
        if session.note is None and not attachment_file_ids:
            raise HTTPException(
                422,
                "This evidence session is empty. Send a note or a photo before GATECLOSE.",
            )

        # KTD17: reuses the session's already-downloaded-and-stored
        # FileObject rows rather than re-writing the same bytes to storage a
        # second time - the exact same service a portal submission calls.
        submission = ProjectGateSubmissionService(self.db).submit(
            project_id,
            session.approval_id,
            actor,
            note=session.note,
            existing_file_ids=attachment_file_ids,
        )

        session.closed_at = datetime.now(timezone.utc)
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return submission

    # ---- expiry sweep -----------------------------------------------------

    def expire_stale_sessions(self, now: datetime) -> list[GateEvidenceSession]:
        """KTD5/KTD6: discards (never submits) every open session silent for
        `EVIDENCE_SESSION_SILENCE_DAYS` or longer. Commits after EACH
        session individually rather than batching the whole sweep into one
        transaction (KTD16) - mirrors `sweep_approval_escalations`'s own
        per-item commit discipline (`escalation.py`), so a failure partway
        through a large batch does not silently roll back the expiries
        already processed in the same pass."""
        cutoff = now - timedelta(days=EVIDENCE_SESSION_SILENCE_DAYS)
        stale_sessions = list(
            self.db.scalars(
                select(GateEvidenceSession).where(
                    GateEvidenceSession.closed_at.is_(None),
                    GateEvidenceSession.expired_at.is_(None),
                    GateEvidenceSession.last_activity_at <= cutoff,
                )
            )
        )
        expired: list[GateEvidenceSession] = []
        for session in stale_sessions:
            session.expired_at = now
            self.db.add(session)
            self.db.commit()
            expired.append(session)
        return expired
