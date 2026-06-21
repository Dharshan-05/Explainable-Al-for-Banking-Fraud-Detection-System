from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, Integer, cast
from fastapi import HTTPException
from datetime import datetime, timedelta
import json
from typing import List, Dict, Any, Optional

from cache import cache_get, cache_set
from models.transaction import Transaction, RiskLevel
from config import settings

CACHE_TTL = 60  # seconds

async def get_dashboard_stats(db: AsyncSession) -> dict:
    cache_key = "analytics:stats"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    # Total counts
    total = await db.execute(select(func.count(Transaction.id)))
    total_count = total.scalar() or 0

    from models.transaction import TransactionStatus

    fraud = await db.execute(select(func.count(Transaction.id)).where(Transaction.is_fraud == True))
    fraud_count = fraud.scalar() or 0

    legit_count = total_count - fraud_count
    fraud_rate  = (fraud_count / total_count * 100) if total_count > 0 else 0

    # Amount at risk (fraud transactions)
    amount_risk = await db.execute(
        select(func.sum(Transaction.amount)).where(Transaction.is_fraud == True)
    )
    total_amount = amount_risk.scalar() or 0

    # Total amount of all transactions
    total_amt = await db.execute(select(func.sum(Transaction.amount)))
    total_amount_sum = total_amt.scalar() or 0

    # Average fraud score
    avg_score = await db.execute(select(func.avg(Transaction.fraud_score)))
    avg_score_val = (avg_score.scalar() or 0) * 100

    # Risk distribution
    high = await db.execute(select(func.count(Transaction.id)).where(Transaction.risk_level == RiskLevel.HIGH))
    med  = await db.execute(select(func.count(Transaction.id)).where(Transaction.risk_level == RiskLevel.MEDIUM))
    low  = await db.execute(select(func.count(Transaction.id)).where(Transaction.risk_level == RiskLevel.LOW))

    # Pending review and other statuses
    pending = await db.execute(
        select(func.count(Transaction.id)).where(Transaction.status == TransactionStatus.pending)
    )
    approved = await db.execute(
        select(func.count(Transaction.id)).where(Transaction.status == TransactionStatus.approved)
    )
    rejected = await db.execute(
        select(func.count(Transaction.id)).where(Transaction.status == TransactionStatus.rejected)
    )
    flagged = await db.execute(
        select(func.count(Transaction.id)).where(Transaction.status == TransactionStatus.flagged)
    )

    result = {
        "total_transactions":   total_count,
        "total_fraud":          fraud_count,
        "total_legit":          legit_count,
        "fraud_rate":           round(fraud_rate, 2),
        "total_amount_at_risk": round(total_amount, 2),
        "high_risk_count":      high.scalar() or 0,
        "medium_risk_count":    med.scalar() or 0,
        "low_risk_count":       low.scalar() or 0,
        "pending_review":       pending.scalar() or 0,
        "approved_count":       approved.scalar() or 0,
        "rejected_count":       rejected.scalar() or 0,
        "flagged_count":        flagged.scalar() or 0,
        "avg_fraud_score":      round(avg_score_val, 2),
        "total_amount":         round(total_amount_sum, 2),
        "model_accuracy":       97.86  # from training
    }
    await cache_set(cache_key, result, CACHE_TTL)
    return result


