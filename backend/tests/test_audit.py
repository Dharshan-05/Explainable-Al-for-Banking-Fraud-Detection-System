# ============================================================
#  tests/test_audit.py  —  Audit Logging and Query Tests
# ============================================================

import pytest
import uuid
import json
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from main import app
from models.user import User, UserRole
from models.audit_log import AuditLog
from services.audit_service import log_audit_event, redact_sensitive_values, sanitize_metadata
from database.db import AsyncSessionLocal
from sqlalchemy import select


# ─────────────────────────────────────────────────────────
#  1. Audit Service Unit Tests
# ─────────────────────────────────────────────────────────

def test_redact_sensitive_values():
    """Assert that passwords, tokens, cvvs, cards, etc. are recursively redacted."""
    payload = {
        "username": "admin",
        "password": "supersecretpassword",
        "token": "bearer-jwt-token-string",
        "nested": {
            "card_number": "1234-5678-9012-3456",
            "cvv": "123",
            "safe_key": "safe_val"
        },
        "list_data": [
            {"jwt": "secretjwt"},
            {"safe_data": 42}
        ]
    }
    redacted = redact_sensitive_values(payload)
    assert redacted["username"] == "admin"
    assert redacted["password"] == "[REDACTED]"
    assert redacted["token"] == "[REDACTED]"
    assert redacted["nested"]["card_number"] == "[REDACTED]"
    assert redacted["nested"]["cvv"] == "[REDACTED]"
    assert redacted["nested"]["safe_key"] == "safe_val"
    assert redacted["list_data"][0]["jwt"] == "[REDACTED]"
    assert redacted["list_data"][1]["safe_data"] == 42


def test_sanitize_metadata():
    """Assert that only whitelisted parameters are allowed and sensitive values are redacted."""
    meta = {
        "task_id": "task-uuid-123",
        "file_size": 1024,
        "password": "do-not-log-me",
        "random_unwanted_key": "ignore-me",
        "error_category": "ValidationError"
    }
    sanitized = sanitize_metadata(meta)
    assert sanitized is not None
    assert sanitized["task_id"] == "task-uuid-123"
    assert sanitized["file_size"] == 1024
    assert sanitized["error_category"] == "ValidationError"
    # Unwhitelisted key and sensitive keys should be absent
    assert "password" not in sanitized
    assert "random_unwanted_key" not in sanitized


@pytest.mark.asyncio
async def test_audit_service_fail_safe():
    """Assert that database write failures do not crash the caller."""
    # Mock AsyncSessionLocal to throw an exception
    with patch("services.audit_service.AsyncSessionLocal") as mock_session_local:
        mock_session_local.side_effect = Exception("DB Connection Down")
        
        # This call should succeed and not raise any exception
        await log_audit_event(
            action="test_fail_safe",
            resource_type="system",
            status="success",
            metadata={"username": "testuser"}
        )


# ─────────────────────────────────────────────────────────
#  2. Route Integration Tests
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_auth_events(client: AsyncClient):
    """Test that login (success/fail) and logout write audit events."""
    # 1. Register analyst
    await client.post("/api/auth/register", json={
        "email": "analyst_audit@example.com",
        "username": "analyst_audit",
        "full_name": "Analyst Audit",
        "password": "pass123_audit",
        "role": "analyst",
    })

    # 2. Login fail
    login_fail_resp = await client.post("/api/auth/login", data={
        "username": "analyst_audit",
        "password": "wrong_password",
    })
    assert login_fail_resp.status_code == 401

    # 3. Login success
    login_success_resp = await client.post("/api/auth/login", data={
        "username": "analyst_audit",
        "password": "pass123_audit",
    })
    assert login_success_resp.status_code == 200
    csrf_token = login_success_resp.cookies.get("csrf_token")

    # 4. Logout (passing CSRF token)
    logout_resp = await client.post("/api/auth/logout", headers={"x-csrf-token": csrf_token})
    assert logout_resp.status_code == 200

    # Query DB to assert audit events were recorded
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AuditLog).order_by(AuditLog.created_at.desc())
        )
        logs = result.scalars().all()
        
        # Verify login failure event
        fail_logs = [l for l in logs if l.action == "login" and l.status == "failure"]
        assert len(fail_logs) >= 1
        assert "username" not in fail_logs[0].metadata_json
        assert fail_logs[0].metadata_json["login_identifier_present"] is True
        assert fail_logs[0].metadata_json["error_category"] == "invalid_credentials"
        assert "password" not in fail_logs[0].metadata_json

        # Verify login success event
        success_logs = [l for l in logs if l.action == "login" and l.status == "success"]
        assert len(success_logs) >= 1

        # Verify logout event
        logout_logs = [l for l in logs if l.action == "logout"]
        assert len(logout_logs) >= 1


