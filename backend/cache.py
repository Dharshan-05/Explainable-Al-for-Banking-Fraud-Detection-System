# ============================================================
#  cache.py  —  Redis Async Wrapper
# ============================================================

import json
from typing import Any, Optional
import redis.asyncio as aioredis
from config import settings

_redis_client: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    """FastAPI dependency — returns a shared async Redis client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def cache_get(key: str) -> Optional[Any]:
    """Return deserialized value from cache, or None if missing."""
    try:
        client = await get_redis()
        raw = await client.get(key)
        return json.loads(raw) if raw is not None else None
    except Exception:
        return None


async def cache_set(key: str, value: Any, ttl_seconds: int = 60) -> None:
    """Serialize and store a value in Redis with a TTL."""
    try:
        client = await get_redis()
        await client.setex(key, ttl_seconds, json.dumps(value))
    except Exception:
        pass  # Cache failures are non-fatal


async def cache_delete(key: str) -> None:
    """Invalidate a single cache key."""
    try:
        client = await get_redis()
        await client.delete(key)
    except Exception:
        pass


async def close_redis() -> None:
    """Gracefully close the Redis connection."""
    global _redis_client
    if _redis_client:
        try:
            await _redis_client.close()
        except Exception:
            pass
        finally:
            _redis_client = None
