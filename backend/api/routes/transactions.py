# ============================================================
#  api/routes/transactions.py  —  Transaction CRUD
#  GET  /api/transactions
#  GET  /api/transactions/:id
#  PUT  /api/transactions/:id/review
#  GET  /api/transactions/flagged
# ============================================================

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, List

from database.db import get_db
from models.transaction import Transaction, TransactionStatus
from api.deps import get_current_user, require_roles
from models.user import User, UserRole
from services import transaction_service

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
    created_at        : str

    class Config:
        from_attributes = True

class ReviewRequest(BaseModel):
    status       : TransactionStatus
    review_notes : Optional[str] = None

class PaginatedTransactions(BaseModel):
    total        : int
    page         : int
    per_page     : int
    transactions : List[TransactionResponse]


def risk_color(risk: Optional[str]) -> Optional[str]:
    if not risk: return None
    return {"HIGH": "#ef4444", "MEDIUM": "#f59e0b", "LOW": "#10b981"}.get(risk)

def format_transaction(t: Transaction) -> TransactionResponse:
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
        risk_level        = t.risk_level.value if t.risk_level else None,
        risk_color        = risk_color(t.risk_level.value if t.risk_level else None),
        explanation       = t.explanation,
        top_features      = t.top_features,
        status            = t.status.value,
        reviewed_by       = t.reviewed_by,
        review_notes      = t.review_notes,
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
    current_user: User            = Depends(require_roles(UserRole.admin, UserRole.analyst))
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
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.analyst))
):
    rows = await transaction_service.get_flagged_transactions(db, limit)
    return [format_transaction(t) for t in rows]


@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.analyst))
):
    t = await transaction_service.get_transaction_by_id(db, transaction_id)
    return format_transaction(t)


@router.put("/{transaction_id}/review", response_model=TransactionResponse)
async def review_transaction(
    transaction_id : str,
    data           : ReviewRequest,
    request        : Request,
    db             : AsyncSession = Depends(get_db),
    current_user   : User         = Depends(require_roles(UserRole.admin, UserRole.analyst))
):
    from services.audit_service import log_audit_event
    from services import transaction_service
    ip_addr = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    # Retrieve current transaction to log status_from
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
