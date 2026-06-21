# ============================================================
#  api/routes/audit_logs.py  —  Admin Audit Logs Endpoint
#  GET /api/audit-logs
# ============================================================

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from database.db import get_db
from api.deps import require_roles
from models.user import User, UserRole
from models.audit_log import AuditLog
from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime
import uuid

router = APIRouter()

class AuditLogResponse(BaseModel):
    id: str
    actor_user_id: Optional[str]
    actor_role: Optional[str]
    action: str
    resource_type: str
    resource_id: Optional[str]
    status: str
    ip_address: Optional[str]
    user_agent: Optional[str]
    metadata_json: Optional[Any]
    created_at: str

    class Config:
        from_attributes = True

class PaginatedAuditLogs(BaseModel):
    total: int
    page: int
    per_page: int
    logs: List[AuditLogResponse]

@router.get("", response_model=PaginatedAuditLogs)
async def get_audit_logs(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    action: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    status: Optional[str] = None,
    resource_type: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin))
):
    """
    Retrieve audit logs. Accessible by admin users only.
    Provides pagination and optional filtering by action, actor_user_id, status, resource_type, start_date, and end_date.
    """
    # Base query
    query = select(AuditLog)

    # Optional Filters
    if action:
        query = query.where(AuditLog.action == action)
    if actor_user_id:
        try:
            actor_uuid = uuid.UUID(actor_user_id)
            query = query.where(AuditLog.actor_user_id == actor_uuid)
        except ValueError:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail="Invalid actor_user_id format. Must be a valid UUID."
            )
    if status:
        query = query.where(AuditLog.status == status)
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
    if start_date:
        query = query.where(AuditLog.created_at >= start_date)
    if end_date:
        query = query.where(AuditLog.created_at <= end_date)

    # Count total matching records
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination and sorting
    query = query.order_by(desc(AuditLog.created_at))
    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    rows = result.scalars().all()

    # Format output
    logs_formatted = []
    for row in rows:
        logs_formatted.append(AuditLogResponse(
            id=str(row.id),
            actor_user_id=str(row.actor_user_id) if row.actor_user_id else None,
            actor_role=row.actor_role,
            action=row.action,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            status=row.status,
            ip_address=row.ip_address,
            user_agent=row.user_agent,
            metadata_json=row.metadata_json,
            created_at=str(row.created_at)
        ))

    return PaginatedAuditLogs(
        total=total,
        page=page,
        per_page=per_page,
        logs=logs_formatted
    )
