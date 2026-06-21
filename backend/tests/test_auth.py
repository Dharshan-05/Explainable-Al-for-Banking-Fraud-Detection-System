# ============================================================
#  tests/test_auth.py  —  Authentication Route Tests
# ============================================================

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestRegister:
    async def test_register_success(self, client: AsyncClient):
        resp = await client.post("/api/auth/register", json={
            "email":     "alice@example.com",
            "username":  "alice",
            "full_name": "Alice Smith",
            "password":  "securepass",
            "role":      "analyst",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == "alice@example.com"
        assert data["username"] == "alice"
        assert data["is_active"] is True

    async def test_register_duplicate_email(self, client: AsyncClient):
        payload = {
            "email":     "dup@example.com",
            "username":  "dup1",
            "full_name": "Dup User",
            "password":  "pass",
        }
        await client.post("/api/auth/register", json=payload)
        payload["username"] = "dup2"  # change username, same email
        resp = await client.post("/api/auth/register", json=payload)
        assert resp.status_code == 400
        assert "Email already registered" in resp.json()["detail"]

    async def test_register_duplicate_username(self, client: AsyncClient):
        payload = {
            "email":     "user1@example.com",
            "username":  "sameuser",
            "full_name": "User One",
            "password":  "pass",
        }
        await client.post("/api/auth/register", json=payload)
        payload["email"] = "user2@example.com"  # change email, same username
        resp = await client.post("/api/auth/register", json=payload)
        assert resp.status_code == 400
        assert "Username already taken" in resp.json()["detail"]


class TestLogin:
    async def test_login_success(self, client: AsyncClient):
        await client.post("/api/auth/register", json={
            "email":     "bob@example.com",
            "username":  "bob",
            "full_name": "Bob Jones",
            "password":  "mypassword",
        })
        resp = await client.post("/api/auth/login", data={
            "username": "bob",
            "password": "mypassword",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["username"] == "bob"

    async def test_login_wrong_password(self, client: AsyncClient):
        await client.post("/api/auth/register", json={
            "email":     "charlie@example.com",
            "username":  "charlie",
            "full_name": "Charlie Brown",
            "password":  "correctpass",
        })
        resp = await client.post("/api/auth/login", data={
            "username": "charlie",
            "password": "wrongpass",
        })
        assert resp.status_code == 401

    async def test_login_unknown_user(self, client: AsyncClient):
        resp = await client.post("/api/auth/login", data={
            "username": "nobody",
            "password": "pass",
        })
        assert resp.status_code == 401

    async def test_get_me(self, client: AsyncClient, auth_headers: dict):
        resp = await client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["username"] == "testuser"

    async def test_get_me_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 401
