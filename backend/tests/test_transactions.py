import pytest
from httpx import AsyncClient
import uuid

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
    resp = await client.put("/api/transactions/invalid-uuid-string/review", json={"status": "approved"}, headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid transaction ID format"

async def test_transaction_not_found(client: AsyncClient, auth_headers: dict):
    random_uuid = str(uuid.uuid4())
    resp = await client.get(f"/api/transactions/{random_uuid}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Transaction not found"

async def test_get_transactions_pagination(client: AsyncClient, auth_headers: dict):
    from database.db import AsyncSessionLocal
    from models.transaction import Transaction, RiskLevel, TransactionStatus

    async with AsyncSessionLocal() as db:
        for i in range(5):
            t = Transaction(
                amount=100.0 + i,
                merchant=f"Merchant {i}",
                risk_level=RiskLevel.LOW,
                status=TransactionStatus.pending,
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
    from models.transaction import Transaction, RiskLevel, TransactionStatus

    async with AsyncSessionLocal() as db:
        t1 = Transaction(
            amount=100.0, merchant="M1",
            risk_level=RiskLevel.HIGH, status=TransactionStatus.flagged,
            is_fraud=True, fraud_score=0.9, v_features={}
        )
        t2 = Transaction(
            amount=200.0, merchant="M2",
            risk_level=RiskLevel.LOW, status=TransactionStatus.pending,
            is_fraud=False, fraud_score=0.1, v_features={}
        )
        t3 = Transaction(
            amount=300.0, merchant="M3",
            risk_level=RiskLevel.MEDIUM, status=TransactionStatus.approved,
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

    # Filter status = approved
    resp = await client.get("/api/transactions?status=approved", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["transactions"]) == 1
    assert data["transactions"][0]["merchant"] == "M3"

async def test_review_transaction_success(client: AsyncClient, auth_headers: dict):
    from database.db import AsyncSessionLocal
    from models.transaction import Transaction, RiskLevel, TransactionStatus

    async with AsyncSessionLocal() as db:
        t = Transaction(
            amount=100.0, merchant="M1",
            risk_level=RiskLevel.MEDIUM, status=TransactionStatus.pending,
            is_fraud=False, fraud_score=0.35, v_features={}
        )
        db.add(t)
        await db.commit()
        await db.refresh(t)
        txn_id = str(t.id)

    resp = await client.put(
        f"/api/transactions/{txn_id}/review",
        json={"status": "approved", "review_notes": "Looks safe"},
        headers=auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "approved"
    assert data["reviewed_by"] == "testuser"
    assert data["review_notes"] == "Looks safe"

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        res = await db.execute(select(Transaction).where(Transaction.id == t.id))
        updated_t = res.scalar_one()
        assert updated_t.status == TransactionStatus.approved
        assert updated_t.review_notes == "Looks safe"
        assert updated_t.reviewed_by == "testuser"

async def test_review_transaction_unauthorized(client: AsyncClient):
    from database.db import AsyncSessionLocal
    from models.transaction import Transaction, RiskLevel, TransactionStatus

    # Register customer
    await client.post("/api/auth/register", json={
        "email":     "cust_test@example.com",
        "username":  "cust_test",
        "full_name": "Customer User",
        "password":  "cust_pass",
        "role":      "customer",
    })
    login_resp = await client.post("/api/auth/login", data={
        "username": "cust_test",
        "password": "cust_pass",
    })
    cust_token = login_resp.json()["access_token"]
    cust_headers = {"Authorization": f"Bearer {cust_token}"}

    async with AsyncSessionLocal() as db:
        t = Transaction(
            amount=100.0, merchant="M1",
            risk_level=RiskLevel.MEDIUM, status=TransactionStatus.pending,
            is_fraud=False, fraud_score=0.35, v_features={}
        )
        db.add(t)
        await db.commit()
        await db.refresh(t)
        txn_id = str(t.id)

    resp = await client.put(
        f"/api/transactions/{txn_id}/review",
        json={"status": "approved", "review_notes": "Block"},
        headers=cust_headers
    )
    assert resp.status_code == 403
