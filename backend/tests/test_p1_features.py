# ============================================================
#  tests/test_p1_features.py  —  Phase P1 Regression Test Suite
#  - P1.1: Login Rate Limiting (Redis & in-memory fallback)
#  - P1.2: Password Policy (Complexity & Boundary Enforcement)
#  - P1.3: Bcrypt 72 UTF-8 bytes limit & Trusted Proxy IP Enforcement
# ============================================================

import time
import pytest
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock, MagicMock
from middleware.rate_limit import _reset_memory_rate_limits
from config import settings
from models.user import UserRole

pytestmark = pytest.mark.asyncio


# ─────────────────────────────────────────────────────────────
#  1. P1.1 — Login Rate Limiting Tests
# ─────────────────────────────────────────────────────────────

async def test_login_rate_limiting_enforced(client: AsyncClient):
    """
    Assert that repeated login attempts from the same IP are rate-limited after
    settings.LOGIN_RATE_LIMIT_PER_MINUTE (default 5) requests.
    """
    await _reset_memory_rate_limits()

    # 1. Register a valid user
    await client.post("/api/auth/register", json={
        "email": "rate_limit_test@example.com",
        "username": "ratelimittest",
        "full_name": "Rate Limit User",
        "password": "Password123",
        "role": "analyst",
    })

    # 2. Fire 5 failed attempts (or attempts within limit)
    for i in range(5):
        resp = await client.post("/api/auth/login", data={
            "username": "ratelimittest",
            "password": "WrongPassword999",
        })
        # Under limit: gets 401 Unauthorized, rate limit headers attached
        assert resp.status_code == 401
        assert "X-RateLimit-Limit" in resp.headers
        assert resp.headers["X-RateLimit-Limit"] == str(settings.LOGIN_RATE_LIMIT_PER_MINUTE)
        remaining = int(resp.headers["X-RateLimit-Remaining"])
        assert remaining == max(0, 5 - (i + 1))

    # 3. 6th attempt must be rejected with 429 Too Many Requests
    resp_blocked = await client.post("/api/auth/login", data={
        "username": "ratelimittest",
        "password": "WrongPassword999",
    })
    assert resp_blocked.status_code == 429
    assert resp_blocked.headers["X-RateLimit-Remaining"] == "0"
    data = resp_blocked.json()
    assert "Too many login attempts" in data["detail"]
    assert "retry_after" in data


async def test_login_rate_limit_resets_after_window(client: AsyncClient):
    """
    Assert that after the rate limiting sliding window expires, requests are allowed again.
    """
    await _reset_memory_rate_limits()

    # Register user
    await client.post("/api/auth/register", json={
        "email": "expiry_test@example.com",
        "username": "expiryuser",
        "full_name": "Expiry User",
        "password": "Password123",
        "role": "analyst",
    })

    # Simulate 5 attempts at time T0
    for _ in range(5):
        resp = await client.post("/api/auth/login", data={
            "username": "expiryuser",
            "password": "WrongPassword999",
        })
        assert resp.status_code == 401

    # 6th attempt blocked
    resp_blocked = await client.post("/api/auth/login", data={
        "username": "expiryuser",
        "password": "WrongPassword999",
    })
    assert resp_blocked.status_code == 429

    # Reset memory window to simulate window expiry
    await _reset_memory_rate_limits()

    # Now the attempt should succeed (or return 401 rather than 429)
    resp_after = await client.post("/api/auth/login", data={
        "username": "expiryuser",
        "password": "Password123",
    })
    assert resp_after.status_code == 200


async def test_login_rate_limit_does_not_block_other_routes(client: AsyncClient):
    """
    Assert that exhausting the login rate limit does not block unrelated endpoints.
    """
    await _reset_memory_rate_limits()

    # Block login endpoint with 6 rapid requests
    for _ in range(6):
        await client.post("/api/auth/login", data={
            "username": "fakeuser",
            "password": "WrongPassword999",
        })

    # Root health endpoint must still be 200 OK
    resp_root = await client.get("/")
    assert resp_root.status_code == 200
    assert resp_root.json()["status"] == "running"

    # Health check endpoint must still be 200 OK
    resp_health = await client.get("/health")
    assert resp_health.status_code == 200


