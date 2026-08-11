"""Read models the Projects split view renders from.

These are presentation-shaped aggregates, not new domain concepts: every
number below is derived from `ProjectVisibilityService.summarize` or from
tables that already exist. Nothing here is persisted.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

AttentionGroup = Literal["Needs a decision", "Running late", "Setup incomplete"]
AttentionSeverity = Literal["decision", "warning", "critical"]


class PhaseProgressOut(BaseModel):
    phase: str
    total: int
    completed: int
    pct: int


class ProjectSummaryOut(BaseModel):
    project_id: uuid.UUID
    progress_pct: int
    total_count: int
    completed_count: int
    blocked_count: int
    delayed_count: int
    overdue_count: int
    no_update_count: int
    pending_approvals: int
    pending_verifications: int
    last_activity_at: datetime | None
    phases: list[PhaseProgressOut]


class AttentionItemOut(BaseModel):
    id: str
    group: AttentionGroup
    severity: AttentionSeverity
    title: str
    subtitle: str
    project_id: uuid.UUID
    project_code: str
    # Which workspace pane resolves the item, so the client can deep-link
    # straight at it rather than dropping the user on the overview.
    pane: str
    due_label: str | None = None
