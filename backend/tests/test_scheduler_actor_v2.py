from __future__ import annotations

import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.models import User, UserRole
from app.services.scheduler_actor import get_system_actor


class SchedulerActorTests(unittest.TestCase):
    """Plan Phase 8 (Part A): `get_system_actor` resolves the one dedicated
    system/service-account actor a scheduled pass uses when there is no real
    acting human behind the call - the bootstrap Super Admin, looked up by
    `settings.bootstrap_super_admin_email`, mirroring `seed.py`'s own
    `_ensure_super_admin` lookup exactly.
    """

    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        User.__table__.create(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self):
        self.engine.dispose()

    def test_resolves_the_bootstrap_super_admin_by_configured_email(self):
        with self.Session.begin() as session:
            session.add(User(
                id=uuid.uuid4(), name="Developer Super Admin", email="superadmin@siteops.local",
                role=UserRole.super_admin, active=True,
            ))

        with patch.object(settings, "bootstrap_super_admin_email", ""):
            with self.Session() as session:
                actor = get_system_actor(session)
        self.assertEqual(actor.email, "superadmin@siteops.local")
        self.assertEqual(actor.role, UserRole.super_admin)

    def test_email_lookup_is_case_and_whitespace_insensitive(self):
        """Mirrors `_ensure_super_admin`'s own `.strip().lower()` handling of
        the configured email, so a differently-cased/whitespace-padded
        setting still finds the same row."""
        with self.Session.begin() as session:
            session.add(User(
                id=uuid.uuid4(), name="Admin", email="ops@example.com",
                role=UserRole.super_admin, active=True,
            ))

        with patch.object(settings, "bootstrap_super_admin_email", "  OPS@Example.com  "):
            with self.Session() as session:
                actor = get_system_actor(session)
        self.assertEqual(actor.email, "ops@example.com")

    def test_raises_loudly_when_the_bootstrap_super_admin_does_not_exist(self):
        """A scheduler pass must fail loudly (caught/logged by its own
        loop's swallow-and-log handling), never proceed with no actor and
        silently produce garbage."""
        with patch.object(settings, "bootstrap_super_admin_email", "missing@example.com"):
            with self.Session() as session:
                with self.assertRaises(RuntimeError):
                    get_system_actor(session)


if __name__ == "__main__":
    unittest.main()
