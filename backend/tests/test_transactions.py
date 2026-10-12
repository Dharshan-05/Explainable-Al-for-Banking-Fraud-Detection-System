import pytest
from httpx import AsyncClient
import uuid
from models.transaction import TransactionStatus

pytestmark = pytest.mark.asyncio

async def test_get_transactions_pagination_and_filtering(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/transactions", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "transactions" in data
    assert isinstance(data["transactions"], list)

async def test_transaction_invalid_uuid(client: AsyncClient, auth_headers: dict):
    # 1. Test detail lookup with invalid UUID string
    resp = await client.get("/api/transactions/invalid-uuid-string", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid transaction ID format"

    # 2. Test review update with invalid UUID string
    resp = await client.put("/api/transactions/invalid-uuid-string/review", json={"status": "APPROVED"}, headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid transaction ID format"

async def test_transaction_not_found(client: AsyncClient, auth_headers: dict):
    random_uuid = str(uuid.uuid4())
    resp = await client.get(f"/api/transactions/{random_uuid}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Transaction not found"

async def test_get_transactions_pagination(client: AsyncClient, auth_headers: dict):
    from database.db import AsyncSessionLocal
    from models.transaction import Transaction, RiskLevel

    async with AsyncSessionLocal() as db:
        for i in range(5):
            t = Transaction(
                amount=100.0 + i,
                merchant=f"Merchant {i}",
                risk_level=RiskLevel.LOW,
                status=TransactionStatus.PENDING,
                is_fraud=False,
                fraud_score=0.01 * i,
                v_features={}
            )
            db.add(t)
        await db.commit()

    resp = await client.get("/api/transactions?page=1&per_page=2", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert len(data["transactions"]) == 2

    resp = await client.get("/api/transactions?page=2&per_page=2", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["transactions"]) == 2

    resp = await client.get("/api/transactions?page=3&per_page=2", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["transactions"]) == 1

async def test_get_transactions_filters(client: AsyncClient, auth_headers: dict):
    from database.db import AsyncSessionLocal
    from models.transaction import Transaction, RiskLevel

    async with AsyncSessionLocal() as db:
        t1 = Transaction(
            amount=100.0, merchant="M1",
            risk_level=RiskLevel.HIGH, status=TransactionStatus.FLAGGED,
            is_fraud=True, fraud_score=0.9, v_features={}
        )
        t2 = Transaction(
            amount=200.0, merchant="M2",
            risk_level=RiskLevel.LOW, status=TransactionStatus.PENDING,
            is_fraud=False, fraud_score=0.1, v_features={}
        )
        t3 = Transaction(
            amount=300.0, merchant="M3",
            risk_level=RiskLevel.MEDIUM, status=TransactionStatus.APPROVED,
            is_fraud=False, fraud_score=0.4, v_features={}
        )
        db.add_all([t1, t2, t3])
        await db.commit()

    # Filter is_fraud = true
    resp = await client.get("/api/transactions?is_fraud=true", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["transactions"]) == 1
    assert data["transactions"][0]["merchant"] == "M1"

    # Filter risk_level = LOW
    resp = await client.get("/api/transactions?risk_level=LOW", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["transactions"]) == 1
    assert data["transactions"][0]["merchant"] == "M2"

    # Filter status = APPROVED (uppercase)
    resp = await client.get("/api/transactions?status=APPROVED", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["transactions"]) == 1
    assert data["transactions"][0]["merchant"] == "M3"

    # Filter status = approved (lowercase alias compatibility)
    resp = await client.get("/api/transactions?status=approved", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["transactions"]) == 1
    assert data["transactions"][0]["merchant"] == "M3"

async def test_review_transaction_success(client: AsyncClient, auth_headers: dict):
    from database.db import AsyncSessionLocal
    from models.transaction import Transaction, RiskLevel

    async with AsyncSessionLocal() as db:
        t = Transaction(
            amount=100.0, merchant="M1",
            risk_level=RiskLevel.MEDIUM, status=TransactionStatus.PENDING,
            is_fraud=False, fraud_score=0.35, v_features={}
        )
        db.add(t)
        await db.commit()
        await db.refresh(t)
        txn_id = str(t.id)

    resp = await client.put(
        f"/api/transactions/{txn_id}/review",
        json={"status": "APPROVED", "review_notes": "Looks safe"},
        headers=auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "APPROVED"
    assert data["reviewed_by"] == "testuser"
    assert data["review_notes"] == "Looks safe"

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        res = await db.execute(select(Transaction).where(Transaction.id == t.id))
        updated_t = res.scalar_one()
        assert updated_t.status == TransactionStatus.APPROVED
        assert updated_t.review_notes == "Looks safe"
        assert updated_t.reviewed_by == "testuser"

async def test_approve_reject_flag_individual(client: AsyncClient, auth_headers: dict):
    from database.db import AsyncSessionLocal
    from models.transaction import Transaction, RiskLevel

    async with AsyncSessionLocal() as db:
        t1 = Transaction(amount=100.0, status=TransactionStatus.PENDING, risk_level=RiskLevel.LOW, v_features={})
        t2 = Transaction(amount=200.0, status=TransactionStatus.PENDING, risk_level=RiskLevel.LOW, v_features={})
        t3 = Transaction(amount=300.0, status=TransactionStatus.PENDING, risk_level=RiskLevel.LOW, v_features={})
        db.add_all([t1, t2, t3])
        await db.commit()
        await db.refresh(t1)
        await db.refresh(t2)
        await db.refresh(t3)
        id1, id2, id3 = str(t1.id), str(t2.id), str(t3.id)

    # Test Approve
    resp = await client.put(f"/api/transactions/{id1}/approve", json={"notes": "Safe card"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "APPROVED"
    assert resp.json()["review_notes"] == "Safe card"

    # Test Reject without notes (should fail)
    resp = await client.put(f"/api/transactions/{id2}/reject", json={"notes": ""}, headers=auth_headers)
    assert resp.status_code == 400

    # Test Reject with notes (should pass)
    resp = await client.put(f"/api/transactions/{id2}/reject", json={"notes": "Confirmed stolen"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "REJECTED"

    # Test Flag
    resp = await client.put(f"/api/transactions/{id3}/flag", json={"notes": "Audit required", "assigned_analyst": "john_doe"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "FLAGGED"
    assert resp.json()["assigned_analyst"] == "john_doe"

async def test_bulk_review_success(client: AsyncClient, auth_headers: dict):
    from database.db import AsyncSessionLocal
    from models.transaction import Transaction, RiskLevel

    async with AsyncSessionLocal() as db:
        t1 = Transaction(amount=100.0, status=TransactionStatus.PENDING, risk_level=RiskLevel.LOW, v_features={})
        t2 = Transaction(amount=200.0, status=TransactionStatus.PENDING, risk_level=RiskLevel.LOW, v_features={})
        db.add_all([t1, t2])
        await db.commit()
        await db.refresh(t1)
        await db.refresh(t2)
        ids = [str(t1.id), str(t2.id)]

    # Bulk approve
    resp = await client.put("/api/transactions/bulk-review", json={
        "transactionIds": ids,
        "status": "APPROVED",
        "notes": "Bulk safe approval"
    }, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["status"] == "APPROVED"
    assert data[1]["status"] == "APPROVED"

async def test_export_transactions_csv(client: AsyncClient, auth_headers: dict):
    from database.db import AsyncSessionLocal
    from models.transaction import Transaction, RiskLevel

    async with AsyncSessionLocal() as db:
        t = Transaction(amount=123.45, merchant="Target Export", risk_level=RiskLevel.HIGH, status=TransactionStatus.PENDING, v_features={})
        db.add(t)
        await db.commit()
        await db.refresh(t)
        txn_id = str(t.id)

    # Selected export
    resp = await client.post("/api/transactions/export", json={
        "exportType": "selected",
        "transactionIds": [txn_id]
    }, headers=auth_headers)
    
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    csv_content = resp.content.decode("utf-8")
    assert "transaction_id" in csv_content
    assert "Target Export" not in csv_content  # Target Export is merchant (not headers or tx fields in csv row)
    assert "123.45" in csv_content

async def test_review_transaction_unauthorized(client: AsyncClient):
    from database.db import AsyncSessionLocal
    from models.transaction import Transaction, RiskLevel

    # Register customer (which should be blocked from review)
    await client.post("/api/auth/register", json={
        "email":     "cust_test@example.com",
        "username":  "cust_test",
        "full_name": "Customer User",
        "password":  "CustPass123",
        "role":      "customer",
    })
    login_resp = await client.post("/api/auth/login", data={
        "username": "cust_test",
        "password": "CustPass123",
    })
    cust_token = login_resp.json()["access_token"]
    cust_headers = {"Authorization": f"Bearer {cust_token}"}

    async with AsyncSessionLocal() as db:
        t = Transaction(
            amount=100.0, merchant="M1",
            risk_level=RiskLevel.MEDIUM, status=TransactionStatus.PENDING,
            is_fraud=False, fraud_score=0.35, v_features={}
        )
        db.add(t)
        await db.commit()
        await db.refresh(t)
        txn_id = str(t.id)

    resp = await client.put(
        f"/api/transactions/{txn_id}/review",
        json={"status": "APPROVED", "review_notes": "Block"},
        headers=cust_headers
    )
    assert resp.status_code == 403
