import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import current_supabase_identity, require_roles
from app.config import settings
from app.database import get_db
from app.models import AccessRequest, AccessRequestEvent, EmployeeProfile, User, UserAccountEvent, UserRole
from app.schemas.requests import AccessRequestCreateIn, AccessRequestReviewIn
from app.services.serializers import public_user
from app.services.supabase_auth import (
    SupabaseAuthError,
    admin_find_user_by_email,
    admin_update_user,
    request_email_verification,
    request_password_recovery,
)

router = APIRouter(prefix="/api/access-requests", tags=["access-requests"])

OPEN_STATUSES = ("pending_email_verification", "pending_approval")
REQUESTABLE_ROLES = {UserRole.admin, UserRole.project_manager, UserRole.supervisor, UserRole.internal_employee}
ADMIN_APPROVABLE_ROLES = {UserRole.project_manager, UserRole.supervisor, UserRole.internal_employee}


def approval_route(item: AccessRequest) -> str:
    if item.submitted_by is not None or item.requested_role == UserRole.admin:
        return "super_admin"
    return "admin_primary_super_admin_fallback"


def clean_required(value: str | None, label: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise HTTPException(422, f"{label} is required.")
    return cleaned


def clean_email(value: str | None) -> str:
    email = clean_required(value, "Work email").lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(422, "Enter a valid work email.")
    return email


def clean_phone(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    phone = value.strip().replace(" ", "").replace("-", "")
    if not re.fullmatch(r"\+[1-9]\d{7,14}", phone):
        raise HTTPException(422, "Use an international mobile number such as +919876543210.")
    return phone


def record_event(db: Session, request: AccessRequest, event_type: str, reason: str, actor_id: uuid.UUID | None = None) -> None:
    db.add(AccessRequestEvent(
        access_request_id=request.id,
        event_type=event_type,
        reason=reason,
        actor_id=actor_id,
    ))


def can_review(actor: User | None, item: AccessRequest) -> bool:
    if not actor or item.status != "pending_approval" or item.submitted_by == actor.id:
        return False
    route = approval_route(item)
    if actor.role == UserRole.super_admin:
        return item.requested_role in REQUESTABLE_ROLES
    if actor.role == UserRole.admin:
        return route == "admin_primary_super_admin_fallback" and item.requested_role in ADMIN_APPROVABLE_ROLES
    return False


def request_row(item: AccessRequest, db: Session, actor: User | None = None) -> dict:
    submitter = db.get(User, item.submitted_by) if item.submitted_by else None
    reviewer = db.get(User, item.reviewed_by) if item.reviewed_by else None
    return {
        "id": str(item.id),
        "name": item.name,
        "email": item.email,
        "phone": item.phone,
        "employee_code": item.employee_code,
        "designation": item.designation,
        "department": item.department,
        "requested_role": item.requested_role.value,
        "project_reference": item.project_reference,
        "justification": item.justification,
        "status": item.status,
        "approval_route": approval_route(item),
        "reviewer_label": "Super Admin" if approval_route(item) == "super_admin" else "Admin (Super Admin fallback)",
        "email_verified_at": item.email_verified_at.isoformat() if item.email_verified_at else None,
        "submitted_by": str(item.submitted_by) if item.submitted_by else None,
        "submitted_by_name": submitter.name if submitter else "Self-service request",
        "reviewed_by": str(item.reviewed_by) if item.reviewed_by else None,
        "reviewed_by_name": reviewer.name if reviewer else None,
        "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
        "review_notes": item.review_notes,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
        "can_review": can_review(actor, item) if actor else False,
    }


def ensure_reviewable(actor: User, item: AccessRequest | None) -> AccessRequest:
    if not item:
        raise HTTPException(404, "Access request not found.")
    if not can_review(actor, item):
        raise HTTPException(403, "You cannot review this access request.")
    return item


def ensure_no_duplicate(db: Session, email: str) -> None:
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(409, "A SiteOps account with this email already exists.")
    existing = db.scalar(select(AccessRequest).where(
        func.lower(AccessRequest.email) == email,
        AccessRequest.status.in_(OPEN_STATUSES),
    ))
    if existing:
        raise HTTPException(409, "An active access request already exists for this email.")


def create_request_record(payload: AccessRequestCreateIn, db: Session, submitted_by: uuid.UUID | None) -> AccessRequest:
    if payload.requested_role not in REQUESTABLE_ROLES:
        raise HTTPException(422, "This role cannot be requested.")
    email = clean_email(payload.email)
    ensure_no_duplicate(db, email)
    item = AccessRequest(
        name=clean_required(payload.name, "Full name"),
        email=email,
        phone=clean_phone(payload.phone),
        employee_code=clean_required(payload.employee_code, "Employee code").upper(),
        designation=clean_required(payload.designation, "Designation"),
        department=(payload.department or "").strip() or None,
        requested_role=payload.requested_role,
        project_reference=(payload.project_reference or "").strip() or None,
        justification=clean_required(payload.justification, "Access justification"),
        status="pending_email_verification",
        submitted_by=submitted_by,
    )
    db.add(item)
    db.flush()
    record_event(
        db,
        item,
        "REQUEST_SUBMITTED",
        "Access request submitted by an administrator." if submitted_by else "Self-service access request submitted.",
        submitted_by,
    )
    db.commit()
    db.refresh(item)
    return item


@router.post("")
def submit_access_request(payload: AccessRequestCreateIn, db: Session = Depends(get_db)):
    item = create_request_record(payload, db, None)
    try:
        request_email_verification(
            item.email,
            f"{settings.frontend_url.rstrip('/')}?view=verify-access",
            {"access_request_id": str(item.id), "requested_role": item.requested_role.value},
        )
        record_event(db, item, "VERIFICATION_EMAIL_SENT", "Work-email verification link sent through Supabase Auth.")
        db.commit()
    except SupabaseAuthError as exc:
        record_event(db, item, "VERIFICATION_EMAIL_FAILED", "Request saved, but the verification email could not be sent.")
        db.commit()
        raise HTTPException(exc.status_code, f"Request saved, but verification email failed: {exc.public_message}") from exc
    return request_row(item, db)


@router.post("/on-behalf")
def submit_on_behalf(
    payload: AccessRequestCreateIn,
    actor: User = Depends(require_roles(UserRole.admin)),
    db: Session = Depends(get_db),
):
    item = create_request_record(payload, db, actor.id)
    try:
        request_email_verification(
            item.email,
            f"{settings.frontend_url.rstrip('/')}/?view=verify-access",
            {"access_request_id": str(item.id), "requested_role": item.requested_role.value},
        )
        record_event(db, item, "VERIFICATION_EMAIL_SENT", "Work-email verification link sent through Supabase Auth.", actor.id)
        db.commit()
    except SupabaseAuthError as exc:
        record_event(db, item, "VERIFICATION_EMAIL_FAILED", "Request saved, but the verification email could not be sent.", actor.id)
        db.commit()
        raise HTTPException(exc.status_code, f"Request saved, but verification email failed: {exc.public_message}") from exc
    return request_row(item, db, actor)


@router.post("/{request_id}/resend-verification")
def resend_verification(
    request_id: uuid.UUID,
    actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)),
    db: Session = Depends(get_db),
):
    item = db.get(AccessRequest, request_id)
    if not item or item.status != "pending_email_verification":
        raise HTTPException(409, "Only requests awaiting email verification can receive a new verification link.")
    if actor.role == UserRole.admin and item.submitted_by != actor.id and not (
        item.submitted_by is None and item.requested_role in ADMIN_APPROVABLE_ROLES
    ):
        raise HTTPException(403, "You cannot manage this verification request.")
    try:
        request_email_verification(
            item.email,
            f"{settings.frontend_url.rstrip('/')}/?view=verify-access",
            {"access_request_id": str(item.id), "requested_role": item.requested_role.value},
        )
    except SupabaseAuthError as exc:
        raise HTTPException(exc.status_code, exc.public_message) from exc
    record_event(db, item, "VERIFICATION_EMAIL_RESENT", "Work-email verification link resent through Supabase Auth.", actor.id)
    db.commit()
    return {"message": "Verification email sent."}


