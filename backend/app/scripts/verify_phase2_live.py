"""Destructive staging-only Phase 2 lifecycle verification through FastAPI.

Required environment variables:
- PHASE2_API_BASE (for example http://localhost:8000)
- PHASE2_SUPER_ADMIN_TOKEN (Supabase access token)
- PHASE2_SOURCE_VERSION_ID (published version UUID to clone)

Optional:
- DATABASE_URL: when PostgreSQL, verifies the publish audit row and stored content hash.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from urllib.parse import urljoin

import httpx
from sqlalchemy import create_engine, text


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def main() -> int:
    base = required("PHASE2_API_BASE").rstrip("/") + "/"
    token = required("PHASE2_SUPER_ADMIN_TOKEN")
    source_version = required("PHASE2_SOURCE_VERSION_ID")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def call(method: str, path: str, **kwargs):
        response = client.request(method, urljoin(base, path.lstrip("/")), **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {path} failed ({response.status_code}): {response.text}")
        return response

    with httpx.Client(headers=headers, timeout=30.0) as client:
        clone = call(
            "POST",
            f"/api/v2/templates/versions/{source_version}/clone",
            json={"change_note": f"Phase 2 live verification {stamp}"},
        ).json()
        draft_id = clone["version_id"]
        version = call("GET", f"/api/v2/templates/versions/{draft_id}").json()
        revision = version["revision_token"]

        tasks = call("GET", f"/api/v2/templates/versions/{draft_id}/tasks?page=1&page_size=100").json()["items"]
        if not tasks:
            raise RuntimeError("Cloned draft contains no tasks.")
        first = tasks[0]
        updated_title = f"{first.get('title') or first['code']} [live-check {stamp}]"
        updated = call(
            "PATCH",
            f"/api/v2/templates/versions/{draft_id}/tasks/{first['id']}",
            json={"revision_token": revision, "title": updated_title[:500]},
        ).json()
        revision = updated["revision_token"]

        validation = call("POST", f"/api/v2/templates/versions/{draft_id}/validate").json()
        blocking = validation.get("severity_counts", {}).get("blocking", 0)
        if blocking:
            raise RuntimeError(f"Draft validation returned {blocking} blocking issues: {validation.get('issues')}")
        if validation.get("draft_revision"):
            revision = validation["draft_revision"]

        published = call(
            "POST",
            f"/api/v2/templates/versions/{draft_id}/publish",
            json={"revision_token": revision, "change_note": f"Phase 2 live verification publish {stamp}"},
        ).json()
        if published["status"] != "published" or not published["is_current_published"]:
            raise RuntimeError(f"Unexpected publish response: {published}")

        listing = call("GET", "/api/v2/templates?page=1&page_size=100").json()["items"]
        same_template = [item for item in listing if item["template_id"] == published["template_id"]]
        currents = [item for item in same_template if item["is_current_published"]]
        if len(currents) != 1 or currents[0]["version_id"] != draft_id:
            raise RuntimeError(f"Current published marker invalid: {currents}")

        published_version = call("GET", f"/api/v2/templates/versions/{draft_id}").json()
        immutable = client.patch(
            urljoin(base, f"/api/v2/templates/versions/{draft_id}/tasks/{first['id']}"),
            json={"revision_token": published_version["revision_token"], "title": "MUST NOT WRITE"},
        )
        if immutable.status_code not in {409, 422}:
            raise RuntimeError(f"Published mutation was not rejected: {immutable.status_code} {immutable.text}")

    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url.startswith("postgresql"):
        engine = create_engine(database_url)
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT v.content_hash,
                           (SELECT count(*) FROM siteops_v2.audit_events a
                            WHERE a.entity_id = v.id
                              AND a.action = 'template_version_published') AS audit_count
                    FROM siteops_v2.v2_template_versions v
                    WHERE v.id = :version_id
                    """
                ),
                {"version_id": draft_id},
            ).mappings().one()
            if row["content_hash"] != published["content_hash"]:
                raise RuntimeError("Stored PostgreSQL content hash does not match publish response.")
            if row["audit_count"] != 1:
                raise RuntimeError(f"Expected one publish audit event; found {row['audit_count']}.")

    print("Phase 2 live lifecycle verification PASSED")
    print(f"Published verification version: {draft_id}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"Phase 2 live lifecycle verification FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
