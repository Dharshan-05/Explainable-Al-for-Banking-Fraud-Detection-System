import os
import tempfile
import uuid
import json
import pytest
from unittest.mock import patch
from sqlalchemy import select, text, delete
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from models.transaction import Transaction, TransactionStatus, RiskLevel
from models.audit_log import AuditLog
from models.user import User, UserRole
from tasks.predict_tasks import _async_process_batch_file

# Sample valid and invalid transaction inputs
VALID_COPY_1 = {
    "V1": 0.5, "V2": -0.2, "V3": 1.1, "V4": -0.4, "V5": 0.1, "V6": 0.0, "V7": 0.0, "V8": 0.0, "V9": 0.0, "V10": 0.0,
    "V11": 0.0, "V12": 0.0, "V13": 0.0, "V14": 0.2, "V15": 0.0, "V16": 0.0, "V17": 0.0, "V18": 0.0, "V19": 0.0, "V20": 0.0,
    "V21": 0.0, "V22": 0.0, "V23": 0.0, "V24": 0.0, "V25": 0.0, "V26": 0.0, "V27": 0.0, "V28": 0.0,
    "Amount": 100.0, "Time": 1000.0,
    "merchant": "POSTGRES_COPY_TEST", "merchant_category": "food",
    "location": "San Francisco", "card_last4": "5555"
}

VALID_COPY_2 = {
    **VALID_COPY_1, "Amount": 200.0, "merchant": "POSTGRES_COPY_TEST", "V14": -8.5
}

# String value too long (> 255 chars) will fail PostgreSQL string validation
INVALID_COPY_DB_FAIL = {
    **VALID_COPY_1, "merchant": "POSTGRES_COPY_TEST", "location": "X" * 300
}

async def get_postgres_engine():
    urls = [
        "postgresql+asyncpg://admin:secretpassword123@db:5432/frauddb",
        "postgresql+asyncpg://admin:secretpassword123@localhost:5432/frauddb",
        "postgresql+asyncpg://admin@localhost:5433/frauddb",
    ]
    for url in urls:
        try:
            engine = create_async_engine(url, connect_args={"ssl": False})
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return engine
        except Exception:
            continue
    return None

@pytest.mark.asyncio
async def test_postgresql_copy_integration():
    engine = await get_postgres_engine()
    if engine is None:
        pytest.skip("Opt-in PostgreSQL integration test skipped: No running PostgreSQL instance found.")

    print(f"\n[PostgreSQL Integration] Connected to: {engine.url.render_as_string(hide_password=True)}")
    postgres_sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # 1. Ensure user exists in postgres database for foreign key or log reference if required
    user_id = str(uuid.uuid4())
    async with postgres_sessionmaker() as session:
        # Create a dummy user to satisfy actor_user_id FK constraint
        u = User(
            id=uuid.UUID(user_id),
            email=f"test_{user_id}@example.com",
            username=f"test_{user_id}",
            full_name="Postgres Integration Test User",
            hashed_password="dummy_hash",
            role=UserRole.analyst
        )
        session.add(u)
        # Clean up any leftover transactions/audit logs for this test run
        await session.execute(delete(Transaction).where(Transaction.merchant == "POSTGRES_COPY_TEST"))
        await session.commit()

    # 2. Write CSV with valid records
    csv_header = "Amount,Time,V1,V2,V3,V4,V5,V6,V7,V8,V9,V10,V11,V12,V13,V14,V15,V16,V17,V18,V19,V20,V21,V22,V23,V24,V25,V26,V27,V28,merchant,merchant_category,location,card_last4\n"
    csv_rows = (
        f"100.0,1000.0,0.5,-0.2,1.1,-0.4,0.1,0,0,0,0,0,0,0,0,0.2,0,0,0,0,0,0,0,0,0,0,0,0,0,0,POSTGRES_COPY_TEST,food,San Francisco,5555\n"
        f"200.0,1000.0,0.5,-0.2,1.1,-0.4,0.1,0,0,0,0,0,0,0,0,-8.5,0,0,0,0,0,0,0,0,0,0,0,0,0,0,POSTGRES_COPY_TEST,food,San Francisco,5555\n"
    )
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w", encoding="utf-8") as f:
        f.write(csv_header + csv_rows)
        temp_path = f.name

    # 3. Patch session maker and spy on copy_records_to_table class method
    import asyncpg
    copy_called = False
    original_copy = asyncpg.Connection.copy_records_to_table

    async def spy_copy(self, *args, **kwargs):
        nonlocal copy_called
        copy_called = True
        return await original_copy(self, *args, **kwargs)

    # Execute task with patches
    with patch("tasks.predict_tasks.AsyncSessionLocal", postgres_sessionmaker), \
         patch("database.db.AsyncSessionLocal", postgres_sessionmaker), \
         patch("services.audit_service.AsyncSessionLocal", postgres_sessionmaker), \
         patch.object(asyncpg.Connection, "copy_records_to_table", new=spy_copy):
        
        try:
            result = await _async_process_batch_file(temp_path, user_id)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass

    # 4. Assertions on task outcomes
    assert not os.path.exists(temp_path), "Temp file was not cleaned up!"
    assert result["total"] == 2
    assert result["processed"] == 2
    assert result["failed"] == 0
    assert result["fraud_count"] == 1
    assert copy_called, "PostgreSQL COPY path was not executed!"

    # 5. Verify database integrity
    async with postgres_sessionmaker() as session:
        # Check transaction columns
        stmt = select(Transaction).where(Transaction.merchant == "POSTGRES_COPY_TEST").order_order = Transaction.amount
        db_res = await session.execute(select(Transaction).where(Transaction.merchant == "POSTGRES_COPY_TEST").order_by(Transaction.amount))
        txns = db_res.scalars().all()
        assert len(txns) == 2

        # Verify fields
        t1, t2 = txns[0], txns[1]
        assert t1.amount == 100.0
        assert t1.is_fraud is False
        assert t1.risk_level == RiskLevel.LOW
        assert t2.amount == 200.0
        assert t2.is_fraud is True
        assert t2.risk_level in [RiskLevel.MEDIUM, RiskLevel.HIGH]

        # Verify JSON/UUID mapping correctness
        assert isinstance(t1.id, uuid.UUID)
        assert t1.v_features["V1"] == 0.5
        assert t1.v_features["V14"] == 0.2
        assert t2.v_features["V14"] == -8.5
        assert t1.created_at is not None

        # Verify audit logging
        stmt_audit = select(AuditLog).where(AuditLog.resource_id == result["predictions"][0]["transaction_id"] if result["predictions"] else "non-existent")
        # Check audit event logs
        stmt_events = select(AuditLog).where(AuditLog.action.in_(["batch_file_started", "batch_file_completed"]))
        audit_res = await session.execute(stmt_events)
        logs = audit_res.scalars().all()
        assert len(logs) >= 2
        
        # Clean up
        await session.execute(delete(Transaction).where(Transaction.merchant == "POSTGRES_COPY_TEST"))
        await session.execute(delete(User).where(User.id == uuid.UUID(user_id)))
        await session.commit()

