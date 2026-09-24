"""Storage for a question the Telegram bot is waiting for a typed answer to
(gate plan chunk 3): the Admin's rejection reason, or an optional note after
a gate health button. See `TelegramPendingInput`.

Rules:
- One pending question per chat. Asking a new one replaces the old one.
- A question is answerable for `PENDING_INPUT_TTL` after it was asked.
- Taking a question always removes it, so an answer is used at most once.
- A question that expired recently (within `EXPIRED_NOTICE_WINDOW`) still
  captures the next message once, so the person is told it expired instead
  of their answer silently becoming a command or evidence text. An older
  expired question is dropped without capturing anything.

Storage only - no gate rules. Callers commit.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.execution_models import TelegramPendingInput

PENDING_INPUT_TTL = timedelta(minutes=15)
EXPIRED_NOTICE_WINDOW = timedelta(hours=24)

KIND_REJECT_REASON = "gate_reject_reason"
KIND_HEALTH_NOTE = "gate_health_note"


@dataclass(frozen=True)
class TakenInput:
    pending: TelegramPendingInput
    expired: bool


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def set_pending(
    db: Session,
    *,
    chat_id: str,
    kind: str,
    approval_id: uuid.UUID,
    health: str | None = None,
    now: datetime | None = None,
) -> TelegramPendingInput:
    now = now or datetime.now(timezone.utc)
    db.execute(delete(TelegramPendingInput).where(TelegramPendingInput.chat_id == chat_id))
    pending = TelegramPendingInput(
        chat_id=chat_id, kind=kind, approval_id=approval_id, health=health,
        created_at=now, expires_at=now + PENDING_INPUT_TTL,
    )
    db.add(pending)
    db.flush()
    return pending


def take_pending(db: Session, chat_id: str, now: datetime | None = None) -> TakenInput | None:
    """Removes and returns this chat's pending question, if it should
    capture the next message. None when there is nothing to capture."""
    now = now or datetime.now(timezone.utc)
    pending = db.scalar(select(TelegramPendingInput).where(TelegramPendingInput.chat_id == chat_id))
    if pending is None:
        return None
    db.delete(pending)
    db.flush()
    expires_at = _aware(pending.expires_at)
    if now < expires_at:
        return TakenInput(pending=pending, expired=False)
    if now - expires_at <= EXPIRED_NOTICE_WINDOW:
        return TakenInput(pending=pending, expired=True)
    return None


def peek_pending(db: Session, chat_id: str) -> TelegramPendingInput | None:
    return db.scalar(select(TelegramPendingInput).where(TelegramPendingInput.chat_id == chat_id))
