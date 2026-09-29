"""Shared test helper: project creation refuses a start date before today
(`app.routes.projects_v2.today_ist`). Suites that create projects with fixed
historical dates pin "today" before those dates, so their schedules and
date assertions stay exactly as written."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

PINNED_TODAY = date(2026, 1, 1)


def pin_project_creation_today(test_case, today: date = PINNED_TODAY) -> None:
    patcher = patch("app.routes.projects_v2.today_ist", return_value=today)
    patcher.start()
    test_case.addCleanup(patcher.stop)
