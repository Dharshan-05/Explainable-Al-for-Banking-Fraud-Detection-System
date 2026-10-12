# ============================================================
#  middleware/rate_limit.py  —  Sliding Window Rate Limiter
#  - Predictions: 60 req/min per user (or IP)
#  - Login endpoint: 5 attempts/min per IP with in-memory fallback
# ============================================================

import time
import asyncio
from collections import defaultdict
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from config import settings

# Prediction rate limiting
PREDICT_PATH_PREFIXES = ("/api/predict",)

# Login rate limiting path
LOGIN_PATH = "/api/auth/login"

# ─────────────────────────────────────────────────────────────
# In-memory sliding-window fallback store (used if Redis is offline)
# Thread/async safe within a single process via asyncio lock
# ─────────────────────────────────────────────────────────────
_memory_lock = asyncio.Lock()
_memory_windows: dict[str, list[float]] = defaultdict(list)


async def _check_memory_rate_limit(key: str, limit: int, window_seconds: int) -> tuple[int, int, int]:
    """
    In-memory fallback rate limiter using sliding timestamp window.
    Returns: (request_count, remaining, reset_timestamp)
    """
    now = time.time()
    window_start = now - window_seconds
    async with _memory_lock:
        timestamps = _memory_windows[key]
        # Purge entries outside window
        valid = [t for t in timestamps if t > window_start]
        valid.append(now)
        _memory_windows[key] = valid
        count = len(valid)

    remaining = max(0, limit - count)
    reset = int(now + window_seconds)
    return count, remaining, reset


async def _reset_memory_rate_limits():
    """Testing helper to clear in-memory rate limiting state."""
    async with _memory_lock:
        _memory_windows.clear()


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Case 1: Login endpoint rate limiting
        if path == LOGIN_PATH and request.method.upper() == "POST":
            return await self._handle_login_rate_limit(request, call_next)

        # Case 2: Prediction endpoints rate limiting
        if any(path.startswith(p) for p in PREDICT_PATH_PREFIXES):
            return await self._handle_predict_rate_limit(request, call_next)

        # All other routes pass through without rate limiting
        return await call_next(request)

    async def _handle_login_rate_limit(self, request: Request, call_next):
        """
        Enforce strict rate limits on POST /api/auth/login.
        Keyed by client IP to block brute-force attacks.
        Uses Redis when available, with in-memory fallback when Redis is unavailable.
        """
        limit = settings.LOGIN_RATE_LIMIT_PER_MINUTE
        window = settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS
        ip = _extract_ip(request)
        key = f"rate_limit:login:ip:{ip}"
        now = int(time.time())

        request_count = None
        remaining = 0
        reset = now + window

        # Try Redis first
        try:
            from cache import get_redis
            redis = await get_redis()
            window_start = now - window

            pipe = redis.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zadd(key, {f"{now}:{time.time_ns()}": now})
            pipe.zcard(key)
            pipe.expire(key, window + 5)
            results = await pipe.execute()

            request_count = results[2]
            remaining = max(0, limit - request_count)
            reset = now + window
        except Exception:
            # Redis is unavailable: use in-memory sliding window fallback
            request_count, remaining, reset = await _check_memory_rate_limit(key, limit, window)

        headers = {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset),
        }

        if request_count is not None and request_count > limit:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": f"Too many login attempts. Max {limit} attempts per minute. Try again in {window} seconds.",
                    "retry_after": window,
                },
                headers=headers,
            )

        response = await call_next(request)
        # Attach rate limit headers to response
        for k, v in headers.items():
            response.headers[k] = v
        return response

    async def _handle_predict_rate_limit(self, request: Request, call_next):
        """Handle prediction endpoints (60 req/min per user or IP)."""
        limit = settings.RATE_LIMIT_PER_MINUTE
        window = 60
        now = int(time.time())

        headers = {}
        try:
            from cache import get_redis
            redis = await get_redis()

            identifier = _extract_identifier(request)
            key = f"rate_limit:{identifier}"
            window_start = now - window

            pipe = redis.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zadd(key, {f"{now}:{time.time_ns()}": now})
            pipe.zcard(key)
            pipe.expire(key, window + 5)
            results = await pipe.execute()

            request_count = results[2]
            remaining = max(0, limit - request_count)
            headers = {
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(now + window),
            }

            if request_count > limit:
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": f"Rate limit exceeded. Max {limit} requests/minute. Try again in {window} seconds.",
                        "retry_after": window,
                    },
                    headers=headers,
                )
        except Exception:
            # Prediction rate limit fails open if Redis is down
            pass

        response = await call_next(request)
        for k, v in headers.items():
            response.headers[k] = v
        return response


def _is_trusted_proxy(peer_ip: str) -> bool:
    """Check if the connecting peer IP matches any configured trusted proxy or network."""
    if not settings.TRUSTED_PROXIES or not peer_ip:
        return False
    import ipaddress
    try:
        peer_addr = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False

    for proxy_pattern in settings.TRUSTED_PROXIES:
        try:
            network = ipaddress.ip_network(proxy_pattern, strict=False)
            if peer_addr in network:
                return True
        except ValueError:
            continue
    return False


def _extract_ip(request: Request) -> str:
    """
    Extract client IP for rate limiting.
    - If connecting peer is not a trusted proxy, always use request.client.host directly.
    - If connecting peer is an explicitly configured trusted proxy, parse X-Forwarded-For:
      The leftmost valid IP in X-Forwarded-For represents the original client.
    """
    peer_ip = request.client.host if request.client else None
    if not peer_ip:
        return "unknown"

    if _is_trusted_proxy(peer_ip):
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # First IP in X-Forwarded-For chain is the originating client IP
            origin_ip = forwarded_for.split(",")[0].strip()
            if origin_ip:
                return origin_ip

    return peer_ip


def _extract_identifier(request: Request) -> str:
    """Extract a unique identifier: JWT sub (user id) or client IP."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        try:
            from jose import jwt
            from config import settings as s
            payload = jwt.decode(token, s.SECRET_KEY, algorithms=[s.ALGORITHM])
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except Exception:
            pass
    return f"ip:{_extract_ip(request)}"
