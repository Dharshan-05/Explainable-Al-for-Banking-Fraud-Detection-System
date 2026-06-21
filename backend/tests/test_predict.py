# ============================================================
#  tests/test_predict.py  —  Prediction Route Tests
# ============================================================

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

# A valid transaction payload with non-zero V14
VALID_LEGIT = {
    "V1": -1.3, "V2": 1.2, "V3": 1.0, "V4": 0.5,
    "V5": -0.1, "V14": 0.3,  # Positive V14 → legit in mock
    "Amount": 150.0, "Time": 45000.0,
    "merchant": "Amazon", "merchant_category": "e-commerce"
}

# Negative V14 < -5 → fraud in mock
VALID_FRAUD = {**VALID_LEGIT, "V14": -9.5, "Amount": 5000.0}

ALL_ZEROS = {
    **{f"V{i}": 0.0 for i in range(1, 29)},
    "Amount": 100.0, "Time": 50000.0,
}

MISSING_V = {"Amount": 100.0, "Time": 50000.0}  # No V features at all


class TestSinglePredict:
    async def test_predict_legit(self, client: AsyncClient, auth_headers: dict):
        resp = await client.post("/api/predict/transaction", json=VALID_LEGIT, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_fraud"] is False
        assert data["risk_level"] == "LOW"
        assert "transaction_id" in data
        assert "top_features" in data
        assert len(data["top_features"]) > 0
        assert data["shap_base_value"] is not None

    async def test_predict_fraud(self, client: AsyncClient, auth_headers: dict):
        resp = await client.post("/api/predict/transaction", json=VALID_FRAUD, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_fraud"] is True
        assert data["risk_level"] == "HIGH"
        assert data["fraud_score"] > 0.9
        assert data["status"] == "flagged"

    async def test_predict_all_zeros_rejected(self, client: AsyncClient, auth_headers: dict):
        """All-zero V-features must return 422."""
        resp = await client.post("/api/predict/transaction", json=ALL_ZEROS, headers=auth_headers)
        assert resp.status_code == 422
        detail = str(resp.json())
        assert "V1" in detail or "non-zero" in detail or "missing" in detail.lower()

    async def test_predict_missing_v_features_rejected(self, client: AsyncClient, auth_headers: dict):
        """Missing all V-features must return 422."""
        resp = await client.post("/api/predict/transaction", json=MISSING_V, headers=auth_headers)
        assert resp.status_code == 422

    async def test_predict_negative_amount_rejected(self, client: AsyncClient, auth_headers: dict):
        """Negative Amount must return 422."""
        bad = {**VALID_LEGIT, "Amount": -50.0}
        resp = await client.post("/api/predict/transaction", json=bad, headers=auth_headers)
        assert resp.status_code == 422

    async def test_predict_unauthenticated(self, client: AsyncClient):
        """No auth token → 401."""
        resp = await client.post("/api/predict/transaction", json=VALID_LEGIT)
        assert resp.status_code == 401

    async def test_predict_response_structure(self, client: AsyncClient, auth_headers: dict):
        """Ensure all required fields are present in the response."""
        resp = await client.post("/api/predict/transaction", json=VALID_LEGIT, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        required_fields = [
            "transaction_id", "fraud_score", "fraud_percentage", "is_fraud",
            "risk_level", "risk_color", "explanation", "top_features",
            "shap_base_value", "status"
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"


class TestBatchPredict:
    @pytest.mark.asyncio
    async def test_async_process_batch_success(self, client: AsyncClient):
        from tasks.predict_tasks import _async_process_batch
        import uuid
        
        txns = [
            {
                "V1": -1.3, "V2": 1.2, "V14": 0.3,
                "Amount": 100.0, "Time": 45000.0,
            },
            {
                "V1": -1.3, "V2": 1.2, "V14": -9.5,  # Fraud in mock (V14 < -5)
                "Amount": 500.0, "Time": 45000.0,
            }
        ]
        
        user_id = str(uuid.uuid4())
        summary = await _async_process_batch(txns, user_id)
        
        assert summary["total"] == 2
        assert summary["processed"] == 2
        assert summary["failed"] == 0
        assert summary["fraud_count"] == 1
        assert "duration" in summary
        assert len(summary["predictions"]) == 2
        assert len(summary["failed_details"]) == 0
        
        # Verify database inserts
        from database.db import AsyncSessionLocal
        from sqlalchemy import select
        from models.transaction import Transaction
        
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Transaction).where(Transaction.amount == 500.0))
            txn = result.scalar_one_or_none()
            assert txn is not None
            assert txn.is_fraud is True

    @pytest.mark.asyncio
    async def test_async_process_batch_with_failures(self, client: AsyncClient):
        from tasks.predict_tasks import _async_process_batch
        import uuid
        
        txns = [
            {
                "V1": -1.3, "V2": 1.2, "V14": 0.3,
                "Amount": 100.0, "Time": 45000.0,
            },
            {
                # Negative Amount -> causes validation exception (ValueError) in ML predict
                "V1": -1.3, "V2": 1.2, "V14": 0.3,
                "Amount": -50.0, "Time": 45000.0,
            }
        ]
        
        user_id = str(uuid.uuid4())
        summary = await _async_process_batch(txns, user_id)
        
        assert summary["total"] == 2
        assert summary["processed"] == 1
        assert summary["failed"] == 1
        assert summary["fraud_count"] == 0
        assert len(summary["predictions"]) == 1
        assert len(summary["failed_details"]) == 1
        assert "Prediction error" in summary["failed_details"][0]["error"]

    @pytest.mark.asyncio
    async def test_async_process_batch_chunking_and_progress(self, client: AsyncClient, monkeypatch):
        """Verify chunking and task progress updates in _async_process_batch."""
        from tasks.predict_tasks import _async_process_batch
        import uuid

        # Create a list of 5 mock transactions
        txns = [
            {
                "V1": -1.3, "V2": 1.2, "V14": 0.3,
                "Amount": 100.0, "Time": 45000.0,
            }
            for _ in range(5)
        ]

        # Use a mock Celery task self object to record updates
        updates = []
        class MockTask:
            def update_state(self, state, meta):
                updates.append((state, meta))

        # Set chunk size to 2 using monkeypatch env var
        monkeypatch.setenv("BATCH_CHUNK_SIZE", "2")

        mock_self = MockTask()
        user_id = str(uuid.uuid4())
        summary = await _async_process_batch(txns, user_id, self=mock_self)

        # Check total records and processed
        assert summary["total"] == 5
        assert summary["processed"] == 5
        assert summary["failed"] == 0

        # We have 5 records chunked by 2 -> 3 chunks (chunk 1: 2, chunk 2: 2, chunk 3: 1)
        assert len(updates) == 3
        # First progress update metadata
        assert updates[0][0] == "PROGRESS"
        assert updates[0][1]["current_chunk"] == 1
        assert updates[0][1]["total_chunks"] == 3
        assert updates[0][1]["processed"] == 2

        # Last progress update metadata
        assert updates[2][1]["current_chunk"] == 3
        assert updates[2][1]["total_chunks"] == 3
        assert updates[2][1]["processed"] == 5

    @pytest.mark.asyncio
    async def test_async_process_batch_memory_safety(self, client: AsyncClient, monkeypatch):
        """Verify memory safety limits predictions list size for very large batches."""
        from tasks.predict_tasks import _async_process_batch
        import uuid
        import ml.predict

        # Mock predict_batch to be extremely fast and return standard responses
        def mock_predict_batch(chunk, *args, **kwargs):
            return [
                {
                    "fraud_score": 0.1,
                    "fraud_percentage": 10.0,
                    "is_fraud": False,
                    "risk_level": "LOW",
                    "risk_color": "#10b981",
                    "explanation": "Mocked",
                    "top_features": [],
                    "all_shap_values": {},
                    "shap_base_value": 0.0
                }
                for _ in chunk
            ]
        monkeypatch.setattr(ml.predict, "predict_batch", mock_predict_batch)

        # Create 1005 items
        txns = [
            {
                "V1": -1.3, "V2": 1.2, "V14": 0.3,
                "Amount": 100.0, "Time": 45000.0,
            }
            for _ in range(1005)
        ]
        # We need a large chunk size to run quickly (e.g. 500)
        monkeypatch.setenv("BATCH_CHUNK_SIZE", "500")

        user_id = str(uuid.uuid4())
        summary = await _async_process_batch(txns, user_id)

        assert summary["total"] == 1005
        assert summary["processed"] == 1005
        # The predictions list should be capped at 100 (for memory safety)
        assert len(summary["predictions"]) == 100


class TestBatchPredictFile:
    @pytest.mark.asyncio
    async def test_batch_file_route_success(self, client: AsyncClient, auth_headers: dict, monkeypatch):
        from tasks.predict_tasks import process_batch_file
        class MockTask:
            id = "mock-task-123"
        monkeypatch.setattr(process_batch_file, "delay", lambda *args, **kwargs: MockTask())

        # Valid CSV data
        csv_content = (
            "Amount,Time,V1,V2,V3,V4,V5,V6,V7,V8,V9,V10,V11,V12,V13,V14,V15,V16,V17,V18,V19,V20,V21,V22,V23,V24,V25,V26,V27,V28\n"
            "100.0,3600,-1.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0\n"
        )
        files = {"file": ("test.csv", csv_content.encode("utf-8"), "text/csv")}
        
        resp = await client.post("/api/predict/batch-file", files=files, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "mock-task-123"
        assert data["status"] == "PENDING"

    @pytest.mark.asyncio
    async def test_batch_file_route_invalid_type(self, client: AsyncClient, auth_headers: dict):
        files = {"file": ("test.txt", b"some plain text", "text/plain")}
        resp = await client.post("/api/predict/batch-file", files=files, headers=auth_headers)
        assert resp.status_code == 400
        assert "Only CSV files are supported" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_batch_file_route_oversized(self, client: AsyncClient, auth_headers: dict, monkeypatch):
        from config import settings
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE", 10) # 10 bytes limit
        
        csv_content = "Amount,Time,V1\n100.0,3600,1.0\n"
        files = {"file": ("test.csv", csv_content.encode("utf-8"), "text/csv")}
        resp = await client.post("/api/predict/batch-file", files=files, headers=auth_headers)
        assert resp.status_code == 413
        assert "Payload Too Large" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_async_process_batch_file_missing_columns(self):
        from tasks.predict_tasks import _async_process_batch_file
        import tempfile
        import os
        
        # Missing Amount and Time columns
        csv_content = "V1,V2\n1.0,2.0\n"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w", encoding="utf-8") as f:
            f.write(csv_content)
            temp_path = f.name
            
        try:
            with pytest.raises(ValueError) as excinfo:
                await _async_process_batch_file(temp_path, "user_123")
            assert "missing required columns" in str(excinfo.value)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_async_process_batch_file_success(self, client: AsyncClient, monkeypatch):
        from tasks.predict_tasks import _async_process_batch_file
        import tempfile
        import os
        import uuid
        
        # Mock predict_batch
        import ml.predict
        def mock_predict_batch(chunk, *args, **kwargs):
            return [{
                "fraud_score": 0.1,
                "fraud_percentage": 10.0,
                "is_fraud": False,
                "risk_level": "LOW",
                "risk_color": "#10b981",
                "explanation": "Legit",
                "top_features": [],
                "all_shap_values": {"V1": 0.1},
                "shap_base_value": 0.0
            } for _ in chunk]
        monkeypatch.setattr(ml.predict, "predict_batch", mock_predict_batch)

        csv_content = (
            "Amount,Time,V1,V2,V3,V4,V5,V6,V7,V8,V9,V10,V11,V12,V13,V14,V15,V16,V17,V18,V19,V20,V21,V22,V23,V24,V25,V26,V27,V28\n"
            "150.0,45000,-1.3,1.2,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.3,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0\n"
        )
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w", encoding="utf-8") as f:
            f.write(csv_content)
            temp_path = f.name
            
        try:
            updates = []
            class MockTask:
                def update_state(self, state, meta):
                    updates.append((state, meta))
            
            user_id = str(uuid.uuid4())
            res = await _async_process_batch_file(temp_path, user_id, self=MockTask())
            
            assert res["total"] == 1
            assert res["processed"] == 1
            assert res["failed"] == 0
            assert len(updates) > 0
            assert updates[-1][1]["processed"] == 1
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_async_process_batch_file_with_failures(self, client: AsyncClient, monkeypatch):
        from tasks.predict_tasks import _async_process_batch_file
        import tempfile
        import os
        import uuid
        
        # Valid row plus invalid row (negative amount)
        csv_content = (
            "Amount,Time,V1,V2,V3,V4,V5,V6,V7,V8,V9,V10,V11,V12,V13,V14,V15,V16,V17,V18,V19,V20,V21,V22,V23,V24,V25,V26,V27,V28\n"
            "150.0,45000,-1.3,1.2,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.3,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0\n"
            "-50.0,45000,-1.3,1.2,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.3,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0\n"
        )
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w", encoding="utf-8") as f:
            f.write(csv_content)
            temp_path = f.name
            
        try:
            user_id = str(uuid.uuid4())
            res = await _async_process_batch_file(temp_path, user_id)
            
            assert res["total"] == 2
            assert res["processed"] == 1
            assert res["failed"] == 1
            assert len(res["failed_details"]) == 1
            assert "Amount must be greater than 0" in res["failed_details"][0]["error"]
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_process_batch_file_task_temp_cleanup_on_success(self, monkeypatch):
        from tasks.predict_tasks import process_batch_file
        import tempfile
        import os
        import asyncio
        
        # Write dummy CSV
        csv_content = (
            "Amount,Time,V1,V2,V3,V4,V5,V6,V7,V8,V9,V10,V11,V12,V13,V14,V15,V16,V17,V18,V19,V20,V21,V22,V23,V24,V25,V26,V27,V28\n"
            "100.0,3600,-1.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0\n"
        )
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w", encoding="utf-8") as f:
            f.write(csv_content)
            temp_path = f.name
            
        # Mock asyncio.run to bypass loop conflict
        monkeypatch.setattr(asyncio, "run", lambda coro: {})
        
        # Execute Celery task synchronously
        process_batch_file(temp_path, "user_123")
        
        # Assert temporary file was deleted
        assert not os.path.exists(temp_path)

    @pytest.mark.asyncio
    async def test_process_batch_file_task_temp_cleanup_on_failure(self, monkeypatch):
        from tasks.predict_tasks import process_batch_file
        import tempfile
        import os
        import asyncio
        
        # Write dummy CSV
        csv_content = "Amount,Time,V1\n100.0,3600,1.0\n"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w", encoding="utf-8") as f:
            f.write(csv_content)
            temp_path = f.name
            
        # Mock asyncio.run to raise exception
        def mock_fail(coro):
            raise ValueError("Forced error for testing cleanup")
        monkeypatch.setattr(asyncio, "run", mock_fail)
        
        # Execute Celery task and check exception
        with pytest.raises(ValueError):
            process_batch_file(temp_path, "user_123")
            
        # Assert temporary file was still deleted in finally block
        assert not os.path.exists(temp_path)

    @pytest.mark.asyncio
    async def test_existing_json_batch_route_works(self, client: AsyncClient, auth_headers: dict, monkeypatch):
        from tasks.predict_tasks import process_batch
        class MockTask:
            id = "mock-json-task-456"
        monkeypatch.setattr(process_batch, "delay", lambda *args, **kwargs: MockTask())
        
        payload = {
            "transactions": [
                {
                    "V1": -1.3, "V2": 1.2, "V14": 0.3,
                    "Amount": 100.0, "Time": 45000.0,
                }
            ]
        }
        resp = await client.post("/api/predict/batch", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "mock-json-task-456"
        assert data["status"] == "PENDING"
        assert data["total"] == 1


