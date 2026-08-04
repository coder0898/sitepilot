"""Phase 2 U4: durable outbox event emission (R6/BR-015).

`OutboxService.emit` writes one `OutboxEvent` row for a business-meaningful
mutation, in the SAME transaction as the domain mutation that caused it.
This is the entire point of the outbox pattern, and the reason `emit()`
NEVER calls `self.db.commit()`: it only ever `self.db.add()`s and
`self.db.flush()`es. Every call site in this codebase already owns its own
commit - either directly, or via a nested service call (e.g.
`TaskVerificationService.verify` calling `TaskLifecycleService.transition`,
whose own `self.db.commit()` closes the transaction) - and `emit()` rides
inside that same still-open transaction. If the outbox insert fails (for
example an idempotency-key collision surfaced as an IntegrityError at flush
time), the exception propagates up through the caller and rolls back the
domain mutation with it. An outbox row and the domain row it describes can
therefore never disagree: either both commit together, or neither does.

Idempotency: `idempotency_key` is unique at the DB level. `emit()` checks
for an existing row with the same key BEFORE adding a new one and returns
`None` (a no-op, no row added) if one is already present - so retrying the
same logical mutation (e.g. a client retry after a timed-out response that
actually succeeded server-side) never produces a second outbox row for the
same logical event.

This unit (U4) only ever writes `status='pending'` rows via `emit()` - it
does not dispatch or send anything. A later unit is responsible for reading
`pending` rows and moving them to `dispatched`/`failed`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import OutboxEvent


class OutboxService:
    def __init__(self, db: Session):
        self.db = db

    def emit(
        self,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: uuid.UUID,
        payload: dict,
        idempotency_key: str,
    ) -> OutboxEvent | None:
        """Adds and flushes (never commits - the caller's own transaction,
        or its containing call site's, covers it). Returns `None` (a
        no-op) if `idempotency_key` already exists, so retrying the same
        logical mutation never double-emits."""
        existing = self.db.scalar(
            select(OutboxEvent.id).where(OutboxEvent.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return None

        event = OutboxEvent(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
            idempotency_key=idempotency_key,
            status="pending",
        )
        self.db.add(event)
        self.db.flush()
        return event
