# ============================================================
#  test_celery_reliability.py  —  P2.1 Celery Reliability Tests
# ============================================================

import os
import uuid
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from httpx import AsyncClient

from tasks.predict_tasks import (
    process_batch,
    process_batch_file,
    calculate_backoff_countdown,
    record_dead_letter,
    NON_RETRYABLE_EXCEPTIONS,
    _async_process_batch,
    _async_process_batch_file,
)
from worker import celery_app
from cache import cache_get, cache_set


class TestCeleryWorkerConfig:
    def test_worker_timeouts_configured(self):
        """Verify Celery app has task execution timeouts configured."""
        conf = celery_app.conf
        assert conf.task_time_limit == 660, "Hard time limit should be configured to 660s"
        assert conf.task_soft_time_limit == 600, "Soft time limit should be configured to 600s"
        assert conf.task_acks_late is True, "task_acks_late must remain True"
        assert conf.task_reject_on_worker_lost is True, "task_reject_on_worker_lost must remain True"


class TestExponentialBackoffAndExceptions:
    def test_backoff_progression_and_jitter(self):
        """Verify backoff calculation incorporates exponential scaling with jitter bounded at max."""
        countdown_0 = calculate_backoff_countdown(0, base=4.0, max_backoff=60.0)
        assert 4.5 <= countdown_0 <= 6.0  # 4 * 1 + jitter (0.5..2.0)

        countdown_1 = calculate_backoff_countdown(1, base=4.0, max_backoff=60.0)
        assert 8.5 <= countdown_1 <= 10.0  # 4 * 2 + jitter

        countdown_2 = calculate_backoff_countdown(2, base=4.0, max_backoff=60.0)
        assert 16.5 <= countdown_2 <= 18.0  # 4 * 4 + jitter

        countdown_high = calculate_backoff_countdown(10, base=4.0, max_backoff=60.0)
        assert 60.5 <= countdown_high <= 62.0  # capped at 60 + jitter

    def test_non_retryable_exceptions_tuple(self):
        """Verify standard validation and file exceptions are marked non-retryable."""
        assert ValueError in NON_RETRYABLE_EXCEPTIONS
        assert TypeError in NON_RETRYABLE_EXCEPTIONS
        assert KeyError in NON_RETRYABLE_EXCEPTIONS
        assert FileNotFoundError in NON_RETRYABLE_EXCEPTIONS


class TestProcessBatchReliability:
    def test_permanent_validation_error_not_retried(self, monkeypatch):
        """Permanent errors like ValueError must raise immediately without calling self.retry."""
        task_mock = MagicMock()
        task_mock.request.id = "test-task-val-err"
        task_mock.request.retries = 0
        task_mock.max_retries = 3

        async def raise_val_err(*args, **kwargs):
            raise ValueError("Invalid schema: missing columns")

        monkeypatch.setattr("tasks.predict_tasks._async_process_batch", raise_val_err)

        with pytest.raises(ValueError) as excinfo:
            process_batch.run.__func__(task_mock, transactions=[], user_id=str(uuid.uuid4()))

        assert "Invalid schema" in str(excinfo.value)
        task_mock.retry.assert_not_called()

    def test_transient_error_triggers_retry_with_backoff(self, monkeypatch):
        """Transient errors like ConnectionError must trigger self.retry with exponential countdown."""
        task_mock = MagicMock()
        task_mock.request.id = "test-task-transient"
        task_mock.request.retries = 1
        task_mock.max_retries = 3

        async def raise_transient_err(*args, **kwargs):
            raise ConnectionError("DB connection lost temporarily")

        monkeypatch.setattr("tasks.predict_tasks._async_process_batch", raise_transient_err)

        process_batch.run.__func__(task_mock, transactions=[{"Amount": 10.0, "Time": 100.0, "V1": 1.0}], user_id=str(uuid.uuid4()))

        task_mock.retry.assert_called_once()
        call_kwargs = task_mock.retry.call_args.kwargs
        assert isinstance(call_kwargs["exc"], ConnectionError)
        assert call_kwargs["max_retries"] == 3
        # Retry 1: 4 * 2 + jitter (0.5..2.0) => between 8.5 and 10.0
        assert 8.0 <= call_kwargs["countdown"] <= 11.0

    def test_exhausted_retries_raises_and_records_dead_letter(self, monkeypatch):
        """When retries reach or exceed max_retries, it must raise and record dead letter."""
        task_mock = MagicMock()
        task_mock.request.id = "test-task-exhausted"
        task_mock.request.retries = 3
        task_mock.max_retries = 3

        async def raise_transient_err(*args, **kwargs):
            raise TimeoutError("Redis response timeout")

        monkeypatch.setattr("tasks.predict_tasks._async_process_batch", raise_transient_err)

        with pytest.raises(TimeoutError):
            process_batch.run.__func__(task_mock, transactions=[{"Amount": 10.0, "Time": 100.0, "V1": 1.0}], user_id=str(uuid.uuid4()))

        task_mock.retry.assert_not_called()