async def test_login_rate_limit_with_redis_backend(client: AsyncClient):
    """
    Assert that when Redis is available, Redis pipeline sorted-set is used correctly.
    """
    # Create mock async Redis client (pipeline() is synchronous in aioredis/redis.asyncio)
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_redis.pipeline.return_value = mock_pipe

    # Simulate results: [zremrangebyscore_count, zadd_count, zcard_count, expire_bool]
    # Here zcard count is 6 (which exceeds limit 5)
    mock_pipe.execute = AsyncMock(return_value=[0, 1, 6, True])

    with patch("cache.get_redis", AsyncMock(return_value=mock_redis)):
        resp = await client.post("/api/auth/login", data={
            "username": "anyuser",
            "password": "Password123",
        })
        assert resp.status_code == 429
        assert "Too many login attempts" in resp.json()["detail"]
        assert resp.headers["X-RateLimit-Remaining"] == "0"


# ─────────────────────────────────────────────────────────────
#  2. P1.2 & P1.3 — Password Policy Tests (Length & UTF-8 Bytes)
# ─────────────────────────────────────────────────────────────

async def test_password_policy_public_registration(client: AsyncClient):
    """Test validation errors for weak passwords on public registration."""
    # 1. Less than 8 characters
    resp_short = await client.post("/api/auth/register", json={
        "email": "p_short@example.com",
        "username": "pshort",
        "full_name": "P Short",
        "password": "Pass1",
    })
    assert resp_short.status_code == 400
    assert "at least 8 characters" in resp_short.json()["detail"]

    # 2. More than 128 characters
    resp_long = await client.post("/api/auth/register", json={
        "email": "p_long@example.com",
        "username": "plong",
        "full_name": "P Long",
        "password": "A1" + ("x" * 127),
    })
    assert resp_long.status_code == 400
    assert "cannot exceed 128 characters" in resp_long.json()["detail"]

    # 3. Missing letters (digits only)
    resp_digits = await client.post("/api/auth/register", json={
        "email": "p_digits@example.com",
        "username": "pdigits",
        "full_name": "P Digits",
        "password": "1234567890",
    })
    assert resp_digits.status_code == 400
    assert "at least one letter" in resp_digits.json()["detail"]

    # 4. Missing digits (letters only)
    resp_letters = await client.post("/api/auth/register", json={
        "email": "p_letters@example.com",
        "username": "pletters",
        "full_name": "P Letters",
        "password": "AllAlphabeticalOnly",
    })
    assert resp_letters.status_code == 400
    assert "at least one digit" in resp_letters.json()["detail"]

    # 5. Compliant password succeeds
    resp_valid = await client.post("/api/auth/register", json={
        "email": "p_valid@example.com",
        "username": "pvalid",
        "full_name": "P Valid",
        "password": "SecurePassword123",
    })
    assert resp_valid.status_code == 201
    assert resp_valid.json()["username"] == "pvalid"