@router.post("/verify")
def verify_request_email(
    identity: dict = Depends(current_supabase_identity),
    db: Session = Depends(get_db),
):
    identity_email = str(identity.get("email") or "").strip().lower()
    identity_id = identity.get("id")
    if not identity_email or not identity_id:
        raise HTTPException(401, "Supabase identity is incomplete.")
    item = db.scalar(select(AccessRequest).where(
        func.lower(AccessRequest.email) == identity_email,
        AccessRequest.status.in_(OPEN_STATUSES),
    ).order_by(AccessRequest.created_at.desc()))
    if not item:
        raise HTTPException(
            409,
            f"This verification link authenticated {identity_email}, but that email has no open access request. "
            "Sign out, then open the newest verification email for the requested account.",
        )
    if item.status == "pending_email_verification":
        item.supabase_user_id = uuid.UUID(identity_id)
        item.email_verified_at = datetime.now(timezone.utc)
        item.status = "pending_approval"
        record_event(db, item, "EMAIL_VERIFIED", "Email ownership verified through Supabase Auth.")
        db.commit()
        db.refresh(item)
    elif item.supabase_user_id and str(item.supabase_user_id) != str(identity_id):
        raise HTTPException(403, "This request belongs to another Supabase identity.")
    return request_row(item, db)

