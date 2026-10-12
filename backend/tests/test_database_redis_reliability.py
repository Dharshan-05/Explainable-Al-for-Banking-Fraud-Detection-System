# ============================================================
#  test_database_redis_reliability.py — P2.2A Reliability Tests
# ============================================================

import os
import time
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

from cache import (
    cache_get,
    cache_set,
    cache_delete,
    clear_in_memory_cache,
    close_redis,
    get_redis,
    _in_memory_cache,
    MAX_IN_MEMORY_CACHE_ITEMS,
)
from database.db import engine, db_url, engine_kwargs, connect_args
from main import lifespan
from fastapi import FastAPI


class TestDatabasePoolAndLifespan:
    def test_database_engine_kwargs(self):
        """Verify engine kwargs include pool_pre_ping and appropriate pool limits."""
        assert engine_kwargs["pool_pre_ping"] is True
        if not db_url.startswith("sqlite"):
            assert engine_kwargs["pool_size"] == 5
            assert engine_kwargs["max_overflow"] == 10
            assert engine_kwargs["pool_recycle"] == 1800
            assert engine_kwargs["pool_timeout"] == 30.0

    def test_connect_args_configuration(self):
        """Verify connect_args configurations are present."""
        if db_url.startswith("postgresql"):
            assert connect_args.get("ssl") is False
            assert connect_args.get("command_timeout") == 30.0

    @pytest.mark.anyio
    async def test_fastapi_lifespan_disposes_resources(self):
        """Verify lifespan context manager gracefully closes Redis and disposes the database engine."""
        app = FastAPI()
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        with patch("database.db.engine", mock_engine), \
             patch("cache.close_redis", new_callable=AsyncMock) as mock_close_redis:
            async with lifespan(app):
                pass
            mock_close_redis.assert_awaited_once()
            mock_engine.dispose.assert_awaited_once()

    @pytest.mark.anyio
    async def test_fastapi_lifespan_isolated_cleanup_on_error(self):
        """Verify engine disposal still proceeds even if close_redis raises an exception."""
        app = FastAPI()
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        with patch("database.db.engine", mock_engine), \
             patch("cache.close_redis", side_effect=RuntimeError("Redis connection failure")):
            async with lifespan(app):
                pass
            mock_engine.dispose.assert_awaited_once()


class TestRedisAndInMemoryCacheReliability:
    @pytest.mark.anyio
    async def test_redis_connection_options_configured(self):
        """Verify get_redis configures socket timeouts and bounded pool."""
        client = await get_redis()
        conn_kwargs = client.connection_pool.connection_kwargs
        assert conn_kwargs.get("socket_connect_timeout") == 3.0
        assert conn_kwargs.get("socket_timeout") == 3.0
        assert conn_kwargs.get("health_check_interval") == 30
        assert conn_kwargs.get("retry_on_timeout") is True
        assert client.connection_pool.max_connections == 20

    @pytest.mark.anyio
    async def test_in_memory_cache_ttl_expiration(self):
        """Verify in-memory fallback cache respects TTL expiration."""
        clear_in_memory_cache()
        # Redis is disabled in tests via mock_redis_cache fixture
        await cache_set("test_key_ttl", {"foo": "bar"}, ttl_seconds=1)
        res = await cache_get("test_key_ttl")
        assert res == {"foo": "bar"}

        # Simulate time passing beyond TTL
        raw, exp = _in_memory_cache["test_key_ttl"]
        _in_memory_cache["test_key_ttl"] = (raw, time.time() - 10)

        res_expired = await cache_get("test_key_ttl")
        assert res_expired is None
        assert "test_key_ttl" not in _in_memory_cache

    @pytest.mark.anyio
    async def test_in_memory_cache_bounded_max_items(self):
        """Verify in-memory fallback cache does not grow unboundedly beyond MAX_IN_MEMORY_CACHE_ITEMS."""
        clear_in_memory_cache()
        # Insert 1050 items into fallback store
        for i in range(1050):
            await cache_set(f"k_{i}", i, ttl_seconds=60)

        assert len(_in_memory_cache) == MAX_IN_MEMORY_CACHE_ITEMS
        # Oldest items (k_0 .. k_49) must have been evicted
        assert "k_0" not in _in_memory_cache
        assert "k_49" not in _in_memory_cache
        # Newer items must remain
        assert "k_1049" in _in_memory_cache
        clear_in_memory_cache()
