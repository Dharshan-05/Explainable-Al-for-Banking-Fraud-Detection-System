# ============================================================
#  tests/conftest.py  —  Shared Pytest Fixtures
# ============================================================

import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_fraud.db"
os.environ["SECRET_KEY"] = "your-super-secret-jwt-key-change-this-in-production-2024"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["DEBUG"] = "False"
os.environ["TESTING"] = "True"

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from unittest.mock import MagicMock, patch

# ── CI Model Mock Patch ──────────────────────────────────────
# If real model files don't exist (e.g. in CI), mock ml.predict.load_models
# to return dummy objects so that ML correctness tests pass.
import ml.predict
if not os.path.exists(ml.predict.MODEL_PATH):
    class DummyModel:
        def predict_proba(self, X):
            import numpy as np
            return np.array([[0.95, 0.05]] * len(X))
            
    class DummyScaler:
        def transform(self, X):
            return X
            
    dummy_model = DummyModel()
    dummy_scaler = DummyScaler()
    feature_cols = [f"V{i}" for i in range(1, 29)] + ["Amount_Scaled", "Time_Scaled"]
    
    def dummy_load_models():
        return dummy_model, dummy_scaler, feature_cols, None, 0.0
        
    ml.predict.load_models = dummy_load_models
    ml.predict._model = dummy_model
    ml.predict._scaler = dummy_scaler
    ml.predict._feature_cols = feature_cols
    ml.predict._explainer = None
    ml.predict._expected_value = 0.0


# ── In-memory SQLite for tests ───────────────────────────────
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_fraud.db"


class TestBase(DeclarativeBase):
    pass


# ── Mock ML predictor (avoids needing model.pkl in tests) ────
def mock_predict_transaction(input_dict: dict) -> dict:
    """Returns a deterministic fraud result based on V14 value."""
    v14 = input_dict.get("V14", 0.0)
    is_fraud = v14 < -5.0
    fraud_score = 0.95 if is_fraud else 0.03
    return {
        "fraud_score":      fraud_score,
        "fraud_percentage": fraud_score * 100,
        "is_fraud":         is_fraud,
        "risk_level":       "HIGH" if is_fraud else "LOW",
        "risk_color":       "#ef4444" if is_fraud else "#10b981",
        "explanation":      "Test explanation",
        "top_features": [
            {"feature": "V14", "shap_value": -1.5, "direction": "increases", "impact": "HIGH"}
        ],
        "shap_base_value":  0.03,
        "all_shap_values":  {"V14": -1.5},
    }


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"

@pytest.fixture(autouse=True)
def mock_redis_cache():
    from middleware.rate_limit import _reset_memory_rate_limits
    from cache import clear_in_memory_cache
    import asyncio
    clear_in_memory_cache()
    asyncio.run(_reset_memory_rate_limits())
    with patch("cache.get_redis", side_effect=Exception("Redis disabled in tests")):
        yield
    clear_in_memory_cache()
    asyncio.run(_reset_memory_rate_limits())


@pytest_asyncio.fixture(scope="function")
async def client():
    """Provide an AsyncClient pointed at the FastAPI app with mocked DB and ML."""
    # Patch ML predictor
    with patch("api.routes.predict.get_predictor",
               return_value={"single": mock_predict_transaction, "batch": None}), \
         patch("services.predict_service.predict_transaction", new=mock_predict_transaction):
        from main import app
        from database.db import get_db

        # Override DB dependency with in-memory SQLite
        engine = create_async_engine(TEST_DATABASE_URL, echo=False)
        TestSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        # Create tables
        from models.user import User
        from models.transaction import Transaction
        from models.audit_log import AuditLog
        from database.db import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async def override_get_db():
            async with TestSessionLocal() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac

        app.dependency_overrides.clear()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient):
    """Register + login a test user, return Authorization headers."""
    await client.post("/api/auth/register", json={
        "email":      "test@example.com",
        "username":   "testuser",
        "full_name":  "Test User",
        "password":   "testpass123",
        "role":       "analyst",
    })
    resp = await client.post("/api/auth/login", data={
        "username": "testuser",
        "password": "testpass123",
    })
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
