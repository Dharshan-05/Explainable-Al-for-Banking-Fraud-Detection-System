# ============================================================
#  api/routes/ws.py  —  WebSocket Live Alerts
#  GET /api/ws/alerts  (WebSocket endpoint)
# ============================================================

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import List
import json

router = APIRouter()


# ─────────────────────────────────────────
#  Connection Manager (singleton)
# ─────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """Send a JSON message to ALL connected clients."""
        dead = []
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except Exception:
                dead.append(connection)
        for d in dead:
            self.disconnect(d)

    async def send_personal(self, message: dict, websocket: WebSocket):
        try:
            await websocket.send_text(json.dumps(message))
        except Exception:
            self.disconnect(websocket)


# Global singleton — imported by predict.py to broadcast alerts
manager = ConnectionManager()


# ─────────────────────────────────────────
#  WebSocket endpoint
# ─────────────────────────────────────────
@router.websocket("/alerts")
async def websocket_alerts(
    websocket: WebSocket,
):
    """
    WebSocket endpoint for real-time fraud alerts.
    Clients connect with: ws://localhost:8000/api/ws/alerts
    """
    from config import settings
    from services.audit_service import log_audit_event

    ip_addr = websocket.client.host if websocket.client else None
    user_agent = websocket.headers.get("user-agent") or websocket.headers.get("User-Agent")

    token = websocket.cookies.get(settings.COOKIE_NAME)

    if not token or token.strip() == "":
        await log_audit_event(
            action="websocket_connect_rejected",
            resource_type="websocket",
            status="failure",
            ip_address=ip_addr,
            user_agent=user_agent,
            metadata={"error_category": "TokenMissing"},
        )
        await websocket.accept()
        await websocket.close(code=4001, reason="Token required")
        return

    try:
        from api.deps import authenticate_ws_token
        from database.db import AsyncSessionLocal
        from models.user import UserRole

        async with AsyncSessionLocal() as db:
            user = await authenticate_ws_token(token, db)
            if user.role not in [UserRole.admin, UserRole.analyst]:
                await log_audit_event(
                    action="websocket_rbac_rejected",
                    resource_type="websocket",
                    status="failure",
                    actor_user_id=user.id,
                    actor_role=user.role.value if hasattr(user.role, "value") else str(user.role),
                    ip_address=ip_addr,
                    user_agent=user_agent,
                    metadata={"error_category": "RoleUnauthorized"},
                    db=db
                )
                await websocket.accept()
                await websocket.close(code=4003, reason="Unauthorized role")
                return
    except ValueError as e:
        await log_audit_event(
            action="websocket_connect_rejected",
            resource_type="websocket",
            status="failure",
            ip_address=ip_addr,
            user_agent=user_agent,
            metadata={"error_category": "AuthenticationError", "error_detail": str(e)},
        )
        await websocket.accept()
        await websocket.close(code=4001, reason=str(e))
        return
    except Exception as e:
        await log_audit_event(
            action="websocket_connect_rejected",
            resource_type="websocket",
            status="failure",
            ip_address=ip_addr,
            user_agent=user_agent,
            metadata={"error_category": "InvalidToken", "error_detail": str(e)},
        )
        await websocket.accept()
        await websocket.close(code=4001, reason="Invalid token")
        return

    # Connection approved: log success
    async with AsyncSessionLocal() as db:
        await log_audit_event(
            action="websocket_connect_success",
            resource_type="websocket",
            status="success",
            actor_user_id=user.id,
            actor_role=user.role.value if hasattr(user.role, "value") else str(user.role),
            ip_address=ip_addr,
            user_agent=user_agent,
            db=db
        )

    await manager.connect(websocket)
    # Send a welcome ping
    await manager.send_personal(
        {"type": "connected", "message": "🔌 Live fraud alerts connected", "user": user.username},
        websocket,
    )

    try:
        while True:
            # Keep the connection alive by listening for pings from client
            data = await websocket.receive_text()
            if data == "ping":
                await manager.send_personal({"type": "pong"}, websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
