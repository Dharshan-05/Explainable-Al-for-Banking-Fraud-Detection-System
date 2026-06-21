# ============================================================
#  models/user.py  —  User DB Model
# ============================================================

from sqlalchemy import Column, String, Boolean, DateTime, Enum, Uuid
from sqlalchemy.sql import func
from database.db import Base
import uuid
import enum


class UserRole(str, enum.Enum):
    admin    = "admin"
    analyst  = "analyst"
    customer = "customer"


class User(Base):
    __tablename__ = "users"

    id         = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email      = Column(String(255), unique=True, nullable=False, index=True)
    username   = Column(String(100), unique=True, nullable=False)
    full_name  = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role       = Column(Enum(UserRole), default=UserRole.analyst, nullable=False)
    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<User {self.email} ({self.role})>"
