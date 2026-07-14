from datetime import datetime, timedelta, timezone
import re
import uuid

from sqlalchemy import and_, func, or_, select

from app.config import settings
from app.database import SessionLocal
from app.models import MockNotificationReceipt, NotificationDeliveryAttempt, NotificationOutbox


RETRY_MINUTES = (1, 5, 15)
LOCK_LEASE = timedelta(minutes=5)


class TemporaryDeliveryError(Exception):
    pass


class PermanentDeliveryError(Exception):
    pass


def _utcnow():
    return datetime.now(timezone.utc)


def _phone_is_valid(phone):
    return len(re.sub(r"\D", "", phone or "")) >= 10


class MockNotificationProvider:
    name = "mock"

    def send(self, notification):
        if not _phone_is_valid(notification.phone):
            raise PermanentDeliveryError("Recipient phone number is missing or invalid.")
        if "[mock:permanent-failure]" in notification.message_preview:
            raise PermanentDeliveryError("Mock provider rejected this message permanently.")
        if "[mock:temporary-failure]" in notification.message_preview:
            raise TemporaryDeliveryError("Mock provider is temporarily unavailable.")

        with SessionLocal() as db:
            existing = db.scalar(select(MockNotificationReceipt).where(
                MockNotificationReceipt.idempotency_key == notification.idempotency_key
            ))
            if existing:
                return existing.provider_message_id, existing.delivered_at
            receipt = MockNotificationReceipt(
                idempotency_key=notification.idempotency_key,
                provider_message_id=f"mock-{uuid.uuid4()}",
                delivered_at=_utcnow(),
            )
            db.add(receipt)
            db.commit()
            return receipt.provider_message_id, receipt.delivered_at


def _provider():
    if settings.whatsapp_enabled or settings.notification_provider != "mock":
        raise RuntimeError("Real notification delivery is disabled. NOTIFICATION_PROVIDER must remain 'mock'.")
    return MockNotificationProvider()


def claim_due_notifications(limit=20, now=None):
    now = now or _utcnow()
    stale_before = now - LOCK_LEASE
    claims = []
    with SessionLocal() as db:
        due_at = func.coalesce(NotificationOutbox.next_attempt_at, NotificationOutbox.scheduled_for, NotificationOutbox.created_at)
        rows = db.scalars(
            select(NotificationOutbox)
            .where(or_(
                and_(NotificationOutbox.status == "scheduled", due_at <= now),
                and_(
                    NotificationOutbox.status == "failed",
                    NotificationOutbox.next_attempt_at.is_not(None),
                    NotificationOutbox.next_attempt_at <= now,
                    NotificationOutbox.attempt_count < NotificationOutbox.max_attempts,
                ),
                and_(NotificationOutbox.status == "sending", NotificationOutbox.locked_at < stale_before),
            ))
            .order_by(due_at, NotificationOutbox.created_at)
            .with_for_update(skip_locked=True)
            .limit(limit)
        ).all()
        for notification in rows:
            if not _phone_is_valid(notification.phone):
                notification.status = "failed"
                notification.failure_reason = "Recipient phone number is missing or invalid."
                notification.next_attempt_at = None
                notification.locked_at = None
                notification.lock_token = None
                continue
            notification.status = "sending"
            notification.attempt_count += 1
            notification.last_attempt_at = now
            notification.locked_at = now
            notification.lock_token = uuid.uuid4()
            notification.updated_at = now
            attempt = NotificationDeliveryAttempt(
                notification_id=notification.id,
                attempt_no=notification.attempt_count,
                status="sending",
                provider="mock",
                started_at=now,
            )
            db.add(attempt)
            db.flush()
            claims.append((notification.id, notification.lock_token, attempt.id))
        db.commit()
    return claims


def _mark_failure(notification_id, lock_token, attempt_id, reason, temporary, now):
    with SessionLocal() as db:
        notification = db.get(NotificationOutbox, notification_id)
        attempt = db.get(NotificationDeliveryAttempt, attempt_id)
        if not notification or notification.lock_token != lock_token:
            return
        notification.status = "failed"
        notification.failure_reason = reason
        notification.locked_at = None
        notification.lock_token = None
        notification.updated_at = now
        if temporary and notification.attempt_count < notification.max_attempts:
            delay_index = min(notification.attempt_count - 1, len(RETRY_MINUTES) - 1)
            notification.next_attempt_at = now + timedelta(minutes=RETRY_MINUTES[delay_index])
        else:
            notification.next_attempt_at = None
        if attempt:
            attempt.status = "failed"
            attempt.failure_reason = reason
            attempt.completed_at = now
        db.commit()


def send_claim(notification_id, lock_token, attempt_id, now=None):
    now = now or _utcnow()
    with SessionLocal() as db:
        notification = db.get(NotificationOutbox, notification_id)
        if not notification or notification.status != "sending" or notification.lock_token != lock_token:
            return "skipped"
        db.expunge(notification)
    try:
        provider_message_id, _ = _provider().send(notification)
    except TemporaryDeliveryError as error:
        _mark_failure(notification_id, lock_token, attempt_id, str(error), True, now)
        return "failed"
    except PermanentDeliveryError as error:
        _mark_failure(notification_id, lock_token, attempt_id, str(error), False, now)
        return "failed"

    with SessionLocal() as db:
        current = db.get(NotificationOutbox, notification_id)
        attempt = db.get(NotificationDeliveryAttempt, attempt_id)
        if not current or current.lock_token != lock_token:
            return "skipped"
        current.status = "sent"
        current.provider_message_id = provider_message_id
        current.sent_at = now
        current.failure_reason = None
        current.next_attempt_at = now + timedelta(seconds=1)
        current.locked_at = None
        current.lock_token = None
        current.updated_at = now
        if attempt:
            attempt.status = "sent"
            attempt.provider_message_id = provider_message_id
        db.commit()
    return "sent"


def deliver_sent_notifications(limit=50, now=None):
    now = now or _utcnow()
    delivered = 0
    with SessionLocal() as db:
        rows = db.scalars(
            select(NotificationOutbox)
            .where(
                NotificationOutbox.status == "sent",
                NotificationOutbox.next_attempt_at <= now,
                NotificationOutbox.provider_message_id.is_not(None),
            )
            .with_for_update(skip_locked=True)
            .limit(limit)
        ).all()
        for notification in rows:
            receipt = db.scalar(select(MockNotificationReceipt).where(
                MockNotificationReceipt.idempotency_key == notification.idempotency_key
            ))
            if not receipt:
                continue
            notification.status = "delivered"
            notification.delivered_at = receipt.delivered_at
            notification.next_attempt_at = None
            notification.updated_at = now
            attempt = db.scalar(
                select(NotificationDeliveryAttempt)
                .where(
                    NotificationDeliveryAttempt.notification_id == notification.id,
                    NotificationDeliveryAttempt.attempt_no == notification.attempt_count,
                )
            )
            if attempt:
                attempt.status = "delivered"
                attempt.completed_at = now
            delivered += 1
        db.commit()
    return delivered


def run_worker_cycle(limit=20, now=None):
    now = now or _utcnow()
    delivered = deliver_sent_notifications(limit=limit, now=now)
    claims = claim_due_notifications(limit=limit, now=now)
    results = [send_claim(*claim, now=now) for claim in claims]
    return {"claimed": len(claims), "sent": results.count("sent"), "failed": results.count("failed"), "delivered": delivered}
