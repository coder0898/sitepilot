import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, inspect, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import can_create_role, require_roles
from app.database import get_db
from app.models import AccessRequest, AccessRequestEvent, EmployeeProfile, ExecutionProject, ExecutionTask, User, UserAccountEvent, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.schemas.requests import MyProfileUpdateIn, UserCreateIn, UserDeleteIn, UserLifecycleIn, UserUpdateIn
from app.services.access_control import access_catalog, manageable_roles
from app.services.serializers import public_user
from app.services.supabase_auth import SupabaseAuthError, admin_create_user, admin_delete_user, admin_update_user

router = APIRouter(prefix="/api/users", tags=["users"])


def clean_required(value: str | None, label: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise HTTPException(422, f"{label} is required.")
    return cleaned


def clean_phone(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    phone = value.strip().replace(" ", "").replace("-", "")
    if not re.fullmatch(r"\+[1-9]\d{7,14}", phone):
        raise HTTPException(422, "Use an international mobile number such as +919876543210.")
    return phone


def ensure_manageable(actor: User, target: User | None) -> User:
    if not target or target.role == UserRole.super_admin or target.role not in manageable_roles(actor.role):
        raise HTTPException(403, "You cannot manage this account.")
    return target


def add_event(db: Session, target: User, actor: User, event_type: str, reason: str, from_role: UserRole | None = None, to_role: UserRole | None = None) -> None:
    db.add(UserAccountEvent(
        user_id=target.id,
        event_type=event_type,
        from_role=from_role.value if from_role else None,
        to_role=to_role.value if to_role else None,
        reason=reason,
        actor_id=actor.id,
    ))


def profile_for(db: Session, user_id: uuid.UUID) -> EmployeeProfile | None:
    return db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == user_id))


def active_accountability_message(db: Session, target: User) -> str | None:
    active_states = ("draft", "active", "on_hold")
    employee = profile_for(db, target.id)
    if employee:
        v2_project = db.scalar(
            select(V2Project)
            .join(V2ProjectMembership, V2ProjectMembership.project_id == V2Project.id)
            .where(
                V2ProjectMembership.employee_id == employee.id,
                V2ProjectMembership.ends_at.is_(None),
                V2Project.status.in_(active_states),
            )
        )
        if v2_project:
            return "End or replace this employee's active V2 project assignment before offboarding the account."
    if target.role == UserRole.project_manager:
        project = db.scalar(select(ExecutionProject).where(ExecutionProject.project_manager_id == target.id, ExecutionProject.status.in_(active_states)))
        if project:
            return "Replace this Project Manager on active projects before deactivating the account."
    if target.role == UserRole.supervisor:
        project = db.scalar(select(ExecutionProject).where(ExecutionProject.supervisor_id == target.id, ExecutionProject.status.in_(active_states)))
        task = db.scalar(select(ExecutionTask).where(ExecutionTask.assigned_supervisor_id == target.id))
        if project or task:
            return "Replace this Supervisor on active projects and tasks before deactivating the account."
    return None


@router.get("/access")
def user_access(actor: User = Depends(require_roles(*tuple(UserRole))), db: Session = Depends(get_db)):
    managed = manageable_roles(actor.role)
    if managed:
        statement = select(User).order_by(User.active.desc(), User.name)
        if actor.role == UserRole.admin:
            statement = statement.where(or_(User.id == actor.id, User.role.in_(managed)))
        users = [public_user(item, db) for item in db.scalars(statement).all()]
        mode = "manage"
    else:
        users = [public_user(actor, db)]
        mode = "profile"
    return {
        "mode": mode,
        "actor": public_user(actor, db),
        "manageable_roles": [role.value for role in managed],
        "roles": access_catalog(),
        "users": users,
    }


