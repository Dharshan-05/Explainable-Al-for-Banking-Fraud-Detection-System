# ============================================================
#  api/routes/analytics.py  —  Dashboard Analytics
#  GET /api/analytics/stats
#  GET /api/analytics/trends
#  GET /api/analytics/risk-distribution
#  GET /api/analytics/top-features
#  GET /api/analytics/summary          (alias for stats)
# ============================================================

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import List, Optional

from database.db import get_db
from api.deps import get_current_user, require_roles
from models.user import User, UserRole
from services import analytics_service

router = APIRouter()


# ─────────────────────────────────────────
#  Schemas
# ─────────────────────────────────────────
class DashboardStats(BaseModel):
    total_transactions : int
    total_fraud        : int
    total_legit        : int
    fraud_rate         : float
    total_amount_at_risk : float
    high_risk_count    : int
    medium_risk_count  : int
    low_risk_count     : int
    pending_review     : int
    approved_count     : int = 0
    rejected_count     : int = 0
    flagged_count      : int = 0
    avg_fraud_score    : float = 0.0
    total_amount       : float = 0.0
    model_accuracy     : float

class TrendPoint(BaseModel):
    date        : str
    total       : int
    fraud       : int
    legit       : int
    fraud_rate  : float

class RiskDistribution(BaseModel):
    risk_level : str
    count      : int
    percentage : float
    color      : str

class TopFeature(BaseModel):
    feature         : str
    avg_shap_impact : float
    frequency       : int

class ScoreBucket(BaseModel):
    range : str
    count : int


# ─────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────
@router.get("/stats", response_model=DashboardStats)
@router.get("/summary", response_model=DashboardStats)  # alias
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.analyst))
):
    stats = await analytics_service.get_dashboard_stats(db)
    return DashboardStats(**stats)


@router.get("/trends", response_model=List[TrendPoint])
async def get_trends(
    days: Optional[int] = Query(None, ge=1, le=365),
    start_date: Optional[str] = Query(None, description="Start date format: YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="End date format: YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.analyst))
):
    trends = await analytics_service.get_daily_trends(db, days, start_date, end_date)
    return [TrendPoint(**t) for t in trends]


@router.get("/risk-distribution", response_model=List[RiskDistribution])
async def get_risk_distribution(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.analyst))
):
    dist = await analytics_service.get_risk_distribution(db)
    return [RiskDistribution(**r) for r in dist]


@router.get("/top-features", response_model=List[TopFeature])
async def get_top_features(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.analyst))
):
    features = await analytics_service.get_top_features(db)
    return [TopFeature(**f) for f in features]


@router.get("/score-distribution", response_model=List[ScoreBucket])
async def get_score_distribution(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.analyst))
):
    buckets = await analytics_service.get_score_distribution(db)
    return [ScoreBucket(**b) for b in buckets]
