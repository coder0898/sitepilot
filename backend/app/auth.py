from datetime import datetime, timedelta, timezone
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User, UserRole

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if password_hash.startswith("plain:"):
        return password == password_hash.replace("plain:", "", 1)
    return pwd_context.verify(password, password_hash)


def make_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "name": user.name,
        "email": user.email,
        "role": user.role.value,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required.")
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
        user_id = uuid.UUID(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired. Please login again.")
    user = db.get(User, user_id)
    if not user or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="This account is inactive. Contact your Admin or Super Admin.")
    return user


def require_roles(*roles: UserRole):
    def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission for this action.")
        return user
    return dependency


def can_create_role(actor_role: UserRole, target_role: UserRole) -> bool:
    if actor_role == UserRole.super_admin:
        return target_role in {UserRole.admin, UserRole.project_manager, UserRole.supervisor}
    if actor_role == UserRole.admin:
        return target_role in {UserRole.project_manager, UserRole.supervisor}
    return False
