import sys
# Force stdout/stderr to use UTF-8 to prevent UnicodeEncodeError with emojis on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

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
    # Graceful shutdown — close Redis connection pool and dispose database engine
    print("👋 Shutting down...")
    try:
        from cache import close_redis
        await close_redis()
    except Exception as e:
        print(f"⚠️ Error closing Redis: {e}")

    try:
        from database.db import engine
        await engine.dispose()
    except Exception as e:
        print(f"⚠️ Error disposing database engine: {e}")


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
    import asyncio

    async def _probe_redis() -> str:
        try:
            from cache import get_redis
            r = await get_redis()
            await r.ping()
            return "ok"
        except Exception:
            return "unavailable"

    async def _probe_db() -> str:
        try:
            from database.db import engine
            from sqlalchemy import text
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return "ok"
        except Exception:
            return "unavailable"

    # Execute both probes concurrently under a unified 2.0-second overall deadline
    t_redis = asyncio.create_task(_probe_redis())
    t_db = asyncio.create_task(_probe_db())

    try:
        redis_status, db_status = await asyncio.wait_for(
            asyncio.gather(t_redis, t_db),
            timeout=2.0
        )
    except TimeoutError:
        redis_status = t_redis.result() if (t_redis.done() and not t_redis.cancelled() and not t_redis.exception()) else "unavailable"
        db_status = t_db.result() if (t_db.done() and not t_db.cancelled() and not t_db.exception()) else "unavailable"
        t_redis.cancel()
        t_db.cancel()
    except Exception:
        redis_status = "unavailable"
        db_status = "unavailable"
        t_redis.cancel()
        t_db.cancel()

    status = "healthy"
    if redis_status != "ok" or db_status != "ok":
        status = "degraded"

    return {
        "status": status,
        "database": db_status,
        "redis": redis_status
    }