async def test_password_policy_bcrypt_72_bytes_boundary(client: AsyncClient):
    """
    Test exact 72-byte limit, >72 ASCII, and multibyte Unicode exceeding 72 bytes.
    """
    # 1. Valid password below 72 bytes (e.g. 20 bytes)
    pw_normal = "ValidPassBelowLimit123"
    assert len(pw_normal.encode("utf-8")) == 22
    resp_normal = await client.post("/api/auth/register", json={
        "email": "p_normal@example.com",
        "username": "pnormal",
        "full_name": "Normal Pass",
        "password": pw_normal,
    })
    assert resp_normal.status_code == 201

    # 2. Exactly 72 UTF-8 bytes
    pw_72 = "A1" + ("x" * 70)
    assert len(pw_72.encode("utf-8")) == 72
    resp_72 = await client.post("/api/auth/register", json={
        "email": "p_exact72@example.com",
        "username": "pexact72",
        "full_name": "Exact 72 Bytes",
        "password": pw_72,
    })
    assert resp_72.status_code == 201
    assert resp_72.json()["username"] == "pexact72"

    # 3. ASCII password above 72 bytes (e.g. 73 bytes, <= 128 characters)
    pw_73 = "A1" + ("x" * 71)
    assert len(pw_73.encode("utf-8")) == 73
    resp_73 = await client.post("/api/auth/register", json={
        "email": "p_73bytes@example.com",
        "username": "p73bytes",
        "full_name": "73 Bytes",
        "password": pw_73,
    })
    assert resp_73.status_code == 400
    assert "cannot exceed 72 bytes" in resp_73.json()["detail"]

    # 4. Multibyte Unicode exceeding 72 bytes despite having fewer than 72 characters
    # 'A1' (2 bytes) + 18 emojis (18 * 4 = 72 bytes) = 74 bytes with only 20 characters
    pw_unicode = "A1" + ("🚀" * 18)
    assert len(pw_unicode) == 20
    assert len(pw_unicode.encode("utf-8")) == 74
    resp_unicode = await client.post("/api/auth/register", json={
        "email": "p_unicode@example.com",
        "username": "punicode",
        "full_name": "Unicode User",
        "password": pw_unicode,
    })
    assert resp_unicode.status_code == 400
    assert "cannot exceed 72 bytes" in resp_unicode.json()["detail"]


async def test_password_policy_admin_create_user(client: AsyncClient):
    """Test password policy is enforced identically on admin user creation."""
    from database.db import AsyncSessionLocal
    from services.auth_service import hash_password
    from models.user import User

    # 1. Create admin directly in database
    async with AsyncSessionLocal() as db:
        admin_user = User(
            email="admin_policy@example.com",
            username="admin_policy",
            full_name="Admin Policy",
            hashed_password=hash_password("AdminPass123"),
            role=UserRole.admin,
        )
        db.add(admin_user)
        await db.commit()

    # 2. Login admin
    login_resp = await client.post("/api/auth/login", data={
        "username": "admin_policy",
        "password": "AdminPass123",
    })
    assert login_resp.status_code == 200
    admin_token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 3. Admin attempts to create user with weak password (< 8 chars)
    resp_weak = await client.post("/api/auth/admin/create-user", json={
        "email": "subordinate@example.com",
        "username": "subordinate",
        "full_name": "Subordinate User",
        "password": "weak",
        "role": "analyst",
    }, headers=headers)
    assert resp_weak.status_code == 400
    assert "at least 8 characters" in resp_weak.json()["detail"]

    # 4. Admin attempts to create user with password > 72 UTF-8 bytes
    resp_too_many_bytes = await client.post("/api/auth/admin/create-user", json={
        "email": "subordinate2@example.com",
        "username": "subordinate2",
        "full_name": "Subordinate User 2",
        "password": "A1" + ("x" * 71),  # 73 bytes
        "role": "analyst",
    }, headers=headers)
    assert resp_too_many_bytes.status_code == 400
    assert "cannot exceed 72 bytes" in resp_too_many_bytes.json()["detail"]

    # 5. Admin creates user with valid password
    resp_good = await client.post("/api/auth/admin/create-user", json={
        "email": "subordinate@example.com",
        "username": "subordinate",
        "full_name": "Subordinate User",
        "password": "ValidPassword123",
        "role": "analyst",
    }, headers=headers)
    assert resp_good.status_code == 201
    assert resp_good.json()["username"] == "subordinate"


# ─────────────────────────────────────────────────────────────
#  3. P1.3 — Trusted Proxy Client IP Extraction Tests
# ─────────────────────────────────────────────────────────────

