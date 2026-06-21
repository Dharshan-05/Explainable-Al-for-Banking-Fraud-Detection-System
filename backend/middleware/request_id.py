import uuid
import string
from contextvars import ContextVar
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

REQUEST_ID_VAR = ContextVar("request_id", default=None)

def get_request_id() -> str | None:
    """Retrieve the current request correlation ID from context variables."""
    return REQUEST_ID_VAR.get()

def is_safe_request_id(req_id: str) -> bool:
    """
    Validates request ID. Must be <= 64 chars, and contain only alphanumeric,
    dashes, and underscores (no newlines/control characters).
    """
    if not req_id or len(req_id) > 64:
        return False
    allowed = set(string.ascii_letters + string.digits + "-_")
    return all(c in allowed for c in req_id)

class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware that extracts or generates a unique correlation ID (X-Request-ID)
    for every incoming HTTP request, stores it in context variables for logging,
    and returns it in the response headers. WebSockets are safely bypassed.
    """
    async def dispatch(self, request: Request, call_next):
        # Safely bypass non-HTTP requests (like WebSockets) to not interfere with upgrade
        if request.scope.get("type") != "http":
            return await call_next(request)

        # Accept X-Request-ID if present and safe, otherwise generate a fresh UUID
        request_id = request.headers.get("X-Request-ID") or request.headers.get("x-request-id")
        if not request_id or not is_safe_request_id(request_id):
            request_id = str(uuid.uuid4())

        token = REQUEST_ID_VAR.set(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            # Reset context variables after every request
            REQUEST_ID_VAR.reset(token)
