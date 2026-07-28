from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import User
from app.services.supabase_auth import SupabaseAuthError, admin_create_user, admin_find_user_by_email


def run() -> None:
    password = settings.migration_temp_password
    if len(password) < 8:
        raise RuntimeError("Set MIGRATION_TEMP_PASSWORD to at least 8 characters for this one-time operation.")

    with SessionLocal() as db:
        users = db.scalars(select(User).where(User.supabase_user_id.is_(None)).order_by(User.created_at)).all()
        for user in users:
            try:
                identity = admin_create_user(
                    email=user.email,
                    password=password,
                    metadata={"name": user.name, "siteops_role": user.role.value},
                )
            except SupabaseAuthError as exc:
                if exc.status_code != 409:
                    raise
                identity = admin_find_user_by_email(user.email)
                if not identity:
                    raise RuntimeError(f"Could not link existing Supabase user {user.email}.") from exc
            user.supabase_user_id = identity["id"]
            user.password_hash = None
            print(f"Linked {user.email} -> {identity['id']}")
        db.commit()
        print(f"Linked {len(users)} SiteOps account(s). Send recovery emails before user acceptance testing.")


if __name__ == "__main__":
    run()