@pytest.mark.asyncio
async def test_audit_prediction_and_transaction_events(client: AsyncClient, monkeypatch):
    """Test prediction submissions and transaction reviews write audit events."""
    # Mock Celery delay to avoid calling real Redis broker
    class MockTask:
        id = "mock-task-uuid"

    from tasks.predict_tasks import process_batch, process_batch_file
    monkeypatch.setattr(process_batch, "delay", lambda *args, **kwargs: MockTask())
    monkeypatch.setattr(process_batch_file, "delay", lambda *args, **kwargs: MockTask())

    # 1. Create and login admin
    from services.auth_service import hash_password
    async with AsyncSessionLocal() as db:
        admin_u = User(
            email="admin_audit@example.com",
            username="admin_audit",
            full_name="Admin Audit",
            hashed_password=hash_password("admin_pass123"),
            role=UserRole.admin
        )
        db.add(admin_u)
        await db.commit()
    login_resp = await client.post("/api/auth/login", data={
        "username": "admin_audit",
        "password": "admin_pass123",
    })
    csrf_token = login_resp.cookies.get("csrf_token")
    headers = {"x-csrf-token": csrf_token}

    # 2. Submit Batch JSON prediction
    from tests.test_predict import VALID_LEGIT
    batch_resp = await client.post("/api/predict/batch", json={"transactions": [VALID_LEGIT]}, headers=headers)
    assert batch_resp.status_code == 200

    # 3. Submit Invalid batch-file prediction (rejected)
    from io import BytesIO
    invalid_file = {"file": ("test.txt", BytesIO(b"dummy data"), "text/plain")}
    rejected_resp = await client.post("/api/predict/batch-file", files=invalid_file, headers=headers)
    assert rejected_resp.status_code == 400

    # 4. Submit Valid batch-file prediction (success submission)
    csv_content = (
        "Amount,Time,V1,V2,V3,V4,V5,V6,V7,V8,V9,V10,V11,V12,V13,V14,V15,V16,V17,V18,V19,V20,V21,V22,V23,V24,V25,V26,V27,V28\n"
        "100.0,3600,-1.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0\n"
    )
    valid_file = {"file": ("test.csv", BytesIO(csv_content.encode("utf-8")), "text/csv")}
    accepted_resp = await client.post("/api/predict/batch-file", files=valid_file, headers=headers)
    assert accepted_resp.status_code == 200

    # 5. Review transaction
    single_resp = await client.post("/api/predict/transaction", json=VALID_LEGIT, headers=headers)
    assert single_resp.status_code == 200
    txn_id = single_resp.json()["transaction_id"]

    review_resp = await client.put(f"/api/transactions/{txn_id}/review", json={
        "status": "approved",
        "review_notes": "Looks safe."
    }, headers=headers)
    assert review_resp.status_code == 200

    # Verify DB events
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()))
        logs = result.scalars().all()

        # Check batch JSON submitted
        json_submitted_logs = [l for l in logs if l.action == "batch_json_submitted"]
        assert len(json_submitted_logs) >= 1
        assert "task_id" in json_submitted_logs[0].metadata_json

        # Check batch file submitted
        file_submitted_logs = [l for l in logs if l.action == "batch_file_submitted"]
        assert len(file_submitted_logs) >= 1
        assert "task_id" in file_submitted_logs[0].metadata_json

        # Check batch file rejected
        file_rejected_logs = [l for l in logs if l.action == "batch_file_rejected"]
        assert len(file_rejected_logs) >= 1
        assert file_rejected_logs[0].metadata_json["error_category"] in ("InvalidFileType", "InvalidContentType")

        # Check transaction review updated
        review_logs = [l for l in logs if l.action == "transaction_review_updated"]
        assert len(review_logs) >= 1
        assert review_logs[0].resource_id == txn_id
        assert review_logs[0].metadata_json["status_to"] == "approved"


