from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import JWTError, jwt
import uuid

from database.db import get_db
from models.user import User, UserRole
from config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code = status.HTTP_401_UNAUTHORIZED,
        detail      = "Could not validate credentials",
        headers     = {"WWW-Authenticate": "Bearer"},
    )

    # 1. Read token from Authorization header first (for dev/testing/API client compatibility)
    token = None
    from_cookie = False
    authorization = request.headers.get("Authorization")
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]

    # 2. Fall back to cookie (standard browser auth)
    if not token:
        token = request.cookies.get(settings.COOKIE_NAME)
        if token:
            from_cookie = True

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. Double-Submit Cookie CSRF validation for mutating unsafe HTTP methods
    if from_cookie and request.method in ("POST", "PUT", "DELETE", "PATCH"):
        csrf_cookie = request.cookies.get("csrf_token")
        csrf_header = request.headers.get("x-csrf-token")

        if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF token validation failed"
            )

    try:
        payload  = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id  = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_uuid))
    user   = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exception
    return user

def require_roles(*allowed_roles: UserRole):
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have the required permissions to access this resource."
            )
        return current_user
    return role_checker

async def authenticate_ws_token(token: str, db: AsyncSession) -> User:
    """
    Decodes and validates a JWT token string for WebSockets.
    Raises ValueError with error detail on failure.
    """
    if not token or token.strip() == "":
        raise ValueError("Token required")
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise ValueError("Invalid token payload")
    except JWTError:
        raise ValueError("Invalid token")

    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise ValueError("Invalid token payload")

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise ValueError("User not active or not found")
    return user