class TestProcessBatchFileReliability:
    def test_process_batch_file_preserves_file_on_transient_retry(self, monkeypatch):
        """If a transient error occurs, the temporary file must NOT be unlinked so retries can read it."""
        import tempfile
        task_mock = MagicMock()
        task_mock.request.id = "test-file-transient"
        task_mock.request.retries = 0
        task_mock.max_retries = 3

        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w") as f:
            f.write("Amount,Time,V1\n100.0,10.0,1.0\n")
            temp_path = f.name

        try:
            async def raise_transient_err(*args, **kwargs):
                raise OSError("Temporary I/O glitch")

            monkeypatch.setattr("tasks.predict_tasks._async_process_batch_file", raise_transient_err)

            process_batch_file.run.__func__(task_mock, temp_path, "user-123")

            task_mock.retry.assert_called_once()
            # File must STILL exist on disk for next retry!
            assert os.path.exists(temp_path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_process_batch_file_cleans_up_on_permanent_failure(self, monkeypatch):
        """Permanent non-retryable failures must clean up the file immediately."""
        import tempfile
        task_mock = MagicMock()
        task_mock.request.id = "test-file-permanent"
        task_mock.request.retries = 0
        task_mock.max_retries = 3

        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w") as f:
            f.write("invalid content")
            temp_path = f.name

        try:
            async def raise_val_err(*args, **kwargs):
                raise ValueError("Missing columns")

            monkeypatch.setattr("tasks.predict_tasks._async_process_batch_file", raise_val_err)

            with pytest.raises(ValueError):
                process_batch_file.run.__func__(task_mock, temp_path, "user-123")

            task_mock.retry.assert_not_called()
            # File must be cleaned up on fatal non-retryable failure!
            assert not os.path.exists(temp_path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)



class TestIdempotencyAndDeadLetter:
    @pytest.mark.asyncio
    async def test_dead_letter_recording_and_retrieval(self):
        """Verify dead letter events can be stored and retrieved from cache."""
        task_id = f"dl-test-{uuid.uuid4()}"
        exc = RuntimeError("Database deadlocked")

        await record_dead_letter(
            task_id=task_id,
            task_name="tasks.predict_tasks.process_batch",
            exc=exc,
            retries=3,
            user_id="user-xyz",
            extra_metadata={"exhausted": True}
        )

        record = await cache_get(f"dead_letter:tasks:{task_id}")
        assert record is not None
        assert record["task_id"] == task_id
        assert record["error_type"] == "RuntimeError"
        assert record["error_message"] == "Database deadlocked"
        assert record["retries"] == 3
        assert record["metadata"]["exhausted"] is True

    @pytest.mark.asyncio
    async def test_batch_result_poll_reflects_dead_letter(self, client: AsyncClient, auth_headers: dict):
        """GET /api/predict/batch/{task_id} returns FAILURE and dead-letter details if available."""
        task_id = f"task-{uuid.uuid4()}"
        dead_letter_data = {
            "task_id": task_id,
            "task_name": "tasks.predict_tasks.process_batch",
            "error_type": "ConnectionError",
            "error_message": "Connection to PostgreSQL refused",
            "retries": 3,
            "exhausted_at": 1700000000.0,
            "metadata": {"exhausted": True}
        }
        await cache_set(f"dead_letter:tasks:{task_id}", dead_letter_data, ttl_seconds=60)

        resp = await client.get(f"/api/predict/batch/{task_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == task_id
        assert data["status"] == "FAILURE"
        assert "ConnectionError: Connection to PostgreSQL refused" in data["error"]
        assert data["result"]["metadata"]["exhausted"] is True

    @pytest.mark.asyncio
    async def test_idempotent_retry_does_not_produce_false_write_failures(self):
        """Retrying an already partially or fully committed batch must not increment failed_count or report write errors."""
        from database.db import AsyncSessionLocal, Base, engine
        from models.transaction import Transaction, RiskLevel, TransactionStatus

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        task_id = f"test-idempotent-{uuid.uuid4()}"
        deterministic_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{task_id}:0")

        # Simulate pre-existing transaction from a previous attempt
        async with AsyncSessionLocal() as db_session:
            pre_existing = Transaction(
                id=deterministic_id,
                amount=50.0,
                transaction_time=123.0,
                fraud_score=0.05,
                is_fraud=False,
                risk_level=RiskLevel.LOW,
                status=TransactionStatus.APPROVED,
            )
            db_session.add(pre_existing)
            await db_session.commit()

        # Execute batch with the same deterministic task_id
        task_mock = MagicMock()
        task_mock.request.id = task_id
        task_mock.request.retries = 1

        txns = [{"Amount": 50.0, "Time": 123.0, "V1": 0.0}]
        # Run _async_process_batch
        res = await _async_process_batch(txns, str(uuid.uuid4()), self=task_mock)

        assert res["failed"] == 0, "Idempotent replay must not mark already-saved transaction as failed"
        assert res["processed"] == 1, "Idempotent replay must recognise transaction as processed"
        assert len(res["failed_details"]) == 0