def test_websocket_audit_events():
    """Test websocket connections generate audit logs."""
    with TestClient(app) as test_client:
        # 1. Reject without token
        try:
            with test_client.websocket_connect("/api/ws/alerts") as ws:
                pass
        except WebSocketDisconnect as e:
            assert e.code == 4001

        # 2. Reject Customer role
        test_client.post("/api/auth/register", json={
            "email": "wscustomer_audit@example.com",
            "username": "wscustomer_audit",
            "full_name": "WS Customer Audit",
            "password": "pass_audit_123",
            "role": "customer",
        })
        test_client.post("/api/auth/login", data={"username": "wscustomer_audit", "password": "pass_audit_123"})
        
        try:
            with test_client.websocket_connect("/api/ws/alerts") as ws:
                pass
        except WebSocketDisconnect as e:
            assert e.code == 4003

        # 3. Connect Analyst successfully
        test_client.post("/api/auth/register", json={
            "email": "wsanalyst_audit@example.com",
            "username": "wsanalyst_audit",
            "full_name": "WS Analyst Audit",
            "password": "pass_audit_123",
            "role": "analyst",
        })
        test_client.post("/api/auth/login", data={"username": "wsanalyst_audit", "password": "pass_audit_123"})

        with test_client.websocket_connect("/api/ws/alerts") as ws:
            ws.receive_json()

    # Verify DB events
    async def verify_db():
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()))
            logs = result.scalars().all()

            # Connection success
            success_logs = [l for l in logs if l.action == "websocket_connect_success"]
            assert len(success_logs) >= 1

            # Connection rejected (TokenMissing)
            missing_logs = [l for l in logs if l.action == "websocket_connect_rejected"]
            assert len(missing_logs) >= 1

            # Connection RBAC rejected
            rbac_logs = [l for l in logs if l.action == "websocket_rbac_rejected"]
            assert len(rbac_logs) >= 1

    import asyncio
    asyncio.run(verify_db())


# ─────────────────────────────────────────────────────────
#  3. Admin Audit Logs Endpoint Tests
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_audit_logs_endpoint_security_and_pagination(client: AsyncClient):
    """Test RBAC blocks unauthenticated/analysts/customers and allows admin with pagination checks."""
    # 1. Register users (Admin via DB, others via API)
    from services.auth_service import hash_password
    async with AsyncSessionLocal() as db:
        admin_u = User(
            email="admin_ep@example.com",
            username="admin_ep",
            full_name="Admin EP",
            hashed_password=hash_password("Pass1234"),
            role=UserRole.admin
        )
        db.add(admin_u)
        await db.commit()

    users = [
        {"email": "analyst_ep@example.com", "username": "analyst_ep", "full_name": "Analyst EP", "password": "Pass1234", "role": "analyst"},
        {"email": "customer_ep@example.com", "username": "customer_ep", "full_name": "Customer EP", "password": "Pass1234", "role": "customer"},
    ]
    for u in users:
        await client.post("/api/auth/register", json=u)

    # Helper to get auth headers / cookies for role
    async def get_cookies_for(username):
        resp = await client.post("/api/auth/login", data={"username": username, "password": "Pass1234"})
        assert resp.status_code == 200
        return resp.cookies.get("access_token")

    admin_token = await get_cookies_for("admin_ep")
    analyst_token = await get_cookies_for("analyst_ep")
    customer_token = await get_cookies_for("customer_ep")

    # A. Unauthenticated -> 401
    from httpx import AsyncClient, ASGITransport
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as clean_client:
        unauth_resp = await clean_client.get("/api/audit-logs")
        assert unauth_resp.status_code == 401

        # B. Customer -> 403
        clean_client.cookies.set("access_token", customer_token)
        customer_resp = await clean_client.get("/api/audit-logs")
        assert customer_resp.status_code == 403

        # C. Analyst -> 403
        clean_client.cookies.set("access_token", analyst_token)
        analyst_resp = await clean_client.get("/api/audit-logs")
        assert analyst_resp.status_code == 403

        # D. Admin -> 200 with pagination
        clean_client.cookies.set("access_token", admin_token)
        admin_resp = await clean_client.get("/api/audit-logs", params={"page": 1, "per_page": 2})
        assert admin_resp.status_code == 200
        data = admin_resp.json()
        assert "total" in data
        assert "page" in data
        assert "per_page" in data
        assert "logs" in data
        assert len(data["logs"]) <= 2

        # E. Verify per_page max limit works
        admin_resp_large = await clean_client.get("/api/audit-logs", params={"page": 1, "per_page": 200})
        # per_page=200 is validated by Query(le=100) and returns 422
        assert admin_resp_large.status_code == 422


