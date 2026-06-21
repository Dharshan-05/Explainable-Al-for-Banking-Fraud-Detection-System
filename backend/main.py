# ============================================================
#  main.py  —  FastAPI Entry Point
#  Fraud Detection XAI Backend
# ============================================================

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from config import settings
from database.db import create_tables
from api.routes import auth, predict, transactions, analytics, audit_logs
from api.routes.ws import router as ws_router
from middleware.rate_limit import RateLimitMiddleware
from middleware.request_id import RequestIdMiddleware
from utils.logger import setup_logging

setup_logging()


# ─────────────────────────────────────────
#  Startup / Shutdown
# ─────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Starting Fraud Detection API...")
    created = await create_tables()
    if created:
        print("✅ Database tables ready!")
    print("🧠 ML model will load on first prediction request")
    print("⚡ Redis / Celery integration active")
    yield
    # Graceful shutdown — close Redis connection pool
    from cache import close_redis
    await close_redis()
    print("👋 Shutting down...")


# ─────────────────────────────────────────
#  App
# ─────────────────────────────────────────
app = FastAPI(
    title       = "Explainable AI — Banking Fraud Detection",
    description = "XGBoost + SHAP powered fraud detection API with Redis caching, Celery async jobs, and WebSocket live alerts",
    version     = "2.0.0",
    lifespan    = lifespan
)

# ─────────────────────────────────────────
#  Middleware
# ─────────────────────────────────────────

# Request correlation ID middleware
app.add_middleware(RequestIdMiddleware)

# Rate limiting (must be added BEFORE cors so headers are set)
app.add_middleware(RateLimitMiddleware)

# CORS — Allow Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["http://localhost:3000", "http://frontend:3000"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

# ─────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────
app.include_router(auth.router,         prefix="/api/auth",         tags=["Auth"])
app.include_router(predict.router,      prefix="/api/predict",      tags=["Prediction"])
app.include_router(transactions.router, prefix="/api/transactions",  tags=["Transactions"])
app.include_router(analytics.router,    prefix="/api/analytics",    tags=["Analytics"])
app.include_router(audit_logs.router,   prefix="/api/audit-logs",   tags=["Audit Logs"])
app.include_router(ws_router,           prefix="/api/ws",            tags=["WebSocket"])


# ─────────────────────────────────────────
#  Health Check
# ─────────────────────────────────────────
@app.get("/", tags=["Health"])
async def root():
    return {
        "status"  : "running",
        "app"     : "Fraud Detection XAI API",
        "version" : "2.0.0",
        "docs"    : "/docs",
        "features": ["Redis caching", "Celery async batch", "WebSocket alerts", "Rate limiting"]
    }

@app.get("/health", tags=["Health"])
async def health():
    # Quick Redis ping
    redis_status = "ok"
    try:
        from cache import get_redis
        r = await get_redis()
        await r.ping()
    except Exception:
        redis_status = "unavailable"

    # Quick DB ping
    db_status = "ok"
    try:
        from database.db import engine
        from sqlalchemy import text
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        db_status = "unavailable"

    status = "healthy"
    if redis_status != "ok" or db_status != "ok":
        status = "degraded"

    return {
        "status": status,
        "database": db_status,
        "redis": redis_status
    }
