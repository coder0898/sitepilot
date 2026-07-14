from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import delete, func, select

from app.database import SessionLocal
from app.models import MockNotificationReceipt, NotificationDeliveryAttempt, NotificationOutbox, ExecutionTask, User, UserRole
from app.routes.execution_v2 import retry_notification
from app.services.notification_delivery import claim_due_notifications, deliver_sent_notifications, send_claim


def create_notification(db, task_id, key, message, phone="9999999999", scheduled_for=None, notification_type="task_assignment"):
    item = NotificationOutbox(
        task_id=task_id,
        recipient_type="supervisor",
        recipient_name="Regression Recipient",
        phone=phone,
        message_preview=message,
        notification_type=notification_type,
        scheduled_for=scheduled_for,
        status="scheduled",
        idempotency_key=key,
    )
    db.add(item)
    db.flush()
    return item.id


def main():
    prefix = f"regression-{uuid.uuid4()}"
    keys = [f"{prefix}-{name}" for name in ("success", "temporary", "future", "missing")]
    notification_ids = []
    base = datetime.now(timezone.utc) + timedelta(days=30)
    try:
        with SessionLocal() as db:
            task_id = db.scalar(select(ExecutionTask.id).limit(1))
            actor = db.scalar(select(User).where(User.role == UserRole.super_admin))
            assert task_id and actor
            actor_id = actor.id
            success_id = create_notification(db, task_id, keys[0], "Mock assignment success", scheduled_for=base)
            temporary_id = create_notification(db, task_id, keys[1], "[mock:temporary-failure] Retry test", scheduled_for=base + timedelta(minutes=1))
            future_id = create_notification(db, task_id, keys[2], "Future material reminder", scheduled_for=base + timedelta(days=2), notification_type="material_reminder")
            missing_id = create_notification(db, task_id, keys[3], "Missing phone test", phone=None, scheduled_for=base + timedelta(minutes=1, seconds=30))
            notification_ids.extend([success_id, temporary_id, future_id, missing_id])
            db.commit()

        first_claim = claim_due_notifications(limit=1, now=base + timedelta(seconds=5))
        duplicate_claim = claim_due_notifications(limit=1, now=base + timedelta(seconds=5))
        assert len(first_claim) == 1 and first_claim[0][0] == success_id
        assert duplicate_claim == []
        assert send_claim(*first_claim[0], now=base + timedelta(seconds=5)) == "sent"
        assert deliver_sent_notifications(now=base + timedelta(seconds=7)) == 1

        temporary_claim = claim_due_notifications(limit=1, now=base + timedelta(minutes=1, seconds=5))
        assert len(temporary_claim) == 1 and temporary_claim[0][0] == temporary_id
        assert send_claim(*temporary_claim[0], now=base + timedelta(minutes=1, seconds=5)) == "failed"

        missing_claim = claim_due_notifications(limit=1, now=base + timedelta(minutes=1, seconds=35))
        assert missing_claim == []

        with SessionLocal() as db:
            temporary = db.get(NotificationOutbox, temporary_id)
            temporary.message_preview = "Retry recovered successfully"
            actor = db.get(User, actor_id)
            retry_notification(temporary_id, actor, db)

        retry_claim = claim_due_notifications(limit=1, now=base + timedelta(minutes=3))
        assert len(retry_claim) == 1 and retry_claim[0][0] == temporary_id
        assert send_claim(*retry_claim[0], now=base + timedelta(minutes=3)) == "sent"
        assert deliver_sent_notifications(now=base + timedelta(minutes=3, seconds=2)) == 1

        with SessionLocal() as db:
            success = db.get(NotificationOutbox, success_id)
            temporary = db.get(NotificationOutbox, temporary_id)
            future = db.get(NotificationOutbox, future_id)
            missing = db.get(NotificationOutbox, missing_id)
            receipt_count = db.scalar(select(func.count()).select_from(MockNotificationReceipt).where(MockNotificationReceipt.idempotency_key == keys[0]))
            temporary_attempts = db.scalar(select(func.count()).select_from(NotificationDeliveryAttempt).where(NotificationDeliveryAttempt.notification_id == temporary_id))
            result = {
                "success_delivered": success.status == "delivered",
                "duplicate_claim_blocked": duplicate_claim == [],
                "single_provider_receipt": receipt_count == 1,
                "temporary_failure_retried": temporary.status == "delivered" and temporary.attempt_count == 2 and temporary_attempts == 2,
                "missing_phone_permanent_failure": missing.status == "failed" and missing.next_attempt_at is None,
                "future_material_reminder_still_scheduled": future.status == "scheduled" and future.attempt_count == 0,
            }
            assert all(result.values()), result
            print(result)
    finally:
        with SessionLocal() as db:
            db.execute(delete(NotificationOutbox).where(NotificationOutbox.id.in_(notification_ids)))
            db.execute(delete(MockNotificationReceipt).where(MockNotificationReceipt.idempotency_key.in_(keys)))
            db.commit()


if __name__ == "__main__":
    main()