@pytest.mark.asyncio
async def test_postgresql_copy_failure_isolation():
    """Verify COPY failure safety: if one row is invalid (location too long), the chunk rolls back and row-by-row fallback isolates the failure while keeping other valid rows."""
    engine = await get_postgres_engine()
    if engine is None:
        pytest.skip("Opt-in PostgreSQL integration test skipped: No running PostgreSQL instance found.")

    postgres_sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    user_id = str(uuid.uuid4())

    async with postgres_sessionmaker() as session:
        # Create a dummy user to satisfy actor_user_id FK constraint
        u = User(
            id=uuid.UUID(user_id),
            email=f"test_{user_id}@example.com",
            username=f"test_{user_id}",
            full_name="Postgres Integration Test User",
            hashed_password="dummy_hash",
            role=UserRole.analyst
        )
        session.add(u)
        await session.execute(delete(Transaction).where(Transaction.merchant == "POSTGRES_COPY_TEST"))
        await session.commit()

    # Create a CSV where one row is valid and one row will trigger character limits on location (> 255 chars)
    csv_header = "Amount,Time,V1,V2,V3,V4,V5,V6,V7,V8,V9,V10,V11,V12,V13,V14,V15,V16,V17,V18,V19,V20,V21,V22,V23,V24,V25,V26,V27,V28,merchant,merchant_category,location,card_last4\n"
    csv_rows = (
        f"100.0,1000.0,0.5,-0.2,1.1,-0.4,0.1,0,0,0,0,0,0,0,0,0.2,0,0,0,0,0,0,0,0,0,0,0,0,0,0,POSTGRES_COPY_TEST,food,San Francisco,5555\n"
        f"300.0,1000.0,0.5,-0.2,1.1,-0.4,0.1,0,0,0,0,0,0,0,0,0.2,0,0,0,0,0,0,0,0,0,0,0,0,0,0,POSTGRES_COPY_TEST,food,{'X' * 300},5555\n"
    )
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w", encoding="utf-8") as f:
        f.write(csv_header + csv_rows)
        temp_path = f.name

    try:
        with patch("tasks.predict_tasks.AsyncSessionLocal", postgres_sessionmaker), \
             patch("database.db.AsyncSessionLocal", postgres_sessionmaker), \
             patch("services.audit_service.AsyncSessionLocal", postgres_sessionmaker):
            
            result = await _async_process_batch_file(temp_path, user_id)
    finally:
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass
    assert result["total"] == 2
    assert result["processed"] == 1
    assert result["failed"] == 1
    assert len(result["failed_details"]) == 1
    assert "value too long for type character varying(255)" in result["failed_details"][0]["error"].lower()

    # Query DB to check if the valid row was persisted and the invalid one rolled back
    async with postgres_sessionmaker() as session:
        db_res = await session.execute(select(Transaction).where(Transaction.merchant == "POSTGRES_COPY_TEST"))
        txns = db_res.scalars().all()
        assert len(txns) == 1
        assert txns[0].amount == 100.0

        # Clean up
        await session.execute(delete(Transaction).where(Transaction.merchant == "POSTGRES_COPY_TEST"))
        await session.execute(delete(User).where(User.id == uuid.UUID(user_id)))
        await session.commit()
