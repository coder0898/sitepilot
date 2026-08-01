"""Small transaction helpers for multi-row command services."""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy.orm import Session


@contextmanager
def command_transaction(db: Session) -> Iterator[Session]:
    """Commit one complete command unit, including an existing request transaction.

    Authentication and authorization perform reads before a command route runs,
    which means SQLAlchemy may already have auto-started a transaction. Command
    services still own the write unit: they commit it before returning and roll
    it back in full when any write fails.
    """
    if db.in_transaction():
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        return

    with db.begin():
        yield db