@router.get("/{user_id}/events")
def account_events(user_id: uuid.UUID, actor: User = Depends(require_roles(*tuple(UserRole))), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found.")
    if target.id != actor.id and target.role not in manageable_roles(actor.role):
        raise HTTPException(403, "You cannot view this account history.")
    events = db.scalars(select(UserAccountEvent).where(UserAccountEvent.user_id == user_id).order_by(UserAccountEvent.created_at.desc()).limit(20)).all()
    return [{
        "id": str(item.id),
        "event_type": item.event_type,
        "from_role": item.from_role,
        "to_role": item.to_role,
        "reason": item.reason,
        "created_at": item.created_at.isoformat(),
    } for item in events]


@router.post("")
def create_user(payload: UserCreateIn, actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)), db: Session = Depends(get_db)):
    if not can_create_role(actor.role, payload.role):
        raise HTTPException(403, "You cannot create this role.")
    if len(payload.password) < 8:
        raise HTTPException(422, "Temporary password must be at least 8 characters.")
    name = clean_required(payload.name, "Full name")
    email = clean_required(payload.email, "Email").lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(409, "An account with this email already exists.")
    employee_code = clean_required(payload.employee_code, "Employee code")
    designation = clean_required(payload.designation, "Designation")
    phone = clean_phone(payload.phone)
    try:
        auth_identity = admin_create_user(
            email=email,
            password=payload.password,
            metadata={"name": name, "siteops_role": payload.role.value},
        )
    except SupabaseAuthError as exc:
        raise HTTPException(exc.status_code, exc.public_message) from exc

    auth_user_id = uuid.UUID(auth_identity["id"])
    user = User(
        name=name,
        email=email,
        phone=phone,
        role=payload.role,
        password_hash=None,
        supabase_user_id=auth_user_id,
        activated_at=datetime.now(timezone.utc),
        created_by=actor.id,
    )
    db.add(user)
    try:
        db.flush()
        db.add(EmployeeProfile(
            user_id=user.id,
            employee_code=employee_code.upper(),
            designation=designation,
            department=(payload.department or "").strip() or None,
        ))
        add_event(db, user, actor, "ACCOUNT_CREATED", "Supabase Auth account and SiteOps access created.", to_role=payload.role)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        try:
            admin_delete_user(str(auth_user_id))
        except SupabaseAuthError:
            pass
        raise HTTPException(409, "Email or employee code is already in use.") from exc
    return public_user(user, db)


@router.put("/me/profile")
def update_my_profile(payload: MyProfileUpdateIn, actor: User = Depends(require_roles(*tuple(UserRole))), db: Session = Depends(get_db)):
    actor.name = clean_required(payload.name, "Full name")
    actor.phone = clean_phone(payload.phone)
    if actor.supabase_user_id:
        try:
            admin_update_user(str(actor.supabase_user_id), {"user_metadata": {"name": actor.name, "siteops_role": actor.role.value}})
        except SupabaseAuthError as exc:
            raise HTTPException(exc.status_code, exc.public_message) from exc
    add_event(db, actor, actor, "SELF_PROFILE_UPDATED", "Personal contact details updated.")
    db.commit()
    return public_user(actor, db)


@router.put("/{user_id}")
def update_user(user_id: uuid.UUID, payload: UserUpdateIn, actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)), db: Session = Depends(get_db)):
    target = ensure_manageable(actor, db.get(User, user_id))
    target_role = payload.role or target.role
    if target_role not in manageable_roles(actor.role):
        raise HTTPException(403, "You cannot assign this role.")
    role_changed = target_role != target.role
    if role_changed and len((payload.reason or "").strip()) < 4:
        raise HTTPException(422, "Provide a reason when changing a role.")
    if not target.supabase_user_id:
        raise HTTPException(409, "This legacy account is not linked to Supabase Auth. Link it before editing access.")

    old_role = target.role
    old_email = target.email
    target.name = clean_required(payload.name, "Full name")
    target.email = clean_required(payload.email, "Email").lower()
    target.phone = clean_phone(payload.phone)
    target.role = target_role
    profile = profile_for(db, target.id)
    if not profile:
        profile = EmployeeProfile(user_id=target.id, employee_code=clean_required(payload.employee_code, "Employee code").upper(), designation=clean_required(payload.designation, "Designation"))
        db.add(profile)
    else:
        profile.employee_code = clean_required(payload.employee_code or profile.employee_code, "Employee code").upper()
        profile.designation = clean_required(payload.designation or profile.designation, "Designation")
    profile.department = (payload.department or "").strip() or None

    try:
        admin_update_user(str(target.supabase_user_id), {
            "email": target.email,
            "user_metadata": {"name": target.name, "siteops_role": target.role.value},
        })
    except SupabaseAuthError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, exc.public_message) from exc

    add_event(db, target, actor, "ROLE_CHANGED" if role_changed else "PROFILE_UPDATED", (payload.reason or "Profile details updated.").strip(), old_role if role_changed else None, target_role if role_changed else None)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        try:
            admin_update_user(str(target.supabase_user_id), {"email": old_email})
        except SupabaseAuthError:
            pass
        raise HTTPException(409, "Email or employee code is already in use.") from exc
    return public_user(target, db)


def clean_lifecycle_reason(value: str | None) -> str:
    reason = clean_required(value, "Reason")
    if len(reason) < 4:
        raise HTTPException(422, "Provide a meaningful reason of at least four characters.")
    return reason


