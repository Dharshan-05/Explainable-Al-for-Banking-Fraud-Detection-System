import logging
from typing import Optional, Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from database.db import AsyncSessionLocal
from models.audit_log import AuditLog
import uuid

# Logger dedicated to structured auditing records
logger = logging.getLogger("audit")

# Secrets and large payloads to redact
SENSITIVE_SUBSTRINGS = {
    "password", "token", "jwt", "access_token", "refresh_token",
    "csrf", "secret", "credential", "card", "pan", "cvv",
    "transactions", "rows", "payload", "csv"
}

def redact_sensitive_values(data: Any) -> Any:
    """
    Recursively scans and redacts keys containing sensitive substrings.
    """
    if isinstance(data, dict):
        cleaned = {}
        for k, v in data.items():
            k_lower = k.lower()
            if any(sub in k_lower for sub in SENSITIVE_SUBSTRINGS):
                cleaned[k] = "[REDACTED]"
            else:
                cleaned[k] = redact_sensitive_values(v)
        return cleaned
    elif isinstance(data, list):
        return [redact_sensitive_values(item) for item in data]
    return data

def sanitize_metadata(metadata: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Ensures only verified, safe metadata parameters are recorded.
    """
    if not metadata:
        return None

    # Redact sensitive keys recursively first
    redacted = redact_sensitive_values(metadata)

    # Explicit whitelist of permitted metadata fields
    allowed_keys = {
        "task_id", "file_size", "total", "processed", "failed", "fraud_count",
        "status_from", "status_to", "error_category", "error_detail", "login_identifier_present"
    }

    sanitized = {}
    for k, v in redacted.items():
        if k in allowed_keys:
            sanitized[k] = v

    return sanitized if sanitized else None

async def log_audit_event(
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    status: str = "success",
    actor_user_id: Optional[uuid.UUID] = None,
    actor_role: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
) -> None:
    """
    Records an audit log entry to stdout structured console and the database.
    This database write is fail-safe; failures will not block the main request execution flow.
    """
    # Sanitize metadata to remove PII and credentials
    sanitized_meta = sanitize_metadata(metadata)

    # Print structured console JSON log
    log_extra = {
        "event_type": "audit_log",
        "actor_user_id": str(actor_user_id) if actor_user_id else None,
        "actor_role": actor_role,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "status": status,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "extra_data": sanitized_meta,
    }
    logger.info(
        f"Audit Event: {action} on {resource_type} ({status})",
        extra=log_extra
    )

    # Execute DB commit inside try/except block with dedicated session
    # so primary business flow is never blocked or corrupted.
    session = None
    try:
        session = AsyncSessionLocal()
        entry = AuditLog(
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            status=status,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata_json=sanitized_meta
        )
        session.add(entry)
        await session.commit()
    except Exception as db_exc:
        # Rollback dedicated session only
        if session is not None:
            try:
                await session.rollback()
            except Exception:
                pass
        logger.error(
            "Failed to commit audit event to database",
            exc_info=False,  # Never dump raw database tracebacks containing credentials
            extra={
                "event_type": "audit_write_failed",
                "error_category": db_exc.__class__.__name__,
                "error_detail": str(db_exc)
            }
        )
    finally:
        # Always close dedicated session
        if session is not None:
            await session.close()
