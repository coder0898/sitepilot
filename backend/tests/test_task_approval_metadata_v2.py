"""Unit coverage for build_approval_metadata (structured task-class /
approval metadata surfaced to the execution UI). Pure function, no DB -
covers every task_kind/task_class combination the PRD/MVP scope actually
define (standard work, class_a work, approval_gate, milestone) across the
lifecycle."""

from __future__ import annotations

import unittest

from app.services.task_approval_metadata import build_approval_metadata


class ApprovalMetadataTests(unittest.TestCase):
    # ---- milestone: never requires approval -------------------------------

    def test_milestone_never_requires_approval(self):
        for status in ("planned", "completed", "cancelled"):
            meta = build_approval_metadata("milestone", None, status)
            self.assertFalse(meta.verification_required)
            self.assertFalse(meta.approval_required)
            self.assertFalse(meta.blocks_dependents_until_approved)
            self.assertEqual(meta.approval_summary, "not_required")
            self.assertEqual(meta.approval_status, "not_required")
            self.assertIsNone(meta.verifier_role)
            self.assertIsNone(meta.approver_role)

    # ---- standard work: Supervisor verification only -----------------------

    def test_standard_work_requires_verification_not_pm_approval(self):
        meta = build_approval_metadata("work", "standard", "planned")
        self.assertTrue(meta.verification_required)
        self.assertFalse(meta.approval_required)
        self.assertFalse(meta.blocks_dependents_until_approved)
        self.assertEqual(meta.approval_summary, "supervisor_verification")
        self.assertEqual(meta.verifier_role, "site_supervisor")
        self.assertIsNone(meta.approver_role)

    def test_standard_work_approval_status_by_lifecycle_stage(self):
        cases = {
            "planned": "not_started",
            "ready": "not_started",
            "in_progress": "not_started",
            "submitted": "awaiting_verification",
            "rejected": "rejected",
            "completed": "approved",
            "cancelled": "cancelled",
        }
        for status, expected in cases.items():
            meta = build_approval_metadata("work", "standard", status)
            self.assertEqual(meta.approval_status, expected, status)

    # ---- class_a work: Supervisor verification + PM approval --------------

    def test_class_a_work_requires_verification_and_approval(self):
        meta = build_approval_metadata("work", "class_a", "planned")
        self.assertTrue(meta.verification_required)
        self.assertTrue(meta.approval_required)
        self.assertTrue(meta.blocks_dependents_until_approved)
        self.assertEqual(meta.approval_summary, "supervisor_and_pm")
        self.assertEqual(meta.verifier_role, "site_supervisor")
        self.assertEqual(meta.approver_role, "project_manager")

    def test_class_a_work_approval_status_by_lifecycle_stage(self):
        cases = {
            "in_progress": "not_started",
            "submitted": "awaiting_verification",
            "verified": "awaiting_pm_approval",
            "approval_pending": "awaiting_pm_approval",
            "rejected": "rejected",
            "completed": "approved",
        }
        for status, expected in cases.items():
            meta = build_approval_metadata("work", "class_a", status)
            self.assertEqual(meta.approval_status, expected, status)

    # ---- approval_gate: PM approval only, no Supervisor verification ------

    def test_approval_gate_requires_pm_approval_not_verification(self):
        meta = build_approval_metadata("approval_gate", "class_a", "planned")
        self.assertFalse(meta.verification_required)
        self.assertTrue(meta.approval_required)
        self.assertTrue(meta.blocks_dependents_until_approved)
        self.assertEqual(meta.approval_summary, "pm_approval")
        self.assertIsNone(meta.verifier_role)
        self.assertEqual(meta.approver_role, "project_manager")

    def test_approval_gate_submitted_is_awaiting_pm_approval_directly(self):
        # Gates skip Supervisor verification (BR-008) - `submitted` goes
        # straight to "awaiting_pm_approval", never "awaiting_verification".
        meta = build_approval_metadata("approval_gate", "class_a", "submitted")
        self.assertEqual(meta.approval_status, "awaiting_pm_approval")

    # ---- unclassified task_kind: nullable at the DB level -------------------
    # A task whose template row never had task_kind assigned during
    # authoring must still be completable - treated the same as ordinary
    # `work` (Supervisor verification), never silently as "not required"
    # (which would leave it permanently stuck with no action available).

    def test_null_task_kind_is_treated_as_standard_work(self):
        meta = build_approval_metadata(None, None, "submitted")
        self.assertTrue(meta.verification_required)
        self.assertFalse(meta.approval_required)
        self.assertEqual(meta.approval_summary, "supervisor_verification")
        self.assertEqual(meta.approval_status, "awaiting_verification")
        self.assertEqual(meta.verifier_role, "site_supervisor")

    def test_null_task_kind_with_class_a_still_requires_pm_approval(self):
        meta = build_approval_metadata(None, "class_a", "verified")
        self.assertTrue(meta.verification_required)
        self.assertTrue(meta.approval_required)
        self.assertEqual(meta.approval_summary, "supervisor_and_pm")
        self.assertEqual(meta.approval_status, "awaiting_pm_approval")


if __name__ == "__main__":
    unittest.main()
