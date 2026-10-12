import os
import tempfile
import uuid
import pytest
import pandas as pd
import numpy as np
from sqlalchemy import select

from database.db import AsyncSessionLocal
from models.transaction import Transaction, TransactionStatus, RiskLevel
from tasks.predict_tasks import _async_process_batch, _async_process_batch_file, validate_chunk_pandas
from ml.predict import predict_batch

# A sample of mock transaction data
VALID_LEGIT = {
    "V1": -1.3, "V2": 1.2, "V3": 1.0, "V4": 0.5,
    "V5": -0.1, "V14": 0.3,
    "Amount": 150.0, "Time": 45000.0,
    "merchant": "Amazon", "merchant_category": "e-commerce",
    "location": "New York", "card_last4": "1234"
}

VALID_FRAUD = {
    **VALID_LEGIT, "V14": -9.5, "Amount": 5000.0, "merchant": "UnusualStore"
}

INVALID_TXN = {
    **VALID_LEGIT, "Amount": -50.0 # Negative amount is invalid
}

class TestPerformanceOptimizations:
    @pytest.mark.asyncio
    async def test_pandas_parser_equivalence(self):
        """Verify that validate_chunk_pandas outputs match the expected output format and filter rules."""
        chunk_df = pd.DataFrame([VALID_LEGIT, VALID_FRAUD, INVALID_TXN])
        raw_rows = chunk_df.to_dict(orient="records")
        headers = list(chunk_df.columns)
        
        parsed_txns, failed_details = validate_chunk_pandas(chunk_df, raw_rows, headers)
        
        # Should have 2 parsed valid transactions and 1 failed
        assert len(parsed_txns) == 2
        assert len(failed_details) == 1
        
        # Verify valid transactions values
        assert parsed_txns[0]["Amount"] == 150.0
        assert parsed_txns[0]["Time"] == 45000.0
        assert parsed_txns[0]["merchant"] == "Amazon"
        assert parsed_txns[0]["V14"] == 0.3
        
        # Verify invalid transaction failure detail
        assert failed_details[0]["raw_input"]["Amount"] == -50.0
        assert "Amount must be greater than 0" in failed_details[0]["error"]

    @pytest.mark.asyncio
    async def test_prediction_correctness(self):
        """Verify that prediction class and score outcomes remain consistent before and after bulk insertion."""
        txns = [VALID_LEGIT, VALID_FRAUD]
        results = predict_batch(txns)
        
        # First should be legit (is_fraud=False), second should be fraud (is_fraud=True)
        assert results[0]["is_fraud"] is False
        assert results[1]["is_fraud"] is True
        assert results[1]["fraud_score"] > 0.8
        assert results[0]["risk_level"] == "LOW"
        assert results[1]["risk_level"] == "HIGH"

    @pytest.mark.asyncio
    async def test_sqlite_bulk_insertion_fallback(self, client):
        """Verify SQLite bulk insertion fallback persists rows correctly and retries one by one on constraints."""
        txns = [
            {
                "V1": -1.3, "V2": 1.2, "V14": 0.3,
                "Amount": 100.0, "Time": 45000.0,
                "merchant": "SQLITE_BULK_TEST"
            },
            {
                "V1": -1.3, "V2": 1.2, "V14": -9.5,
                "Amount": 500.0, "Time": 45000.0,
                "merchant": "SQLITE_BULK_TEST"
            }
        ]
        
        user_id = str(uuid.uuid4())
        summary = await _async_process_batch(txns, user_id)
        print("\nDEBUG SUMMARY:", summary)
        
        assert summary["total"] == 2
        assert summary["processed"] == 2
        assert summary["failed"] == 0
        assert summary["fraud_count"] == 1
        
        # Query DB to check if rows are correctly written
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Transaction).where(Transaction.merchant == "SQLITE_BULK_TEST"))
            db_txns = result.scalars().all()
            assert len(db_txns) == 2
            
            # Clean up
            from sqlalchemy import delete
            await db.execute(delete(Transaction).where(Transaction.merchant == "SQLITE_BULK_TEST"))
            await db.commit()

    def test_chunk_size_configuration(self, monkeypatch):
        """Verify that chunk size can be configured via environment variables."""
        monkeypatch.setenv("BATCH_CHUNK_SIZE", "5")
        chunk_size = int(os.environ.get("BATCH_CHUNK_SIZE", 1000))
        assert chunk_size == 5

    def test_temp_file_cleanup_on_success(self, monkeypatch):
        """Verify that temporary file is successfully unlinked after execution success."""
        csv_content = (
            "Amount,Time,V1,V2,V3,V4,V5,V6,V7,V8,V9,V10,V11,V12,V13,V14,V15,V16,V17,V18,V19,V20,V21,V22,V23,V24,V25,V26,V27,V28\n"
            "100.0,3600,-1.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0\n"
        )
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w", encoding="utf-8") as f:
            f.write(csv_content)
            temp_path = f.name
            
        assert os.path.exists(temp_path)
        
        # Run Celery task wrapper (which handles cleanup)
        from tasks.predict_tasks import process_batch_file
        import asyncio
        monkeypatch.setattr(asyncio, "run", lambda coro: {})
        
        process_batch_file(temp_path, "user_123")
        assert not os.path.exists(temp_path)

    def test_temp_file_cleanup_on_failure(self, monkeypatch):
        """Verify that temporary file is successfully unlinked even after task failure."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w", encoding="utf-8") as f:
            f.write("invalid content")
            temp_path = f.name
            
        assert os.path.exists(temp_path)
        
        from tasks.predict_tasks import process_batch_file
        # Mock _async_process_batch_file to raise an error
        async def mock_fail(*args, **kwargs):
            raise ValueError("Forced test error")
            
        import tasks.predict_tasks
        monkeypatch.setattr(tasks.predict_tasks, "_async_process_batch_file", mock_fail)
        
        with pytest.raises(ValueError):
            process_batch_file(temp_path, "user_123")
            
        assert not os.path.exists(temp_path)

    @pytest.mark.asyncio
    async def test_response_payload_is_bounded(self, monkeypatch, client):
        """Verify that the predictions response list size is capped for large runs (memory safety)."""
        # Create a list of 1005 items
        txns = [VALID_LEGIT] * 1005
        monkeypatch.setenv("BATCH_CHUNK_SIZE", "500")
        
        user_id = str(uuid.uuid4())
        summary = await _async_process_batch(txns, user_id)
        
        # Predictions list must be capped at 100
        assert len(summary["predictions"]) == 100
        assert summary["total"] == 1005
        assert summary["processed"] == 1005
        
        # Clean up database insertions
        async with AsyncSessionLocal() as db:
            from sqlalchemy import delete
            await db.execute(delete(Transaction).where(Transaction.merchant == "Amazon"))
            await db.commit()
