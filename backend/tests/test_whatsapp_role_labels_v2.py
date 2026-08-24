from __future__ import annotations

import unittest

from app.models import UserRole
from app.services.whatsapp_role_labels import whatsapp_role_label


class WhatsappRoleLabelTests(unittest.TestCase):
    """Phase 2 (whatsapp-model-alignment plan, R15): one canonical label
    regardless of which of the two underlying role spellings is supplied."""

    def test_project_role_site_supervisor_and_account_role_supervisor_agree(self):
        by_project_role = whatsapp_role_label(project_role="site_supervisor")
        by_account_role = whatsapp_role_label(account_role=UserRole.supervisor)
        self.assertEqual(by_project_role, "Site Supervisor")
        self.assertEqual(by_project_role, by_account_role)

    def test_project_role_takes_precedence_when_both_supplied(self):
        label = whatsapp_role_label(project_role="project_manager", account_role=UserRole.supervisor)
        self.assertEqual(label, "Project Manager")

    def test_account_role_used_when_no_project_role(self):
        self.assertEqual(whatsapp_role_label(account_role=UserRole.admin), "Admin")
        self.assertEqual(whatsapp_role_label(account_role=UserRole.super_admin), "Super Admin")

    def test_unknown_or_missing_role_falls_back(self):
        self.assertEqual(whatsapp_role_label(), "Team Member")
        self.assertEqual(whatsapp_role_label(project_role="not_a_real_role"), "Team Member")


if __name__ == "__main__":
    unittest.main()
