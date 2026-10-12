import pytest
import pytest_asyncio
from httpx import AsyncClient
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect
from main import app
from models.user import UserRole

@pytest.mark.asyncio
async def test_rbac_customer_blocked_from_internal_apis(client: AsyncClient):
    # 1. Register customer
    await client.post("/api/auth/register", json={
        "email":     "customer@example.com",
        "username":  "customeruser",
        "full_name": "Customer User",
        "password":  "Customer123",
        "role":      "customer",
    })
    
    # 2. Login customer
    login_resp = await client.post("/api/auth/login", data={
        "username": "customeruser",
        "password": "Customer123",
    })
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # 3. Access transactions feed (should be 403)
    resp = await client.get("/api/transactions", headers=headers)
    assert resp.status_code == 403
    assert "required permissions" in resp.json()["detail"]

    # 4. Access flagged (should be 403)
    resp = await client.get("/api/transactions/flagged", headers=headers)
    assert resp.status_code == 403

    # 5. Access analytics stats (should be 403)
    resp = await client.get("/api/analytics/stats", headers=headers)
    assert resp.status_code == 403

@pytest.mark.asyncio
async def test_rbac_analyst_allowed_internal_apis(client: AsyncClient):
    # 1. Register analyst
    await client.post("/api/auth/register", json={
        "email":     "analyst@example.com",
        "username":  "analystuser",
        "full_name": "Analyst User",
        "password":  "Analyst123",
        "role":      "analyst",
    })
    
    # 2. Login analyst
    login_resp = await client.post("/api/auth/login", data={
        "username": "analystuser",
        "password": "Analyst123",
    })
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # 3. Access transactions feed (should be 200)
    resp = await client.get("/api/transactions", headers=headers)
    assert resp.status_code == 200

    # 4. Access analytics stats (should be 200)
    resp = await client.get("/api/analytics/stats", headers=headers)
    assert resp.status_code == 200


def test_websocket_security_matrix():
    with TestClient(app) as client:
        # 1. Connect without token cookie (closed with 4001)
        try:
            with client.websocket_connect("/api/ws/alerts") as ws:
                pass
        except WebSocketDisconnect as e:
            assert e.code == 4001

        # 2. Connect with invalid cookie token (closed with 4001)
        client.cookies.set("access_token", "invalidjwt")
        try:
            with client.websocket_connect("/api/ws/alerts") as ws:
                pass
        except WebSocketDisconnect as e:
            assert e.code == 4001

        # Clear cookies
        client.cookies.clear()

        # 3. Register and Login a Customer
        client.post("/api/auth/register", json={
            "email":     "wscustomer@example.com",
            "username":  "wscustomer",
            "full_name": "WS Customer",
            "password":  "wspass123",
            "role":      "customer",
        })
        client.post("/api/auth/login", data={"username": "wscustomer", "password": "wspass123"})
        # Customer cookie is set automatically in client.cookies

        # 4. Connect with Customer cookie (closed with 4003)
        try:
            with client.websocket_connect("/api/ws/alerts") as ws:
                pass
        except WebSocketDisconnect as e:
            assert e.code == 4003

        # 5. Register and Login an Analyst
        client.post("/api/auth/register", json={
            "email":     "wsanalyst@example.com",
            "username":  "wsanalyst",
            "full_name": "WS Analyst",
            "password":  "wspass123",
            "role":      "analyst",
        })
        client.post("/api/auth/login", data={"username": "wsanalyst", "password": "wspass123"})
        # Analyst cookie is set automatically in client.cookies

        # 6. Connect with Analyst cookie (connects successfully, receives welcome payload)
        with client.websocket_connect("/api/ws/alerts") as ws:
            data = ws.receive_json()
            assert data["type"] == "connected"
            assert data["user"] == "wsanalyst"

        # 7. Register and Login Staff (rejected with 4003)
        client.post("/api/auth/register", json={
            "email":     "wsstaff@example.com",
            "username":  "wsstaff",
            "full_name": "WS Staff",
            "password":  "wspass123",
            "role":      "staff",
        })
        client.post("/api/auth/login", data={"username": "wsstaff", "password": "wspass123"})
        try:
            with client.websocket_connect("/api/ws/alerts") as ws:
                pass
        except WebSocketDisconnect as e:
            assert e.code == 4003

        # 8. Create and Login Fraud Analyst (connects successfully)
        from database.db import AsyncSessionLocal
        from services.auth_service import hash_password
        from models.user import User
        import asyncio

        async def _create_fa():
            async with AsyncSessionLocal() as db:
                fa = User(
                    email="wsfa@example.com",
                    username="wsfa",
                    full_name="WS Fraud Analyst",
                    hashed_password=hash_password("wspass123"),
                    role=UserRole.fraud_analyst
                )
                db.add(fa)
                await db.commit()

        asyncio.run(_create_fa())

        client.post("/api/auth/login", data={"username": "wsfa", "password": "wspass123"})
        with client.websocket_connect("/api/ws/alerts") as ws:
            data = ws.receive_json()
            assert data["type"] == "connected"
            assert data["user"] == "wsfa"