async def get_daily_trends(
    db: AsyncSession,
    days: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> List[dict]:
    # Determine window date boundaries
    if start_date or end_date:
        try:
            parsed_start = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
            parsed_end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else datetime.utcnow().date()
            
            if parsed_start is None:
                # Fall back to 7 days before end date
                parsed_start = parsed_end - timedelta(days=6)
                
            if parsed_start > parsed_end:
                raise HTTPException(status_code=400, detail="start_date cannot be after end_date")
                
            if (parsed_end - parsed_start).days > 365:
                raise HTTPException(status_code=400, detail="Date range cannot exceed 365 days")
                
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
        
        start_dt = datetime.combine(parsed_start, datetime.min.time())
        end_dt = datetime.combine(parsed_end, datetime.max.time())
        total_days = (parsed_end - parsed_start).days + 1
    else:
        num_days = days or 7
        end_dt = datetime.utcnow()
        start_dt = (end_dt - timedelta(days=num_days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        total_days = num_days

    cache_key = f"analytics:trends:{days}:{start_date}:{end_date}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    is_sqlite = settings.DATABASE_URL.startswith("sqlite")
    
    if is_sqlite:
        date_expr = func.strftime("%Y-%m-%d", Transaction.created_at)
    else:
        date_expr = func.to_char(Transaction.created_at, "YYYY-MM-DD")

    # Single grouped query to retrieve counts and fraud counts per day
    query = (
        select(
            date_expr.label("day"),
            func.count(Transaction.id).label("total"),
            func.sum(
                func.coalesce(
                    cast(Transaction.is_fraud, Integer),
                    0
                )
            ).label("fraud")
        )
        .where(Transaction.created_at >= start_dt)
        .where(Transaction.created_at <= end_dt)
        .group_by("day")
        .order_by("day")
    )

    result = await db.execute(query)
    rows = result.all()

    # Map query rows by day string
    db_data = {row.day: {"total": row.total, "fraud": int(row.fraud or 0)} for row in rows if row.day}

    # Iterate through each day of the interval in order, filling empty dates with zeros
    trends = []
    current_day = start_dt
    while len(trends) < total_days:
        day_str = current_day.strftime("%Y-%m-%d")
        stats = db_data.get(day_str, {"total": 0, "fraud": 0})
        t = stats["total"]
        f = stats["fraud"]
        trends.append({
            "date":       day_str,
            "total":      t,
            "fraud":      f,
            "legit":      t - f,
            "fraud_rate": round((f / t * 100) if t > 0 else 0, 2)
        })
        current_day += timedelta(days=1)

    await cache_set(cache_key, trends, CACHE_TTL)
    return trends


async def get_risk_distribution(db: AsyncSession) -> List[dict]:
    cache_key = "analytics:risk_distribution"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    total_result = await db.execute(select(func.count(Transaction.id)))
    total = total_result.scalar() or 1

    distribution = []
    for level, color in [
        (RiskLevel.HIGH,   "#ef4444"),
        (RiskLevel.MEDIUM, "#f59e0b"),
        (RiskLevel.LOW,    "#10b981")
    ]:
        count_result = await db.execute(
            select(func.count(Transaction.id)).where(Transaction.risk_level == level)
        )
        count = count_result.scalar() or 0
        distribution.append({
            "risk_level": level.value,
            "count":      count,
            "percentage": round(count / total * 100, 2),
            "color":      color
        })

    await cache_set(cache_key, distribution, CACHE_TTL)
    return distribution


async def get_top_features(db: AsyncSession) -> List[dict]:
    # Aggregate SHAP values from recent fraud transactions
    result = await db.execute(
        select(Transaction.top_features)
        .where(Transaction.is_fraud == True)
        .where(Transaction.top_features != None)
        .limit(100)
    )
    rows = result.scalars().all()

    feature_stats: Dict[str, List[float]] = {}
    for row in rows:
        if not row: continue
        features = row if isinstance(row, list) else json.loads(row)
        for f in features:
            name = f.get("feature", "")
            val  = abs(f.get("shap_value", 0))
            if name not in feature_stats:
                feature_stats[name] = []
            feature_stats[name].append(val)

    top = sorted(
        [
            {
                "feature":         name,
                "avg_shap_impact": round(sum(vals) / len(vals), 4),
                "frequency":       len(vals)
            }
            for name, vals in feature_stats.items()
        ],
        key=lambda x: x["avg_shap_impact"],
        reverse=True
    )
    return top[:15]


async def get_score_distribution(db: AsyncSession) -> List[dict]:
    cache_key = "analytics:score_distribution"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    # Initialize buckets: 0-10%, 10-20%, ..., 90-100%
    buckets = {i: 0 for i in range(10)}

    result = await db.execute(select(Transaction.fraud_score))
    scores = result.scalars().all()

    for score in scores:
        if score is None:
            continue
        idx = min(int(score * 10), 9)
        buckets[idx] += 1

    response = [
        {"range": f"{i*10}-{(i+1)*10}%", "count": count}
        for i, count in buckets.items()
    ]

    await cache_set(cache_key, response, CACHE_TTL)
    return response
