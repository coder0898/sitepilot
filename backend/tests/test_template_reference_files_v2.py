"""Template Builder Phase 2: Admin reference files on template tasks and
prerequisite approvals (template side - upload, remove, preview, clone,
delete and publish). Reference files are never execution evidence."""
from __future__ import annotations

import io
import unittest
import uuid
import zipfile
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.database import get_db
from app.execution_models import FileObject
from app.models import User, UserRole
from app.project_models import V2AuditEvent
from app.repositories.template_validation_repository import TemplateValidationRepository
from app.routes.templates_v2 import router
from app.services.template_mutation_access import concurrency_token
from app.services.template_publish_service import compute_persisted_content_hash
from app.template_models import (
    V2Template,
    V2TemplateExternalGate,
    V2TemplateExternalGateTask,
    V2TemplateGateReferenceFile,
    V2TemplateTask,
    V2TemplateTaskDependency,
    V2TemplateTaskReferenceFile,
    V2TemplateVersion,
)

@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ACTOR_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def office_file(member: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(member, "<doc/>")
    return buffer.getvalue()


SAMPLES = {
    "spec.pdf": (b"%PDF-1.7\n%test\n", "application/pdf"),
    "photo.jpg": (b"\xff\xd8\xff\xe0" + b"0" * 32, "image/jpeg"),
    "plan.png": (b"\x89PNG\r\n\x1a\n" + b"0" * 32, "image/png"),
    "site.webp": (b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"0" * 32, "image/webp"),
    "method.docx": (office_file("word/document.xml"), DOCX),
    "boq.xlsx": (office_file("xl/workbook.xml"), XLSX),
}


class TemplateReferenceFileTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            dbapi_connection.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)

        for table in (
            V2Template.__table__, V2TemplateVersion.__table__, V2TemplateTask.__table__,
            V2TemplateTaskDependency.__table__, V2TemplateExternalGate.__table__, V2TemplateExternalGateTask.__table__,
            FileObject.__table__, V2TemplateTaskReferenceFile.__table__, V2TemplateGateReferenceFile.__table__,
            V2AuditEvent.__table__,
        ):
            table.create(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()

        self.role = UserRole.admin
        self.app = FastAPI()
        self.app.include_router(router)

        def override_db():
            with self.Session() as session:
                session.scalar(select(V2Template.id).limit(1))
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self.app.dependency_overrides[current_user] = lambda: User(
            id=ACTOR_ID, name="Actor", email="actor@example.com", role=self.role, active=True,
        )
        self.client = TestClient(self.app)
        self.storage: dict[str, bytes] = {}
        self.write_patch = patch("app.services.template_reference_files.evidence_storage.write",
                                 side_effect=lambda key, data, _type: self.storage.__setitem__(key, data))
        self.read_patch = patch("app.services.template_reference_files.evidence_storage.read",
                                side_effect=lambda key: self.storage.get(key))
        self.write_patch.start()
        self.read_patch.start()

    def tearDown(self):
        self.write_patch.stop()
        self.read_patch.stop()
        self.client.close()
        self.engine.dispose()

    def _seed(self):
        with self.Session.begin() as session:
            template = V2Template(code="REF", name="Reference template")
            session.add(template)
            session.flush()
            draft = V2TemplateVersion(template_id=template.id, version_no=2, status="draft", duration_days=45,
                                      is_current_published=False, created_by=ACTOR_ID,
                                      updated_at=datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc))
            published = V2TemplateVersion(template_id=template.id, version_no=1, status="published", duration_days=45,
                                          content_hash="published", is_current_published=True, created_by=ACTOR_ID,
                                          published_by=ACTOR_ID, published_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
            session.add_all([draft, published])
            session.flush()
            task = self._task(draft.id, "T001")
            other_task = self._task(draft.id, "T002", sequence_no=2)
            published_task = self._task(published.id, "T001")
            gate = self._gate(draft.id, "E001")
            published_gate = self._gate(published.id, "E001")
            session.add_all([task, other_task, published_task, gate, published_gate])
            session.flush()
            # A reference already locked into the published version.
            locked = FileObject(storage_key="template-references/locked.pdf", original_filename="locked.pdf",
                                mime_type="application/pdf", size_bytes=10, checksum="c", uploaded_by=ACTOR_ID)
            session.add(locked)
            session.flush()
            session.add(V2TemplateTaskReferenceFile(template_task_id=published_task.id, file_id=locked.id,
                                                    description="Locked spec", created_by=ACTOR_ID))
            self.template_id, self.draft_id, self.published_id = template.id, draft.id, published.id
            self.task_id, self.other_task_id, self.published_task_id = task.id, other_task.id, published_task.id
            self.gate_id, self.published_gate_id = gate.id, published_gate.id
            self.locked_file_id = locked.id

    @staticmethod
    def _task(version_id, code, sequence_no=1):
        return V2TemplateTask(template_version_id=version_id, code=code, sequence_no=sequence_no, title=f"Task {code}",
                              schedule_classification="execution", planned_start_day=1, planned_end_day=2,
                              applicability="mandatory", evidence_required=False, duration_days=2)

    @staticmethod
    def _gate(version_id, code):
        return V2TemplateExternalGate(template_version_id=version_id, code=code, approval_name="Fire NOC",
                                      mapping_classification="unmapped", requires_configuration=True, sequence_no=1)

    # ---- helpers -----------------------------------------------------------

    def revision(self, version_id=None):
        with self.Session() as session:
            return concurrency_token(session.get(V2TemplateVersion, version_id or self.draft_id))

    def upload(self, filename="spec.pdf", data=None, content_type=None, *, target="tasks", owner_id=None,
               version_id=None, description="Approved spec", revision_token=None):
        sample_data, sample_type = SAMPLES.get(filename, (b"", "application/octet-stream"))
        return self.client.post(
            f"/api/v2/templates/versions/{version_id or self.draft_id}/{target}/{owner_id or (self.task_id if target == 'tasks' else self.gate_id)}/reference-files",
            data={"revision_token": revision_token or self.revision(version_id), "description": description},
            files={"file": (filename, sample_data if data is None else data, content_type or sample_type)},
        )

    def count(self, model):
        with self.Session() as session:
            return session.scalar(select(func.count()).select_from(model))

    # ---- upload --------------------------------------------------------------

    def test_every_allowed_type_uploads_and_is_listed_on_the_task(self):
        for filename in SAMPLES:
            with self.subTest(filename=filename):
                response = self.upload(filename)
                self.assertEqual(response.status_code, 201, response.text)
                body = response.json()
                self.assertEqual(body["reference"]["filename"], filename)
                self.assertEqual(body["reference"]["description"], "Approved spec")
                self.assertNotEqual(body["revision_token"], "")
        listed = self.client.get(f"/api/v2/templates/versions/{self.draft_id}/tasks", params={"page_size": 100}).json()
        task = next(item for item in listed["items"] if item["id"] == str(self.task_id))
        self.assertEqual(sorted(ref["filename"] for ref in task["reference_files"]), sorted(SAMPLES))
        self.assertTrue(all(key.startswith(f"template-references/{self.draft_id}/") for key in self.storage))

    def test_office_files_sent_as_octet_stream_are_accepted_by_content(self):
        data, _ = SAMPLES["boq.xlsx"]
        response = self.upload("boq.xlsx", data, "application/octet-stream")
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["reference"]["mime_type"], XLSX)

    def test_invalid_files_are_rejected_and_nothing_is_stored(self):
        cases = [
            ("tool.exe", b"MZ\x90\x00", "application/octet-stream"),
            ("page.pdf", b"<html><script>alert(1)</script></html>", "application/pdf"),
            ("spec.pdf", SAMPLES["spec.pdf"][0], "text/html"),
            ("empty.pdf", b"", "application/pdf"),
            ("big.pdf", b"%PDF-" + b"0" * (10 * 1024 * 1024), "application/pdf"),
            ("notes.docx", b"PK\x03\x04 not really a zip", DOCX),
            ("sheet.xlsx", office_file("word/document.xml"), XLSX),
        ]
        for filename, data, content_type in cases:
            with self.subTest(filename=filename):
                response = self.upload(filename, data, content_type)
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.storage, {})
        self.assertEqual(self.count(V2TemplateTaskReferenceFile), 1)  # only the seeded published one
        self.assertEqual(self.count(FileObject), 1)

    def test_only_org_admins_can_add_or_remove_reference_files(self):
        for role in (UserRole.project_manager, UserRole.supervisor, UserRole.internal_employee):
            with self.subTest(role=role):
                self.role = role
                self.assertEqual(self.upload().status_code, 403)
        self.role = UserRole.super_admin
        self.assertEqual(self.upload().status_code, 201)
        self.assertEqual(self.storage.__len__(), 1)

    def test_published_versions_and_stale_drafts_cannot_change(self):
        published = self.upload(version_id=self.published_id, owner_id=self.published_task_id)
        self.assertEqual(published.status_code, 409, published.text)
        stale = self.upload(revision_token="stale-token")
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(self.storage, {})

    def test_a_task_from_another_version_is_not_found(self):
        response = self.upload(owner_id=self.published_task_id)
        self.assertEqual(response.status_code, 404, response.text)

    # ---- remove / preview -----------------------------------------------------

    def test_removing_a_reference_keeps_the_stored_file(self):
        added = self.upload().json()
        reference_id = added["reference"]["id"]
        removed = self.client.delete(
            f"/api/v2/templates/versions/{self.draft_id}/tasks/{self.task_id}/reference-files/{reference_id}",
            params={"revision_token": added["revision_token"]},
        )
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertTrue(removed.json()["deleted"])
        with self.Session() as session:
            self.assertIsNone(session.get(V2TemplateTaskReferenceFile, uuid.UUID(reference_id)))
            self.assertIsNotNone(session.get(FileObject, uuid.UUID(added["reference"]["file_id"])))
        self.assertEqual(len(self.storage), 1)

    def test_gate_reference_files_upload_list_and_download(self):
        added = self.upload("spec.pdf", target="gates", description="NOC form")
        self.assertEqual(added.status_code, 201, added.text)
        listed = self.client.get(f"/api/v2/templates/versions/{self.draft_id}/gates", params={"page_size": 100}).json()
        gate = next(item for item in listed["items"] if item["id"] == str(self.gate_id))
        self.assertEqual([ref["description"] for ref in gate["reference_files"]], ["NOC form"])
        download = self.client.get(
            f"/api/v2/templates/versions/{self.draft_id}/gates/{self.gate_id}/reference-files/{added.json()['reference']['id']}"
        )
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, SAMPLES["spec.pdf"][0])
        self.assertIn("attachment", download.headers["content-disposition"])
        self.assertEqual(download.headers["x-content-type-options"], "nosniff")

    def test_template_preview_follows_version_visibility(self):
        reference_id = self.upload().json()["reference"]["id"]
        url = f"/api/v2/templates/versions/{self.draft_id}/tasks/{self.task_id}/reference-files/{reference_id}"
        self.assertEqual(self.client.get(url).status_code, 200)
        self.role = UserRole.project_manager
        self.assertEqual(self.client.get(url).status_code, 404)  # PMs never see drafts
        with self.Session() as session:
            locked_link = session.scalar(select(V2TemplateTaskReferenceFile).where(
                V2TemplateTaskReferenceFile.template_task_id == self.published_task_id))
        self.storage["template-references/locked.pdf"] = b"%PDF-locked"
        published_url = (f"/api/v2/templates/versions/{self.published_id}/tasks/{self.published_task_id}"
                         f"/reference-files/{locked_link.id}")
        self.assertEqual(self.client.get(published_url).status_code, 200)
        self.role = UserRole.supervisor
        self.assertEqual(self.client.get(published_url).status_code, 403)

    # ---- clone / delete / publish ---------------------------------------------

    def test_clone_shares_the_files_and_leaves_the_source_untouched(self):
        self.upload()
        self.upload("spec.pdf", target="gates", description="NOC form")
        cloned = self.client.post(f"/api/v2/templates/versions/{self.draft_id}/clone", json={"change_note": "Next"})
        self.assertEqual(cloned.status_code, 201, cloned.text)
        target_id = uuid.UUID(cloned.json()["version_id"])
        with self.Session() as session:
            source_task_refs = session.scalars(select(V2TemplateTaskReferenceFile).where(
                V2TemplateTaskReferenceFile.template_task_id == self.task_id)).all()
            target_task = session.scalar(select(V2TemplateTask).where(
                V2TemplateTask.template_version_id == target_id, V2TemplateTask.code == "T001"))
            target_task_refs = session.scalars(select(V2TemplateTaskReferenceFile).where(
                V2TemplateTaskReferenceFile.template_task_id == target_task.id)).all()
            target_gate = session.scalar(select(V2TemplateExternalGate).where(
                V2TemplateExternalGate.template_version_id == target_id))
            target_gate_refs = session.scalars(select(V2TemplateGateReferenceFile).where(
                V2TemplateGateReferenceFile.gate_id == target_gate.id)).all()
        self.assertEqual([r.file_id for r in target_task_refs], [r.file_id for r in source_task_refs])
        self.assertEqual([r.description for r in target_task_refs], ["Approved spec"])
        self.assertEqual(len(target_gate_refs), 1)
        self.assertEqual(len(self.storage), 2)  # no bytes copied

        # Removing the clone's link does not touch the source.
        target_link = target_task_refs[0]
        removed = self.client.delete(
            f"/api/v2/templates/versions/{target_id}/tasks/{target_task.id}/reference-files/{target_link.id}",
            params={"revision_token": self.revision(target_id)},
        )
        self.assertEqual(removed.status_code, 200, removed.text)
        with self.Session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(V2TemplateTaskReferenceFile).where(
                V2TemplateTaskReferenceFile.template_task_id == self.task_id)), 1)

    def test_deleting_a_task_gate_or_draft_removes_their_links(self):
        self.upload(owner_id=self.other_task_id)
        task_delete = self.client.delete(f"/api/v2/templates/versions/{self.draft_id}/tasks/{self.other_task_id}",
                                         params={"revision_token": self.revision()})
        self.assertEqual(task_delete.status_code, 200, task_delete.text)
        self.upload(target="gates")
        gate_delete = self.client.delete(f"/api/v2/templates/versions/{self.draft_id}/gates/{self.gate_id}",
                                         params={"revision_token": self.revision()})
        self.assertEqual(gate_delete.status_code, 200, gate_delete.text)
        self.assertEqual(self.count(V2TemplateGateReferenceFile), 0)
        self.upload()
        draft_delete = self.client.request("DELETE", f"/api/v2/templates/versions/{self.draft_id}",
                                           json={"revision_token": self.revision(), "reason": "Not needed"})
        self.assertEqual(draft_delete.status_code, 200, draft_delete.text)
        # Only the published version's locked reference remains.
        self.assertEqual(self.count(V2TemplateTaskReferenceFile), 1)

    def test_reference_files_are_part_of_the_published_content(self):
        with self.Session() as session:
            before = compute_persisted_content_hash(TemplateValidationRepository(session).load(self.draft_id))
        self.upload()
        with self.Session() as session:
            after = compute_persisted_content_hash(TemplateValidationRepository(session).load(self.draft_id))
        self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()
