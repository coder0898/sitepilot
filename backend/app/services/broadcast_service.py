"""Communication module: recipient resolution + send logic for `Broadcast`.

Recipient resolution reads the SAME sources Vendor Hub and project
membership already use (`V2ProjectMembership` for PM/Supervisor/Internal
Employee, `ProjectVendor` + `V2Vendor`/`V2VendorContact` for vendors) - no
new "who is on this project" concept is introduced.

Delivery is deliberately synchronous and simulated, mirroring this
codebase's existing `SandboxProviderAdapter` philosophy (see
`app/services/message_dispatch.py`'s header comment): no outbound network
call is made. A recipient with at least one contactable channel (WhatsApp
number or, for internal users, an email/in-app account) is marked 'sent'
immediately; one with none is marked 'skipped_no_contact'. Wiring a real
WhatsApp/email provider later only needs to change how a 'pending' row is
resolved - the data shape (channels, delivery_status) is already built for it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.broadcast_models import Broadcast, BroadcastRecipient, BroadcastTemplate
from app.models import EmployeeProfile, User
from app.project_models import V2Project, V2ProjectMembership
from app.routes.projects_v2 import add_audit
from app.vendor_models import ProjectVendor, V2Vendor, V2VendorContact

GROUP_ROLE_LABEL = {
    "project_manager": "Project Manager",
    "site_supervisor": "Site Supervisor",
    "internal_employee": "Internal Employee",
}
INTERNAL_GROUPS = tuple(GROUP_ROLE_LABEL)
ALL_GROUPS = INTERNAL_GROUPS + ("vendor", "vendor_contact")


def _internal_recipients(db: Session, project_id: uuid.UUID, project_role: str) -> list[dict]:
    rows = db.execute(
        select(User)
        .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
        .join(V2ProjectMembership, V2ProjectMembership.employee_id == EmployeeProfile.id)
        .where(
            V2ProjectMembership.project_id == project_id,
            V2ProjectMembership.project_role == project_role,
            V2ProjectMembership.ends_at.is_(None),
        )
        .distinct()
    ).scalars().all()
    role_label = GROUP_ROLE_LABEL[project_role]
    results = []
    for user in rows:
        # Internal users always have a portal account (email is required at
        # signup) - "no contact" only ever applies to vendors below.
        channels = ["in_app", "email"] + (["whatsapp"] if user.phone else [])
        results.append({
            "key": f"{project_role}:{user.id}", "recipient_type": project_role,
            "user_id": user.id, "vendor_id": None, "vendor_contact_id": None,
            "name": user.name, "role_label": role_label, "company_name": None,
            "phone": user.phone, "email": user.email, "channels": channels,
        })
    return results


def _vendor_recipients(db: Session, project_id: uuid.UUID) -> list[dict]:
    vendor_ids = db.scalars(select(ProjectVendor.vendor_id).where(ProjectVendor.project_id == project_id)).all()
    if not vendor_ids:
        return []
    vendors = db.scalars(select(V2Vendor).where(V2Vendor.id.in_(vendor_ids)).order_by(V2Vendor.name)).all()
    results = []
    for vendor in vendors:
        phone = vendor.whatsapp or vendor.phone
        channels = (["whatsapp"] if phone else []) + (["email"] if vendor.email else [])
        results.append({
            "key": f"vendor:{vendor.id}", "recipient_type": "vendor",
            "user_id": None, "vendor_id": vendor.id, "vendor_contact_id": None,
            "name": vendor.contact_person or vendor.name,
            "role_label": "Main Vendor" if vendor.engagement_type == "main" else "Sub-vendor",
            "company_name": vendor.name, "phone": phone, "email": vendor.email, "channels": channels,
        })
    return results


def _vendor_contact_recipients(db: Session, project_id: uuid.UUID) -> list[dict]:
    vendor_ids = db.scalars(select(ProjectVendor.vendor_id).where(ProjectVendor.project_id == project_id)).all()
    if not vendor_ids:
        return []
    rows = db.execute(
        select(V2VendorContact, V2Vendor)
        .join(V2Vendor, V2Vendor.id == V2VendorContact.vendor_id)
        .where(V2VendorContact.vendor_id.in_(vendor_ids))
        .order_by(V2Vendor.name, V2VendorContact.name)
    ).all()
    results = []
    for contact, vendor in rows:
        # V2VendorContact carries no email column - only phone/whatsapp.
        phone = contact.whatsapp or contact.phone
        channels = ["whatsapp"] if phone else []
        results.append({
            "key": f"vendor_contact:{contact.id}", "recipient_type": "vendor_contact",
            "user_id": None, "vendor_id": vendor.id, "vendor_contact_id": contact.id,
            "name": contact.name, "role_label": "Vendor Contact", "company_name": vendor.name,
            "phone": phone, "email": None, "channels": channels,
        })
    return results


def resolve_group(db: Session, project_id: uuid.UUID, group: str) -> list[dict]:
    if group in INTERNAL_GROUPS:
        return _internal_recipients(db, project_id, group)
    if group == "vendor":
        return _vendor_recipients(db, project_id)
    if group == "vendor_contact":
        return _vendor_contact_recipients(db, project_id)
    raise HTTPException(400, f"Unknown recipient group '{group}'.")


def group_counts(db: Session, project_id: uuid.UUID) -> dict[str, int]:
    return {group: len(resolve_group(db, project_id, group)) for group in ALL_GROUPS}


def resolve_recipients(db: Session, project_id: uuid.UUID, groups: list[str]) -> list[dict]:
    unknown = set(groups) - set(ALL_GROUPS)
    if unknown:
        raise HTTPException(400, f"Unknown recipient group(s): {', '.join(sorted(unknown))}.")
    seen: dict[str, dict] = {}
    for group in groups:
        for recipient in resolve_group(db, project_id, group):
            seen.setdefault(recipient["key"], recipient)
    return list(seen.values())


def _status_from_recipients(recipients: list[dict] | list[BroadcastRecipient]) -> str:
    if not recipients:
        return "failed"
    channel_of = (lambda r: r["channels"]) if isinstance(recipients[0], dict) else (lambda r: r.channels)
    skipped = sum(1 for r in recipients if not channel_of(r))
    if skipped == 0:
        return "sent"
    if skipped == len(recipients):
        return "failed"
    return "partially_failed"


def create_broadcast(
    db: Session, actor: User, project: V2Project, *,
    title: str, meeting_date, meeting_time: str | None, location_or_link: str | None,
    agenda: str | None, message_body: str, groups: list[str], excluded_keys: list[str],
    send_mode: str, scheduled_at,
) -> Broadcast:
    if not groups:
        raise HTTPException(422, "Select at least one recipient group.")
    if send_mode == "scheduled" and not scheduled_at:
        raise HTTPException(422, "A scheduled broadcast requires a scheduled date and time.")
    if send_mode == "now":
        scheduled_at = None

    excluded = set(excluded_keys or [])
    included = [r for r in resolve_recipients(db, project.id, groups) if r["key"] not in excluded]

    broadcast = Broadcast(
        project_id=project.id, title=title.strip(), meeting_date=meeting_date, meeting_time=meeting_time or None,
        location_or_link=location_or_link or None, agenda=agenda or None, message_body=message_body.strip(),
        recipient_groups=list(groups), send_mode=send_mode, scheduled_at=scheduled_at,
        status="scheduled" if send_mode == "scheduled" else _status_from_recipients(included),
        created_by=actor.id,
    )
    db.add(broadcast)
    db.flush()

    now_ts = datetime.now(timezone.utc)
    deliver_now = send_mode == "now"
    for recipient in included:
        has_channel = bool(recipient["channels"])
        db.add(BroadcastRecipient(
            broadcast_id=broadcast.id, recipient_type=recipient["recipient_type"], user_id=recipient["user_id"],
            vendor_id=recipient["vendor_id"], vendor_contact_id=recipient["vendor_contact_id"], name=recipient["name"],
            role_label=recipient["role_label"], company_name=recipient["company_name"], phone=recipient["phone"],
            email=recipient["email"], channels=recipient["channels"],
            delivery_status=("sent" if has_channel else "skipped_no_contact") if deliver_now else "pending",
            delivered_at=now_ts if deliver_now and has_channel else None,
        ))
    if deliver_now:
        broadcast.sent_at = now_ts

    add_audit(
        db, actor, project,
        "BROADCAST_SCHEDULED" if send_mode == "scheduled" else "BROADCAST_SENT",
        f"Broadcast \"{broadcast.title}\" {'scheduled' if send_mode == 'scheduled' else 'sent'} to {len(included)} recipient(s).",
        entity_type="broadcast", entity_id=broadcast.id,
    )
    db.commit()
    db.refresh(broadcast)
    return broadcast


def send_scheduled_broadcast(db: Session, actor: User, broadcast: Broadcast) -> Broadcast:
    if broadcast.status != "scheduled":
        raise HTTPException(409, "Only a scheduled broadcast can be sent.")
    recipients = db.scalars(select(BroadcastRecipient).where(BroadcastRecipient.broadcast_id == broadcast.id)).all()
    now_ts = datetime.now(timezone.utc)
    for recipient in recipients:
        recipient.delivery_status = "sent" if recipient.channels else "skipped_no_contact"
        recipient.delivered_at = now_ts if recipient.channels else None
    broadcast.status = _status_from_recipients(recipients)
    broadcast.sent_at = now_ts

    project = db.get(V2Project, broadcast.project_id)
    add_audit(
        db, actor, project, "BROADCAST_SENT",
        f"Scheduled broadcast \"{broadcast.title}\" sent to {len(recipients)} recipient(s).",
        entity_type="broadcast", entity_id=broadcast.id,
    )
    db.commit()
    db.refresh(broadcast)
    return broadcast


# ---- serialization -----------------------------------------------------

def recipient_json(recipient: BroadcastRecipient) -> dict:
    return {
        "id": str(recipient.id), "recipient_type": recipient.recipient_type, "name": recipient.name,
        "role_label": recipient.role_label, "company_name": recipient.company_name, "phone": recipient.phone,
        "email": recipient.email, "channels": recipient.channels, "delivery_status": recipient.delivery_status,
        "delivered_at": recipient.delivered_at.isoformat() if recipient.delivered_at else None,
    }


def broadcast_summary_json(db: Session, broadcast: Broadcast) -> dict:
    project = db.get(V2Project, broadcast.project_id)
    creator = db.get(User, broadcast.created_by)
    recipient_count = db.scalar(
        select(func.count()).select_from(BroadcastRecipient).where(BroadcastRecipient.broadcast_id == broadcast.id)
    ) or 0
    return {
        "id": str(broadcast.id), "project_id": str(broadcast.project_id),
        "project_name": project.name if project else "Unknown project", "project_code": project.code if project else None,
        "title": broadcast.title, "meeting_date": broadcast.meeting_date.isoformat() if broadcast.meeting_date else None,
        "meeting_time": broadcast.meeting_time, "location_or_link": broadcast.location_or_link,
        "recipient_groups": broadcast.recipient_groups, "recipient_count": recipient_count,
        "send_mode": broadcast.send_mode, "scheduled_at": broadcast.scheduled_at.isoformat() if broadcast.scheduled_at else None,
        "status": broadcast.status, "created_by_name": creator.name if creator else "SiteOps user",
        "created_at": broadcast.created_at.isoformat(), "sent_at": broadcast.sent_at.isoformat() if broadcast.sent_at else None,
    }


def broadcast_detail_json(db: Session, broadcast: Broadcast) -> dict:
    recipients = db.scalars(
        select(BroadcastRecipient).where(BroadcastRecipient.broadcast_id == broadcast.id)
        .order_by(BroadcastRecipient.role_label, BroadcastRecipient.name)
    ).all()
    data = broadcast_summary_json(db, broadcast)
    data.update({
        "agenda": broadcast.agenda, "message_body": broadcast.message_body,
        "recipients": [recipient_json(item) for item in recipients],
        "channels_used": sorted({channel for item in recipients for channel in item.channels}),
        "delivery_summary": {
            "sent": sum(1 for item in recipients if item.delivery_status == "sent"),
            "pending": sum(1 for item in recipients if item.delivery_status == "pending"),
            "skipped_no_contact": sum(1 for item in recipients if item.delivery_status == "skipped_no_contact"),
        },
    })
    return data


def template_json(template: BroadcastTemplate) -> dict:
    return {
        "id": str(template.id), "name": template.name, "title": template.title,
        "agenda": template.agenda, "message_body": template.message_body, "created_at": template.created_at.isoformat(),
    }