async def test_untrusted_peer_forged_x_forwarded_for_is_ignored(client: AsyncClient):
    """
    When TRUSTED_PROXIES is empty, an attacker sending X-Forwarded-For must NOT bypass rate limits.
    All attempts are rate-limited based on request.client.host (127.0.0.1 in tests).
    """
    await _reset_memory_rate_limits()

    with patch.object(settings, "TRUSTED_PROXIES", []):
        # Fire 5 attempts with spoofed rotating X-Forwarded-For headers
        for i in range(5):
            spoofed_ip = f"198.51.100.{i+1}"
            resp = await client.post("/api/auth/login", data={
                "username": "fakeuser",
                "password": "WrongPassword123",
            }, headers={"X-Forwarded-For": spoofed_ip})
            assert resp.status_code == 401

        # 6th attempt with another spoofed IP must be BLOCKED (429) because peer IP is 127.0.0.1
        resp_6 = await client.post("/api/auth/login", data={
            "username": "fakeuser",
            "password": "WrongPassword123",
        }, headers={"X-Forwarded-For": "198.51.100.99"})
        assert resp_6.status_code == 429
        assert "Too many login attempts" in resp_6.json()["detail"]


async def test_trusted_peer_honors_forwarded_for(client: AsyncClient):
    """
    When TRUSTED_PROXIES includes the connecting peer IP (127.0.0.1),
    the originating client IP from X-Forwarded-For is trusted.
    """
    await _reset_memory_rate_limits()

    with patch.object(settings, "TRUSTED_PROXIES", ["127.0.0.1"]):
        # Attacker 1 from 203.0.113.1 fires 5 attempts
        for _ in range(5):
            resp = await client.post("/api/auth/login", data={
                "username": "fakeuser",
                "password": "WrongPassword123",
            }, headers={"X-Forwarded-For": "203.0.113.1"})
            assert resp.status_code == 401

        # Attacker 1 6th attempt is blocked
        resp_blocked = await client.post("/api/auth/login", data={
            "username": "fakeuser",
            "password": "WrongPassword123",
        }, headers={"X-Forwarded-For": "203.0.113.1"})
        assert resp_blocked.status_code == 429

        # Legitimate User from distinct IP 203.0.113.2 forwarded through the same proxy is NOT blocked
        resp_other = await client.post("/api/auth/login", data={
            "username": "fakeuser",
            "password": "WrongPassword123",
        }, headers={"X-Forwarded-For": "203.0.113.2"})
        assert resp_other.status_code == 401


async def test_trusted_peer_multiple_forwarded_addresses(client: AsyncClient):
    """
    When X-Forwarded-For contains a chain (e.g. client, proxy1, proxy2),
    the leftmost IP is parsed as the original client.
    """
    await _reset_memory_rate_limits()

    with patch.object(settings, "TRUSTED_PROXIES", ["127.0.0.1"]):
        chain = "192.0.2.50, 10.0.0.1, 172.16.0.1"
        for _ in range(5):
            resp = await client.post("/api/auth/login", data={
                "username": "fakeuser",
                "password": "WrongPassword123",
            }, headers={"X-Forwarded-For": chain})
            assert resp.status_code == 401

        # 6th attempt from same chain is blocked
        resp_blocked = await client.post("/api/auth/login", data={
            "username": "fakeuser",
            "password": "WrongPassword123",
        }, headers={"X-Forwarded-For": chain})
        assert resp_blocked.status_code == 429


async def test_invalid_trusted_proxy_configuration():
    """
    Confirm that an invalid IP or CIDR network in TRUSTED_PROXIES fails validation
    rather than silently accepting all or nothing.
    """
    from config import Settings
    with pytest.raises(ValueError, match="Invalid trusted proxy IP/network"):
        Settings(
            DATABASE_URL="sqlite+aiosqlite:///./test.db",
            SECRET_KEY="test-secret",
            REDIS_URL="redis://localhost:6379/0",
            TRUSTED_PROXIES=["invalid-ip-string-12345"]
        )
