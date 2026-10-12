# ============================================================
#  api/routes/transactions.py  —  Transaction CRUD & Review Workflow
# ============================================================

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, List
import io

from database.db import get_db
from models.transaction import Transaction, TransactionStatus
from api.deps import get_current_user, require_roles
from models.user import User, UserRole
from services import transaction_service
from services.export_service import generate_transactions_csv

router = APIRouter()


# ─────────────────────────────────────────
#  Schemas
# ─────────────────────────────────────────
class TransactionResponse(BaseModel):
    id                : str
    amount            : float
    merchant          : Optional[str]
    merchant_category : Optional[str]
    location          : Optional[str]
    card_last4        : Optional[str]
    fraud_score       : Optional[float]
    fraud_percentage  : Optional[float]
    is_fraud          : Optional[bool]
    risk_level        : Optional[str]
    risk_color        : Optional[str]
    explanation       : Optional[str]
    top_features      : Optional[list]
    status            : str
    reviewed_by       : Optional[str]
    review_notes      : Optional[str]
    reviewed_at       : Optional[str] = None
    assigned_analyst  : Optional[str] = None
    created_at        : str

    class Config:
        from_attributes = True


class ReviewRequest(BaseModel):
    status       : TransactionStatus
    review_notes : Optional[str] = None


class ReviewNotesRequest(BaseModel):
    notes            : Optional[str] = None
    assigned_analyst : Optional[str] = None


class BulkReviewRequest(BaseModel):
    transactionIds   : List[str]
    status           : TransactionStatus
    notes            : Optional[str] = None
    assigned_analyst : Optional[str] = None


class ExportFilters(BaseModel):
    riskLevel : Optional[str] = "ALL"
    status    : Optional[str] = "ALL"
    dateFrom  : Optional[str] = None
    dateTo    : Optional[str] = None
    limit     : Optional[int] = 100
    isFraud   : Optional[bool] = None


class ExportRequest(BaseModel):
    exportType     : str  # "current_page" | "selected" | "filtered" | "all" | "custom"
    transactionIds : Optional[List[str]] = None
    filters        : Optional[ExportFilters] = None


class PaginatedTransactions(BaseModel):
    total        : int
    page         : int
    per_page     : int
    transactions : List[TransactionResponse]


def risk_color(risk: Optional[str]) -> Optional[str]:
    if not risk: return None
    return {"HIGH": "#ef4444", "MEDIUM": "#f59e0b", "LOW": "#10b981"}.get(risk)


def get_val(val):
    if val is None:
        return None
    if hasattr(val, "value"):
        return val.value
    return str(val)


def format_transaction(t: Transaction) -> TransactionResponse:
    status_val = get_val(t.status) or "PENDING"
    risk_val = get_val(t.risk_level)
    return TransactionResponse(
        id                = str(t.id),
        amount            = t.amount,
        merchant          = t.merchant,
        merchant_category = t.merchant_category,
        location          = t.location,
        card_last4        = t.card_last4,
        fraud_score       = t.fraud_score,
        fraud_percentage  = round(t.fraud_score * 100, 2) if t.fraud_score else None,
        is_fraud          = t.is_fraud,
        risk_level        = risk_val,
        risk_color        = risk_color(risk_val),
        explanation       = t.explanation,
        top_features      = t.top_features,
        status            = status_val,
        reviewed_by       = t.reviewed_by,
        review_notes      = t.review_notes,
        reviewed_at       = str(t.reviewed_at) if t.reviewed_at else None,
        assigned_analyst  = t.assigned_analyst,
        created_at        = str(t.created_at)
    )


# ─────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────
@router.get("", response_model=PaginatedTransactions)
async def get_transactions(
    page       : int   = Query(1, ge=1),
    per_page   : int   = Query(20, ge=1, le=100),
    is_fraud   : Optional[bool]   = None,
    risk_level : Optional[str]    = None,
    status     : Optional[str]    = None,
    db         : AsyncSession     = Depends(get_db),
    current_user: User            = Depends(require_roles(UserRole.admin, UserRole.analyst, UserRole.fraud_analyst, UserRole.staff))
):
    total, rows = await transaction_service.get_paginated_transactions(
        db, page, per_page, is_fraud, risk_level, status
    )
    return PaginatedTransactions(
        total        = total,
        page         = page,
        per_page     = per_page,
        transactions = [format_transaction(t) for t in rows]
    )


@router.get("/flagged", response_model=List[TransactionResponse])
async def get_flagged(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.analyst, UserRole.fraud_analyst, UserRole.staff))
):
    rows = await transaction_service.get_flagged_transactions(db, limit)
    return [format_transaction(t) for t in rows]


# NOTE: /bulk-review and /export MUST be defined before /{transaction_id}
# to prevent FastAPI matching "bulk-review" or "export" as a transaction ID.
@router.put("/bulk-review", response_model=List[TransactionResponse])
async def bulk_review(
    data         : BulkReviewRequest,
    request      : Request,
    db           : AsyncSession = Depends(get_db),
    current_user : User         = Depends(require_roles(UserRole.admin, UserRole.analyst, UserRole.fraud_analyst))
):
    from services.audit_service import log_audit_event
    ip_addr = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    txns = await transaction_service.bulk_review_transactions(
        db, data.transactionIds, data.status, current_user.username, data.notes, data.assigned_analyst
    )

    status_to = data.status.value if hasattr(data.status, "value") else str(data.status)

    for t in txns:
        await log_audit_event(
            action="transaction_review_updated",
            resource_type="transaction",
            resource_id=str(t.id),
            status="success",
            actor_user_id=current_user.id,
            actor_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
            ip_address=ip_addr,
            user_agent=user_agent,
            metadata={"status_from": "bulk_update", "status_to": status_to},
            db=db
        )

    return [format_transaction(t) for t in txns]