@pytest.mark.asyncio
async def test_auth_invalid_jwt_signature(client: AsyncClient):
    headers = {"Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.invalidpayload.invalidsignature"}
    resp = await client.get("/api/transactions", headers=headers)
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Could not validate credentials"

@pytest.mark.asyncio
async def test_cookie_auth_and_csrf_flow(client: AsyncClient):
    # 1. Register a test analyst
    await client.post("/api/auth/register", json={
        "email":     "testcookie@example.com",
        "username":  "testcookie",
        "full_name": "Test Cookie User",
        "password":  "testpass123",
        "role":      "analyst",
    })

    # 2. Login to get cookies
    login_resp = await client.post("/api/auth/login", data={
        "username": "testcookie",
        "password": "testpass123",
    })
    assert login_resp.status_code == 200
    
    # Assert login sets cookies
    access_token_cookie = login_resp.cookies.get("access_token")
    csrf_token_cookie = login_resp.cookies.get("csrf_token")
    assert access_token_cookie is not None
    assert csrf_token_cookie is not None

    # Create a clean client without cookies to test various auth methods manually
    from httpx import AsyncClient, ASGITransport
    from tests.test_predict import VALID_LEGIT

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as clean_client:
        # 3. GET /api/auth/me with missing cookie -> 401
        me_resp = await clean_client.get("/api/auth/me")
        assert me_resp.status_code == 401

        # 4. GET /api/auth/me with invalid cookie token -> 401
        clean_client.cookies.set("access_token", "invalidtoken")
        me_resp = await clean_client.get("/api/auth/me")
        assert me_resp.status_code == 401
        clean_client.cookies.clear()

        # 5. GET /api/auth/me with valid cookie -> 200
        clean_client.cookies.set("access_token", access_token_cookie)
        me_resp = await clean_client.get("/api/auth/me")
        assert me_resp.status_code == 200
        assert me_resp.json()["username"] == "testcookie"

        # 6. Safe GET route with cookie does not require CSRF
        tx_resp = await clean_client.get("/api/transactions")
        assert tx_resp.status_code == 200

        # 7. Unsafe mutating POST request using cookie without CSRF header -> 403
        pred_resp = await clean_client.post("/api/predict/transaction", json=VALID_LEGIT)
        assert pred_resp.status_code == 403
        assert "CSRF token validation failed" in pred_resp.json()["detail"]

        # 8. Unsafe mutating POST request using cookie with invalid CSRF header -> 403
        pred_resp = await clean_client.post(
            "/api/predict/transaction", 
            json=VALID_LEGIT,
            headers={"X-CSRF-Token": "wrong-csrf-token"}
        )
        assert pred_resp.status_code == 403

        # 9. Unsafe mutating POST request using cookie with valid CSRF header -> 200
        clean_client.cookies.set("csrf_token", csrf_token_cookie)
        pred_resp = await clean_client.post(
            "/api/predict/transaction", 
            json=VALID_LEGIT,
            headers={"X-CSRF-Token": csrf_token_cookie}
        )
        assert pred_resp.status_code == 200

        # 10. Unsafe mutating POST request using Bearer auth (fallback) does not require CSRF
        clean_client.cookies.clear()
        pred_resp = await clean_client.post(
            "/api/predict/transaction", 
            json=VALID_LEGIT,
            headers={"Authorization": f"Bearer {access_token_cookie}"}
        )
        assert pred_resp.status_code == 200

        # 11. Logout cleans up cookies
        clean_client.cookies.set("access_token", access_token_cookie)
        clean_client.cookies.set("csrf_token", csrf_token_cookie)
        logout_resp = await clean_client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token_cookie})
        assert logout_resp.status_code == 200
        
        # Verify the backend responded with Set-Cookie instructions to clear the cookies
        set_cookies = logout_resp.headers.get_list("set-cookie")
        assert any("access_token=" in c for c in set_cookies)
        assert any("csrf_token=" in c for c in set_cookies)