def set_account_active(db: Session, target: User, actor: User, active: bool, reason: str) -> User:
    if target.active == active:
        return target
    if not active:
        blocked = active_accountability_message(db, target)
        if blocked:
            raise HTTPException(409, blocked)
    if not target.supabase_user_id:
        raise HTTPException(409, "This legacy account is not linked to Supabase Auth.")
    try:
        admin_update_user(str(target.supabase_user_id), {"ban_duration": "none" if active else "876000h"})
    except SupabaseAuthError as exc:
        raise HTTPException(exc.status_code, exc.public_message) from exc
    target.active = active
    add_event(
        db,
        target,
        actor,
        "ACCOUNT_RESTORED" if active else "ACCOUNT_OFFBOARDED",
        reason,
    )
    db.commit()
    return target


def blocking_user_references(db: Session, user_id: uuid.UUID) -> list[str]:
    """Return operational FK references that make permanent deletion unsafe."""
    allowed_history = {
        ("employee_profiles", "user_id"),
        ("user_account_events", "user_id"),
        ("user_account_events", "actor_id"),
        ("access_requests", "submitted_by"),
        ("access_requests", "reviewed_by"),
        ("access_request_events", "actor_id"),
    }
    labels: list[str] = []
    database = inspect(db.bind)
    for table_name in database.get_table_names():
        for foreign_key in database.get_foreign_keys(table_name):
            if foreign_key.get("referred_table") != "users":
                continue
            for column, referred_column in zip(
                foreign_key.get("constrained_columns") or [],
                foreign_key.get("referred_columns") or [],
            ):
                if referred_column != "id" or (table_name, column) in allowed_history:
                    continue
                found = db.execute(
                    text(f'SELECT 1 FROM "{table_name}" WHERE "{column}" = :user_id LIMIT 1'),
                    {"user_id": user_id},
                ).first()
                if found:
                    labels.append(f"{table_name}.{column}")
    return sorted(set(labels))


@router.post("/{user_id}/offboard")
def offboard_user(
    user_id: uuid.UUID,
    payload: UserLifecycleIn,
    actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)),
    db: Session = Depends(get_db),
):
    target = ensure_manageable(actor, db.get(User, user_id))
    reason = clean_lifecycle_reason(payload.reason)
    return public_user(set_account_active(db, target, actor, False, reason), db)


@router.post("/{user_id}/restore")
def restore_user(
    user_id: uuid.UUID,
    payload: UserLifecycleIn,
    actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)),
    db: Session = Depends(get_db),
):
    target = ensure_manageable(actor, db.get(User, user_id))
    reason = clean_lifecycle_reason(payload.reason)
    return public_user(set_account_active(db, target, actor, True, reason), db)


@router.patch("/{user_id}/active")
def toggle_user(
    user_id: uuid.UUID,
    active: bool,
    actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)),
    db: Session = Depends(get_db),
):
    """Backward-compatible lifecycle endpoint; new UI uses offboard/restore with reasons."""
    target = ensure_manageable(actor, db.get(User, user_id))
    reason = "Account restored through legacy lifecycle endpoint." if active else "Account deactivated through legacy lifecycle endpoint."
    return public_user(set_account_active(db, target, actor, active, reason), db)


@router.delete("/{user_id}")
def delete_user(
    user_id: uuid.UUID,
    payload: UserDeleteIn,
    actor: User = Depends(require_roles(UserRole.super_admin)),
    db: Session = Depends(get_db),
):
    target = ensure_manageable(actor, db.get(User, user_id))
    reason = clean_lifecycle_reason(payload.reason)
    if target.active:
        raise HTTPException(409, "Offboard this account before permanent deletion.")
    if payload.confirmation.strip().lower() != target.email.lower():
        raise HTTPException(422, "Enter the user's exact email address to confirm permanent deletion.")

    references = blocking_user_references(db, target.id)
    if references:
        raise HTTPException(
            409,
            "This account has project, task, approval, or system ownership history. Keep it offboarded instead of deleting it.",
        )

    auth_user_id = target.supabase_user_id
    deleted_email = target.email
    related_requests = db.scalars(select(AccessRequest).where(or_(
        AccessRequest.supabase_user_id == auth_user_id,
        func.lower(AccessRequest.email) == target.email.lower(),
    ))).all()
    for access_request in related_requests:
        access_request.status = "cancelled"
        access_request.review_notes = f"Unused account permanently deleted: {reason}"
        db.add(AccessRequestEvent(
            access_request_id=access_request.id,
            event_type="UNUSED_ACCOUNT_DELETED",
            reason=reason,
            actor_id=actor.id,
        ))
    try:
        db.delete(target)
        db.flush()
        if auth_user_id:
            admin_delete_user(str(auth_user_id))
        db.commit()
    except SupabaseAuthError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, exc.public_message) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            409,
            "This account has linked business history. Keep it offboarded instead of deleting it.",
        ) from exc
    return {"message": f"Unused account {deleted_email} was permanently deleted.", "reason": reason}