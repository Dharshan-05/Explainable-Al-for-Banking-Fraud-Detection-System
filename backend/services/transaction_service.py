import uuid
from datetime import datetime
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
        status_val = status.upper() if isinstance(status, str) else status
        query = query.where(Transaction.status == status_val)

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
    t.reviewed_at = datetime.utcnow()
    await db.commit()
    await db.refresh(t)
    return t

async def approve_transaction(
    db: AsyncSession,
    id_str: str,
    username: str,
    notes: Optional[str]
) -> Transaction:
    t = await get_transaction_by_id(db, id_str)
    t.status = TransactionStatus.APPROVED
    t.reviewed_by = username
    t.review_notes = notes
    t.reviewed_at = datetime.utcnow()
    await db.commit()
    await db.refresh(t)
    return t

async def reject_transaction(
    db: AsyncSession,
    id_str: str,
    username: str,
    notes: str
) -> Transaction:
    if not notes or not notes.strip():
        raise HTTPException(status_code=400, detail="Review notes are mandatory for rejection")
    t = await get_transaction_by_id(db, id_str)
    t.status = TransactionStatus.REJECTED
    t.reviewed_by = username
    t.review_notes = notes
    t.reviewed_at = datetime.utcnow()
    await db.commit()
    await db.refresh(t)
    return t

async def flag_transaction(
    db: AsyncSession,
    id_str: str,
    username: str,
    notes: Optional[str],
    assigned_analyst: Optional[str] = None
) -> Transaction:
    t = await get_transaction_by_id(db, id_str)
    t.status = TransactionStatus.FLAGGED
    t.reviewed_by = username
    t.review_notes = notes
    t.reviewed_at = datetime.utcnow()
    if assigned_analyst:
        t.assigned_analyst = assigned_analyst
    await db.commit()
    await db.refresh(t)
    return t

async def bulk_review_transactions(
    db: AsyncSession,
    transaction_ids: List[str],
    status: TransactionStatus,
    username: str,
    notes: Optional[str] = None,
    assigned_analyst: Optional[str] = None
) -> List[Transaction]:
    status_val = status
    if (status_val == TransactionStatus.REJECTED or status_val == TransactionStatus.rejected) and (not notes or not notes.strip()):
        raise HTTPException(status_code=400, detail="Review notes are mandatory for rejection")
        
    uuids = []
    for id_str in transaction_ids:
        try:
            uuids.append(uuid.UUID(id_str))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid transaction ID: {id_str}")
            
    result = await db.execute(
        select(Transaction).where(Transaction.id.in_(uuids))
    )
    txns = result.scalars().all()
    
    for t in txns:
        t.status = status_val
        t.reviewed_by = username
        t.review_notes = notes
        t.reviewed_at = datetime.utcnow()
        if status_val == TransactionStatus.FLAGGED and assigned_analyst:
            t.assigned_analyst = assigned_analyst
            
    await db.commit()
    return list(txns)

async def get_flagged_transactions(db: AsyncSession, limit: int) -> List[Transaction]:
    result = await db.execute(
        select(Transaction)
        .where(Transaction.is_fraud == True)
        .order_by(desc(Transaction.fraud_score))
        .limit(limit)
    )
    return list(result.scalars().all())

async def query_transactions_for_export(
    db: AsyncSession,
    export_type: str,
    transaction_ids: Optional[List[str]] = None,
    filters: Optional[dict] = None
) -> List[Transaction]:
    filters = filters or {}
    query = select(Transaction).order_by(desc(Transaction.created_at))
    
    if export_type == "selected":
        if not transaction_ids:
            return []
        uuids = []
        for id_str in transaction_ids:
            try:
                uuids.append(uuid.UUID(id_str))
            except ValueError:
                continue
        query = query.where(Transaction.id.in_(uuids))
        result = await db.execute(query)
        return list(result.scalars().all())
        
    elif export_type == "current_page":
        if not transaction_ids:
            return []
        uuids = []
        for id_str in transaction_ids:
            try:
                uuids.append(uuid.UUID(id_str))
            except ValueError:
                continue
        query = query.where(Transaction.id.in_(uuids))
        result = await db.execute(query)
        return list(result.scalars().all())
        
    elif export_type == "filtered":
        risk_level = filters.get("riskLevel")
        status = filters.get("status")
        is_fraud = filters.get("isFraud")
        
        if risk_level and risk_level.upper() != "ALL":
            query = query.where(Transaction.risk_level == risk_level.upper())
        if status and status.upper() != "ALL":
            query = query.where(Transaction.status == status.upper())
        if is_fraud is not None:
            query = query.where(Transaction.is_fraud == is_fraud)
            
        result = await db.execute(query)
        return list(result.scalars().all())
        
    elif export_type == "custom":
        risk_level = filters.get("riskLevel")
        status = filters.get("status")
        date_from = filters.get("dateFrom")
        date_to = filters.get("dateTo")
        limit = filters.get("limit", 100)
        
        if risk_level and risk_level.upper() != "ALL":
            query = query.where(Transaction.risk_level == risk_level.upper())
        if status and status.upper() != "ALL":
            query = query.where(Transaction.status == status.upper())
            
        if date_from:
            try:
                dt_from = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
                query = query.where(Transaction.created_at >= dt_from)
            except ValueError:
                pass
        if date_to:
            try:
                dt_to = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
                query = query.where(Transaction.created_at <= dt_to)
            except ValueError:
                pass
                
        if limit and limit > 0:
            query = query.limit(limit)
            
        result = await db.execute(query)
        return list(result.scalars().all())
        
    else: # "all"
        result = await db.execute(query)
        return list(result.scalars().all())
