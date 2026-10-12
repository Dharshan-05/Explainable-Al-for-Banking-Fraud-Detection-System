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


@pytest.mark.anyio
async def test_health_endpoint_redis_timeout(client: AsyncClient):
    import asyncio
    async def slow_ping():
        await asyncio.sleep(5.0)
        return True

    mock_redis = AsyncMock()
    mock_redis.ping = slow_ping

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
        assert data["status"] == "degraded"
        assert data["redis"] == "unavailable"
        assert data["database"] == "ok"


@pytest.mark.anyio
async def test_health_endpoint_db_timeout(client: AsyncClient):
    import asyncio
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)

    class SlowAsyncContext:
        async def __aenter__(self):
            await asyncio.sleep(5.0)
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_engine = MagicMock()
    mock_engine.connect = MagicMock(return_value=SlowAsyncContext())

    with patch("cache.get_redis", return_value=mock_redis), \
         patch("database.db.engine", mock_engine):

        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] == "unavailable"
        assert data["redis"] == "ok"


@pytest.mark.anyio
async def test_health_endpoint_dual_timeout(client: AsyncClient):
    """When both Redis and DB hang simultaneously, the endpoint must complete within the 2s deadline and return degraded."""
    import asyncio, time
    async def slow_ping():
        await asyncio.sleep(5.0)
        return True

    mock_redis = AsyncMock()
    mock_redis.ping = slow_ping

    class SlowAsyncContext:
        async def __aenter__(self):
            await asyncio.sleep(5.0)
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_engine = MagicMock()
    mock_engine.connect = MagicMock(return_value=SlowAsyncContext())

    with patch("cache.get_redis", return_value=mock_redis), \
         patch("database.db.engine", mock_engine):

        t0 = time.perf_counter()
        response = await client.get("/health")
        elapsed = time.perf_counter() - t0

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["redis"] == "unavailable"
        assert data["database"] == "unavailable"
        # Verify overall deadline: finished well before 4.0s sequential sum
        assert elapsed < 3.2, f"Dual timeout took {elapsed}s; expected < 3.2s"


@pytest.mark.anyio
async def test_health_endpoint_get_redis_hang(client: AsyncClient):
    """When get_redis() itself hangs before returning a client, the overall timeout must catch it."""
    import asyncio, time
    async def slow_get_redis():
        await asyncio.sleep(5.0)
        return AsyncMock()

    mock_conn = AsyncMock()
    mock_conn.__aenter__.return_value = mock_conn
    mock_conn.execute = AsyncMock()
    mock_engine = MagicMock()
    mock_engine.connect = MagicMock(return_value=mock_conn)

    with patch("cache.get_redis", side_effect=slow_get_redis), \
         patch("database.db.engine", mock_engine):

        t0 = time.perf_counter()
        response = await client.get("/health")
        elapsed = time.perf_counter() - t0

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["redis"] == "unavailable"
        assert data["database"] == "ok"
        assert elapsed < 3.2, f"get_redis hang took {elapsed}s; expected < 3.2s"
