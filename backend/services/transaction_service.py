import uuid
from typing import Optional, Tuple, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from fastapi import HTTPException

from models.transaction import Transaction, TransactionStatus

async def get_paginated_transactions(
    db: AsyncSession,
    page: int,
    per_page: int,
    is_fraud: Optional[bool] = None,
    risk_level: Optional[str] = None,
    status: Optional[str] = None
) -> Tuple[int, List[Transaction]]:
    query = select(Transaction).order_by(desc(Transaction.created_at))

    if is_fraud is not None:
        query = query.where(Transaction.is_fraud == is_fraud)
    if risk_level is not None:
        query = query.where(Transaction.risk_level == risk_level)
    if status is not None:
        query = query.where(Transaction.status == status)

    # Count total
    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar() or 0

    # Paginate
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    rows = result.scalars().all()

    return total, list(rows)

async def get_transaction_by_id(db: AsyncSession, id_str: str) -> Transaction:
    try:
        transaction_uuid = uuid.UUID(id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid transaction ID format")

    result = await db.execute(
        select(Transaction).where(Transaction.id == transaction_uuid)
    )
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return t

async def review_transaction(
    db: AsyncSession,
    id_str: str,
    status: TransactionStatus,
    review_notes: Optional[str],
    username: str
) -> Transaction:
    t = await get_transaction_by_id(db, id_str)
    t.status = status
    t.review_notes = review_notes
    t.reviewed_by = username
    await db.commit()
    await db.refresh(t)
    return t

async def get_flagged_transactions(db: AsyncSession, limit: int) -> List[Transaction]:
    result = await db.execute(
        select(Transaction)
        .where(Transaction.is_fraud == True)
        .order_by(desc(Transaction.fraud_score))
        .limit(limit)
    )
    return list(result.scalars().all())