@router.get("")
def list_access_requests(
    actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)),
    db: Session = Depends(get_db),
):
    statement = select(AccessRequest).order_by(AccessRequest.created_at.desc())
    if actor.role == UserRole.admin:
        statement = statement.where(or_(
            AccessRequest.submitted_by == actor.id,
            (
                AccessRequest.submitted_by.is_(None)
                & AccessRequest.requested_role.in_(tuple(ADMIN_APPROVABLE_ROLES))
            ),
        ))
    return [request_row(item, db, actor) for item in db.scalars(statement).all()]


@router.get("/{request_id}/events")
def access_request_events(
    request_id: uuid.UUID,
    actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)),
    db: Session = Depends(get_db),
):
    item = db.get(AccessRequest, request_id)
    if not item:
        raise HTTPException(404, "Access request not found.")
    if actor.role == UserRole.admin:
        visible = item.submitted_by == actor.id or (
            item.submitted_by is None and item.requested_role in ADMIN_APPROVABLE_ROLES
        )
        if not visible:
            raise HTTPException(403, "You cannot view this request.")
    events = db.scalars(select(AccessRequestEvent).where(
        AccessRequestEvent.access_request_id == item.id
    ).order_by(AccessRequestEvent.created_at.desc())).all()
    return [{
        "id": str(event.id),
        "event_type": event.event_type,
        "reason": event.reason,
        "actor_id": str(event.actor_id) if event.actor_id else None,
        "created_at": event.created_at.isoformat(),
    } for event in events]