# ─────────────────────────────────────────────────────────
#  4. Safety, Privacy, and Boundary Correction Tests
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_endpoint_uuid_validation(client: AsyncClient):
    """Verify that an invalid UUID in actor_user_id returns 400 Bad Request."""
    # 1. Create and login admin
    from services.auth_service import hash_password
    async with AsyncSessionLocal() as db:
        admin_u = User(
            email="admin_uuid_check@example.com",
            username="admin_uuid_check",
            full_name="Admin UUID Check",
            hashed_password=hash_password("Pass1234"),
            role=UserRole.admin
        )
        db.add(admin_u)
        await db.commit()
    login_resp = await client.post("/api/auth/login", data={"username": "admin_uuid_check", "password": "Pass1234"})
    assert login_resp.status_code == 200
    token = login_resp.cookies.get("access_token")

    from httpx import AsyncClient, ASGITransport
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as clean_client:
        clean_client.cookies.set("access_token", token)
        
        # Test invalid UUID -> 400
        bad_uuid_resp = await clean_client.get("/api/audit-logs", params={"actor_user_id": "not-a-valid-uuid"})
        assert bad_uuid_resp.status_code == 400
        assert "Invalid actor_user_id" in bad_uuid_resp.json()["detail"]

        # Test valid UUID -> 200
        good_uuid_resp = await clean_client.get("/api/audit-logs", params={"actor_user_id": str(uuid.uuid4())})
        assert good_uuid_resp.status_code == 200


@pytest.mark.asyncio
async def test_audit_redaction_failed_login(client: AsyncClient):
    """Assert that failed login metadata has no raw username and is properly redacted."""
    # Try invalid login
    login_resp = await client.post("/api/auth/login", data={
        "username": "secret_attacker_user",
        "password": "wrong_password",
    })
    assert login_resp.status_code == 401

    # Check DB
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AuditLog).where(AuditLog.action == "login", AuditLog.status == "failure").order_by(AuditLog.created_at.desc())
        )
        logs = result.scalars().all()
        assert len(logs) >= 1
        meta = logs[0].metadata_json
        
        # Username must not be present in metadata
        assert "username" not in meta
        # Verify generic flags are present
        assert meta["error_category"] == "invalid_credentials"
        assert meta["login_identifier_present"] is True