@router.post("/export")
async def export_transactions(
    data         : ExportRequest,
    db           : AsyncSession = Depends(get_db),
    current_user : User         = Depends(require_roles(UserRole.admin, UserRole.analyst, UserRole.fraud_analyst))
):
    filters_dict = {}
    if data.filters:
        filters_dict = data.filters.model_dump()
        
    txns = await transaction_service.query_transactions_for_export(
        db, data.exportType, data.transactionIds, filters_dict
    )
    
    csv_bytes = generate_transactions_csv(txns)
    
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=transactions_export_{data.exportType}.csv"
        }
    )


@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.analyst, UserRole.fraud_analyst, UserRole.staff))
):
    t = await transaction_service.get_transaction_by_id(db, transaction_id)
    return format_transaction(t)



@router.put("/{transaction_id}/review", response_model=TransactionResponse)
async def review_transaction(
    transaction_id : str,
    data           : ReviewRequest,
    request        : Request,
    db             : AsyncSession = Depends(get_db),
    current_user   : User         = Depends(require_roles(UserRole.admin, UserRole.analyst, UserRole.fraud_analyst))
):
    from services.audit_service import log_audit_event
    ip_addr = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    orig_t = await transaction_service.get_transaction_by_id(db, transaction_id)
    status_from = orig_t.status.value if orig_t and orig_t.status else "unknown"

    t = await transaction_service.review_transaction(
        db, transaction_id, data.status, data.review_notes, current_user.username
    )

    status_to = t.status.value if t and t.status else "unknown"

    await log_audit_event(
        action="transaction_review_updated",
        resource_type="transaction",
        resource_id=transaction_id,
        status="success",
        actor_user_id=current_user.id,
        actor_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        ip_address=ip_addr,
        user_agent=user_agent,
        metadata={"status_from": status_from, "status_to": status_to},
        db=db
    )

    return format_transaction(t)


@router.put("/{transaction_id}/approve", response_model=TransactionResponse)
async def approve_transaction(
    transaction_id : str,
    data           : ReviewNotesRequest,
    request        : Request,
    db             : AsyncSession = Depends(get_db),
    current_user   : User         = Depends(require_roles(UserRole.admin, UserRole.analyst, UserRole.fraud_analyst))
):
    from services.audit_service import log_audit_event
    ip_addr = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    orig_t = await transaction_service.get_transaction_by_id(db, transaction_id)
    status_from = orig_t.status.value if orig_t and orig_t.status else "unknown"

    t = await transaction_service.approve_transaction(
        db, transaction_id, current_user.username, data.notes
    )

    await log_audit_event(
        action="transaction_review_updated",
        resource_type="transaction",
        resource_id=transaction_id,
        status="success",
        actor_user_id=current_user.id,
        actor_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        ip_address=ip_addr,
        user_agent=user_agent,
        metadata={"status_from": status_from, "status_to": "APPROVED"},
        db=db
    )

    return format_transaction(t)


@router.put("/{transaction_id}/reject", response_model=TransactionResponse)
async def reject_transaction(
    transaction_id : str,
    data           : ReviewNotesRequest,
    request        : Request,
    db             : AsyncSession = Depends(get_db),
    current_user   : User         = Depends(require_roles(UserRole.admin, UserRole.analyst, UserRole.fraud_analyst))
):
    from services.audit_service import log_audit_event
    ip_addr = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    orig_t = await transaction_service.get_transaction_by_id(db, transaction_id)
    status_from = orig_t.status.value if orig_t and orig_t.status else "unknown"

    t = await transaction_service.reject_transaction(
        db, transaction_id, current_user.username, data.notes or ""
    )

    await log_audit_event(
        action="transaction_review_updated",
        resource_type="transaction",
        resource_id=transaction_id,
        status="success",
        actor_user_id=current_user.id,
        actor_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        ip_address=ip_addr,
        user_agent=user_agent,
        metadata={"status_from": status_from, "status_to": "REJECTED"},
        db=db
    )

    return format_transaction(t)


@router.put("/{transaction_id}/flag", response_model=TransactionResponse)
async def flag_transaction(
    transaction_id : str,
    data           : ReviewNotesRequest,
    request        : Request,
    db             : AsyncSession = Depends(get_db),
    current_user   : User         = Depends(require_roles(UserRole.admin, UserRole.analyst, UserRole.fraud_analyst))
):
    from services.audit_service import log_audit_event
    ip_addr = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    orig_t = await transaction_service.get_transaction_by_id(db, transaction_id)
    status_from = orig_t.status.value if orig_t and orig_t.status else "unknown"

    t = await transaction_service.flag_transaction(
        db, transaction_id, current_user.username, data.notes, data.assigned_analyst
    )

    await log_audit_event(
        action="transaction_review_updated",
        resource_type="transaction",
        resource_id=transaction_id,
        status="success",
        actor_user_id=current_user.id,
        actor_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        ip_address=ip_addr,
        user_agent=user_agent,
        metadata={"status_from": status_from, "status_to": "FLAGGED"},
        db=db
    )

    return format_transaction(t)


# (bulk-review and export routes moved above /{transaction_id} to avoid path conflicts)
