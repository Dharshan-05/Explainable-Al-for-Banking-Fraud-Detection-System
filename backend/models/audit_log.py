# ============================================================
#  models/audit_log.py  —  Audit Log DB Model
# ============================================================

from sqlalchemy import Column, String, DateTime, JSON, Uuid, ForeignKey
from sqlalchemy.sql import func
from database.db import Base
import uuid

class AuditLog(Base):
    """
    SQLAlchemy database model for security and operational audit logs.
    Captures system actors, actions, targets, status, and request details.
    Sensitive user/card secrets are strictly prohibited from this table.
    """
    __tablename__ = "audit_logs"

    id              = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_user_id   = Column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_role      = Column(String(50), nullable=True)
    action          = Column(String(100), nullable=False, index=True)
    resource_type   = Column(String(100), nullable=False)
    resource_id     = Column(String(100), nullable=True)
    status          = Column(String(50), nullable=False, index=True)  # success | failure
    ip_address      = Column(String(45), nullable=True)
    user_agent      = Column(String(512), nullable=True)
    metadata_json   = Column(JSON, nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    def __repr__(self):
        return f"<AuditLog {self.action} actor={self.actor_user_id} status={self.status}>"
