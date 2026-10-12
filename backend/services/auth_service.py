# ============================================================
#  services/auth_service.py  —  Authentication and Password Policy
# ============================================================

import re
import bcrypt
from datetime import datetime, timedelta
from jose import jwt
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from config import settings
from models.user import User, UserRole


def validate_password_policy(password: str) -> None:
    """
    Enforce security policy for user passwords.
    Requirements:
    - Minimum length: 8 characters
    - Maximum length: 128 characters
    - At least one letter (a-zA-Z)
    - At least one number (0-9)
    """
    if not password or len(password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long."
        )
    if len(password) > 128:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password cannot exceed 128 characters."
        )
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password cannot exceed 72 bytes."
        )
    if not re.search(r'[A-Za-z]', password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one letter."
        )
    if not re.search(r'\d', password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one digit."
        )


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


async def register_user(db: AsyncSession, data: any, role: Optional[UserRole] = None) -> User:
    # 1. Enforce password policy before database operations
    validate_password_policy(data.password)

    # 2. Check existing email
    result = await db.execute(select(User).where(User.email == data.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    # 3. Check existing username
    result = await db.execute(select(User).where(User.username == data.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already taken")

    assigned_role = role if role is not None else getattr(data, "role", UserRole.analyst)

    user = User(
        email           = data.email,
        username        = data.username,
        full_name       = data.full_name,
        hashed_password = hash_password(data.password),
        role            = assigned_role
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, username_or_email: str, password: str) -> User:
    result = await db.execute(
        select(User).where(
            (User.username == username_or_email) | (User.email == username_or_email)
        )
    )
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    return user