@router.post("/{request_id}/approve")
def approve_access_request(
    request_id: uuid.UUID,
    payload: AccessRequestReviewIn,
    actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)),
    db: Session = Depends(get_db),
):
    item = db.scalar(select(AccessRequest).where(AccessRequest.id == request_id).with_for_update())
    if not item:
        raise HTTPException(404, "Access request not found.")
    if item.status == "approved":
        existing_user = db.scalar(select(User).where(func.lower(User.email) == item.email.lower()))
        allowed_repeat = actor.role == UserRole.super_admin or (
            actor.role == UserRole.admin
            and item.submitted_by is None
            and item.requested_role in ADMIN_APPROVABLE_ROLES
        )
        if not allowed_repeat:
            raise HTTPException(403, "You cannot review this access request.")
        if not existing_user:
            raise HTTPException(409, "This request is approved, but its SiteOps account is missing. Contact Super Admin.")
        return {
            "request": request_row(item, db, actor),
            "user": public_user(existing_user, db),
            "activation_email_sent": None,
            "already_approved": True,
        }
    if item.status == "pending_email_verification":
        raise HTTPException(409, "Approval is unavailable until the employee verifies the work email.")
    item = ensure_reviewable(actor, item)
    if not item.email_verified_at or not item.supabase_user_id:
        raise HTTPException(409, "Email verification must be completed before approval.")

    final_role = payload.role or item.requested_role
    allowed_roles = REQUESTABLE_ROLES if actor.role == UserRole.super_admin else ADMIN_APPROVABLE_ROLES
    if final_role not in allowed_roles:
        raise HTTPException(403, "You cannot approve this role.")
    if db.scalar(select(User).where(func.lower(User.email) == item.email.lower())):
        raise HTTPException(409, "A SiteOps account with this email already exists.")

    employee_code = clean_required(payload.employee_code or item.employee_code, "Employee code").upper()
    if db.scalar(select(EmployeeProfile).where(func.upper(EmployeeProfile.employee_code) == employee_code)):
        raise HTTPException(409, "Employee code is already in use.")

    identity = admin_find_user_by_email(item.email)
    if not identity or str(identity.get("id")) != str(item.supabase_user_id):
        raise HTTPException(409, "The verified Supabase identity could not be found.")

    try:
        admin_update_user(str(item.supabase_user_id), {
            "email_confirm": True,
            "user_metadata": {
                "name": item.name,
                "siteops_role": final_role.value,
                "access_request_id": str(item.id),
            },
        })
    except SupabaseAuthError as exc:
        raise HTTPException(exc.status_code, exc.public_message) from exc

    user = User(
        name=item.name,
        email=item.email,
        phone=item.phone,
        role=final_role,
        active=True,
        password_hash=None,
        supabase_user_id=item.supabase_user_id,
        created_by=actor.id,
    )
    db.add(user)
    try:
        db.flush()
        db.add(EmployeeProfile(
            user_id=user.id,
            employee_code=employee_code,
            designation=clean_required(payload.designation or item.designation, "Designation"),
            department=(payload.department if payload.department is not None else item.department) or None,
        ))
        db.add(UserAccountEvent(
            user_id=user.id,
            event_type="ACCOUNT_APPROVED",
            from_role=None,
            to_role=final_role.value,
            reason=(payload.reason or "Access request reviewed and approved.").strip(),
            actor_id=actor.id,
        ))
        item.status = "approved"
        item.requested_role = final_role
        item.reviewed_by = actor.id
        item.reviewed_at = datetime.now(timezone.utc)
        item.review_notes = (payload.reason or "Access request approved.").strip()
        record_event(db, item, "REQUEST_APPROVED", item.review_notes, actor.id)
        db.commit()
        db.refresh(user)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Email or employee code is already in use.") from exc

    activation_sent = True
    try:
        request_password_recovery(item.email, f"{settings.frontend_url.rstrip('/')}/?view=reset-password")
        record_event(db, item, "ACTIVATION_EMAIL_SENT", "Password setup email sent through Supabase Auth.", actor.id)
        db.commit()
    except SupabaseAuthError:
        activation_sent = False
        record_event(db, item, "ACTIVATION_EMAIL_FAILED", "Account approved, but the password setup email could not be sent.", actor.id)
        db.commit()

    return {
        "request": request_row(item, db, actor),
        "user": public_user(user, db),
        "activation_email_sent": activation_sent,
    }


@router.post("/{request_id}/reject")
def reject_access_request(
    request_id: uuid.UUID,
    payload: AccessRequestReviewIn,
    actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)),
    db: Session = Depends(get_db),
):
    item = ensure_reviewable(actor, db.get(AccessRequest, request_id))
    reason = clean_required(payload.reason, "Rejection reason")
    if len(reason) < 4:
        raise HTTPException(422, "Provide a meaningful rejection reason.")
    item.status = "rejected"
    item.reviewed_by = actor.id
    item.reviewed_at = datetime.now(timezone.utc)
    item.review_notes = reason
    record_event(db, item, "REQUEST_REJECTED", reason, actor.id)
    db.commit()
    return request_row(item, db, actor)


@router.post("/{request_id}/resend-activation")
def resend_activation(
    request_id: uuid.UUID,
    actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)),
    db: Session = Depends(get_db),
):
    item = db.get(AccessRequest, request_id)
    if not item or item.status != "approved":
        raise HTTPException(404, "Approved access request not found.")
    if actor.role == UserRole.admin and item.requested_role not in ADMIN_APPROVABLE_ROLES:
        raise HTTPException(403, "You cannot manage this activation.")
    try:
        request_password_recovery(item.email, f"{settings.frontend_url.rstrip('/')}/?view=reset-password")
    except SupabaseAuthError as exc:
        raise HTTPException(exc.status_code, exc.public_message) from exc
    record_event(db, item, "ACTIVATION_EMAIL_RESENT", "Password setup email resent through Supabase Auth.", actor.id)
    db.commit()
    return {"message": "Password setup email sent."}