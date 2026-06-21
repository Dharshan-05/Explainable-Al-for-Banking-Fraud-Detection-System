# ============================================================
#  api/routes/auth.py  —  Authentication Routes
#  POST /api/auth/register
#  POST /api/auth/login
#  GET  /api/auth/me
# ============================================================

from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, EmailStr
from typing import Optional
import secrets

from database.db import get_db
from models.user import User, UserRole
from config import settings
from api.deps import oauth2_scheme, get_current_user, require_roles
from services.auth_service import register_user, authenticate_user, create_access_token

router = APIRouter()


# ─────────────────────────────────────────
#  Schemas
# ─────────────────────────────────────────
class RegisterRequest(BaseModel):
    email     : EmailStr
    username  : str
    full_name : str
    password  : str
    role      : UserRole = UserRole.analyst

class UserResponse(BaseModel):
    id        : str
    email     : str
    username  : str
    full_name : str
    role      : str
    is_active : bool

class TokenResponse(BaseModel):
    access_token : str
    token_type   : str
    user         : UserResponse


# ─────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────
@router.post("/register", response_model=UserResponse, status_code=201)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    user = await register_user(db, data)
    return UserResponse(
        id=str(user.id), email=user.email, username=user.username,
        full_name=user.full_name, role=user.role.value if hasattr(user.role, "value") else str(user.role), is_active=user.is_active
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    response: Response,
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    from services.audit_service import log_audit_event
    ip_addr = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    try:
        user = await authenticate_user(db, form_data.username, form_data.password)
    except HTTPException as e:
        await log_audit_event(
            action="login",
            resource_type="user",
            status="failure",
            ip_address=ip_addr,
            user_agent=user_agent,
            metadata={"error_category": "invalid_credentials", "login_identifier_present": True, "error_detail": e.detail},
            db=db
        )
        raise e

    if not user.is_active:
        await log_audit_event(
            action="login",
            resource_type="user",
            resource_id=str(user.id),
            status="failure",
            actor_user_id=user.id,
            actor_role=user.role.value if hasattr(user.role, "value") else str(user.role),
            ip_address=ip_addr,
            user_agent=user_agent,
            metadata={"error_category": "account_disabled", "login_identifier_present": True, "error_detail": "Account is disabled"},
            db=db
        )
        raise HTTPException(status_code=400, detail="Account is disabled")

    token = create_access_token(data={"sub": str(user.id), "role": user.role.value if hasattr(user.role, "value") else str(user.role)})

    # Set HttpOnly access_token cookie
    response.set_cookie(
        key=settings.COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )

    # Set JavaScript-readable csrf_token cookie for double-submit protection
    csrf_token = secrets.token_hex(32)
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )

    await log_audit_event(
        action="login",
        resource_type="user",
        resource_id=str(user.id),
        status="success",
        actor_user_id=user.id,
        actor_role=user.role.value if hasattr(user.role, "value") else str(user.role),
        ip_address=ip_addr,
        user_agent=user_agent,
        db=db
    )

    return TokenResponse(
        access_token = token,
        token_type   = "bearer",
        user         = UserResponse(
            id=str(user.id), email=user.email, username=user.username,
            full_name=user.full_name, role=user.role.value if hasattr(user.role, "value") else str(user.role), is_active=user.is_active
        )
    )


@router.post("/logout")
async def logout(
    response: Response,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    from services.audit_service import log_audit_event
    ip_addr = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    # Clear both cookies by setting max_age=0 / deleting them
    response.delete_cookie(
        key=settings.COOKIE_NAME,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN
    )
    response.delete_cookie(
        key="csrf_token",
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN
    )

    await log_audit_event(
        action="logout",
        resource_type="user",
        resource_id=str(current_user.id),
        status="success",
        actor_user_id=current_user.id,
        actor_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        ip_address=ip_addr,
        user_agent=user_agent,
        db=db
    )
    return {"status": "success", "message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=str(current_user.id), email=current_user.email,
        username=current_user.username, full_name=current_user.full_name,
        role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role), is_active=current_user.is_active
    )
