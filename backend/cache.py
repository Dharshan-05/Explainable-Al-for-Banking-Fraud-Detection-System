# ============================================================
#  cache.py  —  Redis Async Wrapper
# ============================================================

import json
from typing import Any, Optional
import redis.asyncio as aioredis
from config import settings

from collections import OrderedDict
import time

_redis_client: Optional[aioredis.Redis] = None

# Bounded process-memory cache (volatile fallback when Redis is unreachable; not durable storage)
MAX_IN_MEMORY_CACHE_ITEMS = 1000
_in_memory_cache: OrderedDict[str, tuple[str, float]] = OrderedDict()


async def get_redis() -> aioredis.Redis:
    """FastAPI dependency — returns a shared async Redis client with bounded pooling and timeouts."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=3.0,
            socket_timeout=3.0,
            health_check_interval=30,
            retry_on_timeout=True,
            max_connections=20,
        )
    return _redis_client


def _purge_expired_in_memory(now: float) -> None:
    """Purge expired entries from the in-memory fallback cache."""
    expired_keys = [k for k, (_, exp) in _in_memory_cache.items() if exp <= now]
    for k in expired_keys:
        _in_memory_cache.pop(k, None)


async def cache_get(key: str) -> Optional[Any]:
    """Return deserialized value from cache, or in-memory fallback if Redis is unavailable, or None if missing."""
    try:
        client = await get_redis()
        raw = await client.get(key)
        return json.loads(raw) if raw is not None else None
    except Exception:
        # Fallback to local in-memory cache (e.g. for testing or transient Redis downtime)
        now = time.time()
        item = _in_memory_cache.get(key)
        if item is not None:
            raw, expiry = item
            if now < expiry:
                _in_memory_cache.move_to_end(key)
                return json.loads(raw)
            else:
                _in_memory_cache.pop(key, None)
        return None


async def cache_set(key: str, value: Any, ttl_seconds: int = 60) -> None:
    """Serialize and store a value in Redis with a TTL, falling back to bounded in-memory store if Redis is unavailable."""
    serialized = json.dumps(value)
    try:
        client = await get_redis()
        await client.setex(key, ttl_seconds, serialized)
    except Exception:
        # Fallback to bounded process-memory store
        now = time.time()
        _purge_expired_in_memory(now)
        if key in _in_memory_cache:
            _in_memory_cache.move_to_end(key)
        _in_memory_cache[key] = (serialized, now + ttl_seconds)
        # Enforce maximum entries bound with FIFO/LRU eviction
        while len(_in_memory_cache) > MAX_IN_MEMORY_CACHE_ITEMS:
            _in_memory_cache.popitem(last=False)


async def cache_delete(key: str) -> None:
    """Invalidate a single cache key."""
    _in_memory_cache.pop(key, None)
    try:
        client = await get_redis()
        await client.delete(key)
    except Exception:
        pass


def clear_in_memory_cache() -> None:
    """Testing helper to purge in-memory cache."""
    _in_memory_cache.clear()


async def close_redis() -> None:
    """Gracefully close the Redis connection pool."""
    global _redis_client
    if _redis_client:
        try:
            if hasattr(_redis_client, "aclose"):
                await _redis_client.aclose()
            else:
                await _redis_client.close()
        except Exception:
            pass
        finally:
            _redis_client = None