@pytest.mark.asyncio
async def test_audit_write_failure_does_not_rollback_business_transaction(client: AsyncClient):
    """
    Force audit database write failure.
    Perform transaction review or another persistent business update.
    Verify primary update exists using a fresh independent DB session.
    Verify audit failure did not roll back main operation.
    """
    # 1. Register/Login analyst
    await client.post("/api/auth/register", json={
        "email": "analyst_rollback_check@example.com",
        "username": "analyst_rollback_check",
        "full_name": "Analyst Rollback Check",
        "password": "Pass1234_Check",
        "role": "analyst",
    })
    login_resp = await client.post("/api/auth/login", data={"username": "analyst_rollback_check", "password": "Pass1234_Check"})
    assert login_resp.status_code == 200
    csrf_token = login_resp.cookies.get("csrf_token")
    headers = {"x-csrf-token": csrf_token}

    # 2. Predict a transaction to get an ID
    from tests.test_predict import VALID_LEGIT
    pred_resp = await client.post("/api/predict/transaction", json=VALID_LEGIT, headers=headers)
    assert pred_resp.status_code == 200
    txn_id = pred_resp.json()["transaction_id"]

    # 3. Mock log_audit_event DB write to fail
    # We patch AsyncSessionLocal inside audit_service to raise a DB connection error
    with patch("services.audit_service.AsyncSessionLocal") as mock_session_class:
        from unittest.mock import AsyncMock
        mock_session = AsyncMock()
        mock_session.commit.side_effect = Exception("Audit DB Write Failed")
        mock_session_class.return_value = mock_session

        # 4. Perform primary business operation (review transaction status update)
        review_resp = await client.put(f"/api/transactions/{txn_id}/review", json={
            "status": "approved",
            "review_notes": "Rollback test notes"
        }, headers=headers)
        
        # Verify the primary business request succeeds with 200
        assert review_resp.status_code == 200
        assert review_resp.json()["status"] == "approved"

    # 5. Verify database update exists in fresh independent DB session
    async with AsyncSessionLocal() as db:
        from models.transaction import Transaction
        result = await db.execute(select(Transaction).where(Transaction.id == uuid.UUID(txn_id)))
        txn = result.scalar_one()
        assert txn.status.value == "approved"
        assert txn.review_notes == "Rollback test notes"


@pytest.mark.asyncio
async def test_celery_only_logs_lifecycle_events_to_db(client: AsyncClient, monkeypatch):
    """
    Test that Celery process_batch writes start/completion/failure lifecycle events to DB,
    but does NOT write chunk_progress event logs to the database.
    """
    from tasks.predict_tasks import _async_process_batch
    from tests.test_predict import VALID_LEGIT

    # Mock predict_batch
    mock_res = [{
        "fraud_score": 0.05,
        "fraud_percentage": 5.0,
        "is_fraud": False,
        "risk_level": "LOW",
        "risk_color": "#10b981",
        "explanation": "Test explanation",
        "top_features": [],
        "all_shap_values": {}
    }]
    monkeypatch.setattr("ml.predict.predict_batch", lambda *args, **kwargs: mock_res)

    # Run celery process_batch async helper directly
    res = await _async_process_batch(
        transactions=[VALID_LEGIT],
        user_id=None
    )
    assert res["processed"] == 1

    # Check DB logs
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()))
        logs = result.scalars().all()
        
        # Verify lifecycle events are recorded in DB
        lifecycle_starts = [l for l in logs if l.action == "batch_started"]
        lifecycle_ends = [l for l in logs if l.action == "batch_completed"]
        assert len(lifecycle_starts) >= 1
        assert len(lifecycle_ends) >= 1

        # Verify chunk_progress is NOT written to the DB
        chunk_logs = [l for l in logs if l.action == "chunk_progress"]
        assert len(chunk_logs) == 0


@pytest.mark.asyncio
async def test_request_id_header_and_injection_filtering(client: AsyncClient):
    """
    Test request ID middleware generates ID, returns header,
    filters malformed/injected request IDs, and doesn't leak context.
    """
    # 1. Missing request ID -> generated and returned
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "X-Request-ID" in resp.headers
    generated_id = resp.headers["X-Request-ID"]
    assert len(generated_id) > 10

    # 2. Oversized/Injected ID -> replaced with safe UUID
    # Send a request ID with control characters/newlines
    malicious_id = "abc\ndef-very-long-id-more-than-64-characters-long-1234567890-1234567890"
    resp_bad = await client.get("/", headers={"X-Request-ID": malicious_id})
    assert resp_bad.status_code == 200
    returned_id = resp_bad.headers["X-Request-ID"]
    # It must be a clean generated UUID instead of malicious_id
    assert returned_id != malicious_id
    assert len(returned_id) == 36  # UUID length

    # 3. Safe incoming request ID -> accepted
    safe_id = "my-custom-safe-request-id-1234"
    resp_safe = await client.get("/", headers={"X-Request-ID": safe_id})
    assert resp_safe.status_code == 200
    assert resp_safe.headers["X-Request-ID"] == safe_id

