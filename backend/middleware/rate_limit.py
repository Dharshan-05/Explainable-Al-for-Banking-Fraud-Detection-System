# ============================================================
#  middleware/rate_limit.py  —  Sliding Window Rate Limiter
#  Uses Redis to enforce 60 req/min per authenticated user.
#  Unauthenticated requests are rate-limited by IP.
# ============================================================

import time
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from config import settings


# Only apply rate limiting to these path prefixes
RATE_LIMITED_PREFIXES = ("/api/predict",)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Only rate-limit prediction endpoints
        if not any(request.url.path.startswith(p) for p in RATE_LIMITED_PREFIXES):
            return await call_next(request)

        try:
            from cache import get_redis
            redis = await get_redis()

            # Identify the caller — prefer JWT sub, fall back to IP
            identifier = _extract_identifier(request)
            key = f"rate_limit:{identifier}"
            now = int(time.time())
            window_start = now - 60  # 1-minute sliding window

            # Redis sorted-set sliding window
            pipe = redis.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)       # drop old entries
            pipe.zadd(key, {str(now) + ":" + str(time.time_ns()): now})  # add current
            pipe.zcard(key)                                   # count in window
            pipe.expire(key, 65)                              # auto-expire set
            results = await pipe.execute()

            request_count = results[2]
            limit = settings.RATE_LIMIT_PER_MINUTE

            # Attach rate-limit headers (always)
            remaining = max(0, limit - request_count)
            headers = {
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(now + 60),
            }

            if request_count > limit:
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": f"Rate limit exceeded. Max {limit} requests/minute. Try again in 60 seconds.",
                        "retry_after": 60,
                    },
                    headers=headers,
                )

        except Exception:
            # If Redis is unavailable, allow the request through (fail open)
            pass

        response = await call_next(request)
        return response


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
    # Fall back to IP
    forwarded_for = request.headers.get("X-Forwarded-For")
    ip = forwarded_for.split(",")[0].strip() if forwarded_for else request.client.host
    return f"ip:{ip}"
