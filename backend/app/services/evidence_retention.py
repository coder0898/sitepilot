"""Deletes evidence bytes N months after a project's actual completion.

`V2Project.completed_at` (set only by the draft/on_hold/active ->
'completed' transition in routes/projects_v2.py) anchors the clock - never
`target_handover_date`, which is a plan, not a fact, and would let a
delayed project have its still-in-use evidence swept while execution is
ongoing.

A purge deletes only the file bytes on disk. It deliberately leaves every
row alone: `FileObject` (filename/mime/size/checksum/uploader),
`TaskEvidence` / `ProjectExternalApprovalEvidence` link rows,
`TaskProgressUpdate` / `ProjectExternalApprovalSubmission` notes, and the
full `V2AuditEvent` trail. That is deliberate, not an oversight - it is
what lets `TaskProgressService.get_evidence_file` and
`ProjectGateSubmissionService.get_evidence_file` already answer "evidence
file is no longer available" for a purged file with no route change at
all: their existing `file_path.is_file()` check already handles bytes that
used to exist and no longer do. So after a purge, the record that evidence
existed, passed validation, and was approved/rejected survives - only the
pixels are gone.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.execution_models import (
    FileObject,
    ProjectExternalApproval,
    ProjectExternalApprovalEvidence,
    ProjectExternalApprovalSubmission,
    TaskEvidence,
    TaskProgressUpdate,
)
from app.project_models import V2Project

logger = logging.getLogger(__name__)

_DAYS_PER_MONTH = 30


def _eligible_projects(db: Session, retention_months: int, now: datetime) -> list[V2Project]:
    cutoff = now - timedelta(days=retention_months * _DAYS_PER_MONTH)
    return list(db.scalars(
        select(V2Project).where(
            V2Project.status == "completed",
            V2Project.completed_at.is_not(None),
            V2Project.completed_at <= cutoff,
            V2Project.evidence_purged_at.is_(None),
        )
    ).all())


def _project_evidence_file_ids(db: Session, project_id) -> set:
    task_file_ids = set(db.scalars(
        select(TaskEvidence.file_id)
        .join(TaskProgressUpdate, TaskEvidence.task_progress_update_id == TaskProgressUpdate.id)
        .where(TaskProgressUpdate.project_id == project_id)
    ))
    gate_file_ids = set(db.scalars(
        select(ProjectExternalApprovalEvidence.file_id)
        .join(ProjectExternalApprovalSubmission, ProjectExternalApprovalEvidence.submission_id == ProjectExternalApprovalSubmission.id)
        .join(ProjectExternalApproval, ProjectExternalApprovalSubmission.approval_id == ProjectExternalApproval.id)
        .where(ProjectExternalApproval.project_id == project_id)
    ))
    return task_file_ids | gate_file_ids


def _delete_file_bytes(storage_dir: Path, file_object: FileObject, project_id) -> None:
    try:
        (storage_dir / file_object.storage_key).unlink(missing_ok=True)
    except OSError:
        logger.exception("Failed to delete evidence file %s for project %s.", file_object.id, project_id)


def purge_expired_evidence(db: Session, retention_months: int | None = None, now: datetime | None = None) -> int:
    """Purges evidence bytes for every project past its retention window.

    Returns the number of projects purged in this pass. Commits once per
    project - matching `MessageDispatchService.process_pending`'s shape -
    so a crash mid-sweep leaves already-purged projects marked and does not
    repeat work on the next pass.
    """
    months = retention_months if retention_months is not None else settings.evidence_retention_months
    current_time = now or datetime.now(timezone.utc)
    storage_dir = Path(settings.evidence_upload_dir)

    projects = _eligible_projects(db, months, current_time)
    for project in projects:
        for file_id in _project_evidence_file_ids(db, project.id):
            file_object = db.get(FileObject, file_id)
            if file_object is not None:
                _delete_file_bytes(storage_dir, file_object, project.id)

        project.evidence_purged_at = current_time
        db.add(project)
        db.commit()

    return len(projects)
