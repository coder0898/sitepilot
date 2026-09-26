"""Storage for a question the Telegram bot is waiting for a typed answer to
(gate plan chunk 3): the Admin's rejection reason, or an optional note after
a gate health button - and, from Telegram task plan U6, questions about an
internal task (e.g. the reason for starting it early). See
`TelegramPendingInput`.

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

# Telegram task plan U6+: questions about an internal task (`task_id` set,
# `approval_id` empty). Handled by `telegram_task_callback.py`.
KIND_TASK_EARLY_START_REASON = "task_early_start_reason"
# Not a question but a mode (U7, KTD8): while open, every text or media
# message from the chat is a progress update for the task. Read without being
# taken, its expiry slides forward with each item.
KIND_TASK_ADD_PROGRESS = "task_add_progress"
ADD_PROGRESS_TTL = timedelta(minutes=10)
KIND_TASK_VERIFY_REJECT_REASON = "task_verify_reject_reason"
TASK_KINDS = frozenset({
    KIND_TASK_EARLY_START_REASON,
    KIND_TASK_VERIFY_REJECT_REASON,
    "task_approval_reject_reason",
    "task_blocker_type",
    "task_blocker_description",
    KIND_TASK_ADD_PROGRESS,
})


def is_task_question(pending: TelegramPendingInput) -> bool:
    return pending.kind in TASK_KINDS


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
    approval_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    health: str | None = None,
    draft_text: str | None = None,
    review_token: str | None = None,
    ttl: timedelta = PENDING_INPUT_TTL,
    now: datetime | None = None,
) -> TelegramPendingInput:
    """A gate question passes `approval_id`, a task question `task_id`."""
    now = now or datetime.now(timezone.utc)
    db.execute(delete(TelegramPendingInput).where(TelegramPendingInput.chat_id == chat_id))
    pending = TelegramPendingInput(
        chat_id=chat_id, kind=kind, approval_id=approval_id, task_id=task_id, health=health,
        draft_text=draft_text, review_token=review_token,
        created_at=now, expires_at=now + ttl,
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


def open_add_progress_mode(db: Session, chat_id: str, now: datetime | None = None) -> TelegramPendingInput | None:
    """This chat's Add Progress mode while it is still open. An expired mode
    is dropped silently - unlike a question, it never captures a message
    just to say it expired (KTD8). Callers commit."""
    now = now or datetime.now(timezone.utc)
    pending = peek_pending(db, chat_id)
    if pending is None or pending.kind != KIND_TASK_ADD_PROGRESS:
        return None
    if now >= _aware(pending.expires_at):
        db.delete(pending)
        db.flush()
        return None
    return pending


def close_add_progress_mode(db: Session, chat_id: str) -> bool:
    """Closes the chat's Add Progress mode, if any. Callers commit."""
    pending = peek_pending(db, chat_id)
    if pending is None or pending.kind != KIND_TASK_ADD_PROGRESS:
        return False
    db.delete(pending)
    db.flush()
    return True
