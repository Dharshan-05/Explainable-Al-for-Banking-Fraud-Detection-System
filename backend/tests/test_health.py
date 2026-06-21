# ============================================================
#  tests/test_health.py  —  Health Check Tests
# ============================================================
import pytest
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock, MagicMock

@pytest.mark.anyio
async def test_root_endpoint(client: AsyncClient):
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running"
    assert "app" in data
    assert "version" in data
    # Health check does not leak secrets
    for key in data.keys():
        assert "secret" not in key.lower()
        assert "password" not in key.lower()

@pytest.mark.anyio
async def test_health_endpoint_healthy(client: AsyncClient):
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    
    mock_conn = AsyncMock()
    mock_conn.__aenter__.return_value = mock_conn
    mock_conn.execute = AsyncMock()
    
    mock_engine = MagicMock()
    mock_engine.connect = MagicMock(return_value=mock_conn)
    
    with patch("cache.get_redis", return_value=mock_redis), \
         patch("database.db.engine", mock_engine):
        
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["database"] == "ok"
        assert data["redis"] == "ok"
        # Health check does not leak secrets
        for val in data.values():
            assert "secret" not in str(val).lower()
            assert "password" not in str(val).lower()

@pytest.mark.anyio
async def test_health_endpoint_degraded(client: AsyncClient):
    mock_conn = AsyncMock()
    mock_conn.__aenter__.return_value = mock_conn
    mock_conn.execute = AsyncMock()
    
    mock_engine = MagicMock()
    mock_engine.connect = MagicMock(return_value=mock_conn)
    
    with patch("cache.get_redis", side_effect=Exception("Redis down")), \
         patch("database.db.engine", mock_engine):
        
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] == "ok"
        assert data["redis"] == "unavailable"

@pytest.mark.anyio
async def test_health_endpoint_db_failure(client: AsyncClient):
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    
    mock_engine = MagicMock()
    mock_engine.connect.side_effect = Exception("DB connection error")
    
    with patch("cache.get_redis", return_value=mock_redis), \
         patch("database.db.engine", mock_engine):
        
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] == "unavailable"
        assert data["redis"] == "ok"
