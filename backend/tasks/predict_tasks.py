# ============================================================
#  tasks/predict_tasks.py  —  Async Batch Prediction
#  Celery task that processes a list of transactions in the
#  background, writes results to Postgres, and returns a
#  summary dict consumable via GET /api/predict/batch/{task_id}
# ============================================================

import uuid
import asyncio
import time
import os
import random
import json
import logging
from celery.exceptions import MaxRetriesExceededError
from worker import celery_app
from services.audit_service import log_audit_event
from database.db import AsyncSessionLocal
from models.user import User
import pandas as pd
import numpy as np
from sqlalchemy import insert, select
from cache import cache_set

logger = logging.getLogger("tasks")

# Exceptions that indicate permanent failure and must NOT be retried
NON_RETRYABLE_EXCEPTIONS = (
    ValueError,
    TypeError,
    KeyError,
    FileNotFoundError,
    pd.errors.EmptyDataError,
    pd.errors.ParserError,
)


def calculate_backoff_countdown(retries: int, base: float = 4.0, max_backoff: float = 60.0) -> float:
    """
    Calculate bounded exponential backoff with additive jitter.
    Formula: min(max_backoff, (base * (2 ** retries))) + uniform(0.5, 2.0)
    """
    backoff = min(max_backoff, base * (2 ** retries))
    jitter = random.uniform(0.5, 2.0)
    return round(backoff + jitter, 2)


async def record_dead_letter(
    task_id: str,
    task_name: str,
    exc: Exception,
    retries: int,
    user_id: str | None = None,
    extra_metadata: dict | None = None
) -> None:
    """
    Record dead-letter event in Redis with TTL when retries are exhausted
    or a fatal non-retryable error terminates the task.
    """
    dead_letter_data = {
        "task_id": task_id,
        "task_name": task_name,
        "error_type": exc.__class__.__name__,
        "error_message": str(exc),
        "retries": retries,
        "user_id": user_id,
        "exhausted_at": time.time(),
        "metadata": extra_metadata or {}
    }
    key = f"dead_letter:tasks:{task_id}"
    logger.error(
        f"Task {task_id} dead-lettered: {exc.__class__.__name__}: {str(exc)}",
        extra={"event_type": "task_dead_letter", "dead_letter": dead_letter_data}
    )
    # Store dead-letter details in Redis for 7 days (604800s)
    try:
        await cache_set(key, dead_letter_data, ttl_seconds=604800)
    except Exception as e:
        logger.warning(f"Failed to record dead letter in Redis for {task_id}: {e}")


from concurrent.futures import ThreadPoolExecutor

def record_dead_letter_sync(
    task_id: str,
    task_name: str,
    exc: Exception,
    retries: int,
    user_id: str | None = None,
    extra_metadata: dict | None = None
) -> None:
    """Synchronous caller for record_dead_letter that deterministically executes across event loop contexts."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        # Running inside an active loop (e.g. pytest or async test harness):
        # Run in a dedicated worker thread with its own loop to guarantee completion
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(
                lambda: asyncio.run(
                    record_dead_letter(task_id, task_name, exc, retries, user_id, extra_metadata)
                )
            ).result()
    else:
        try:
            cur_loop = asyncio.get_event_loop()
            if not cur_loop.is_closed():
                cur_loop.run_until_complete(
                    record_dead_letter(task_id, task_name, exc, retries, user_id, extra_metadata)
                )
            else:
                asyncio.run(
                    record_dead_letter(task_id, task_name, exc, retries, user_id, extra_metadata)
                )
        except RuntimeError:
            asyncio.run(
                record_dead_letter(task_id, task_name, exc, retries, user_id, extra_metadata)
            )



@celery_app.task(bind=True, name="tasks.predict_tasks.process_batch")
def process_batch(self, transactions: list, user_id: str) -> dict:
    """
    Process a batch of raw transaction dicts using the XGBoost model.

    Args:
        transactions: List of dicts matching TransactionInput schema.
        user_id: UUID string of the authenticated user (for DB linking).

    Returns:
        Summary dict containing: total, processed, failed, fraud_count, duration, predictions, failed_details.
    """
    task_id = self.request.id if (hasattr(self, "request") and self.request and hasattr(self.request, "id")) else "unknown"
    current_retries = self.request.retries if (hasattr(self, "request") and self.request and hasattr(self.request, "retries")) else 0
    max_retries = getattr(self, "max_retries", 3)

    try:
        return asyncio.run(_async_process_batch(transactions, user_id, self))
    except NON_RETRYABLE_EXCEPTIONS as fatal_exc:
        logger.error(
            f"Permanent failure in process_batch (task {task_id}): {fatal_exc.__class__.__name__}: {str(fatal_exc)}"
        )
        try:
            record_dead_letter_sync(
                task_id=task_id,
                task_name="tasks.predict_tasks.process_batch",
                exc=fatal_exc,
                retries=current_retries,
                user_id=user_id,
                extra_metadata={"permanent": True, "total_records": len(transactions)}
            )
        except Exception as dl_err:
            logger.warning(f"Could not write dead letter for permanent failure: {dl_err}")
        raise fatal_exc
    except Exception as exc:
        if current_retries >= max_retries:
            logger.error(
                f"Retries exhausted for process_batch (task {task_id}) after {current_retries} attempts."
            )
            try:
                record_dead_letter_sync(
                    task_id=task_id,
                    task_name="tasks.predict_tasks.process_batch",
                    exc=exc,
                    retries=current_retries,
                    user_id=user_id,
                    extra_metadata={"exhausted": True, "total_records": len(transactions)}
                )
            except Exception as dl_err:
                logger.warning(f"Could not write dead letter on exhaustion: {dl_err}")
            raise exc

        countdown = calculate_backoff_countdown(current_retries)
        logger.warning(
            f"Transient failure in process_batch (task {task_id}, retry {current_retries + 1}/{max_retries}). "
            f"Retrying in {countdown}s. Error: {exc.__class__.__name__}: {str(exc)}"
        )
        self.retry(exc=exc, countdown=countdown, max_retries=max_retries)


async def _async_process_batch(transactions: list, user_id: str, self=None) -> dict:
    """Inner async logic so we can use SQLAlchemy async sessions."""
    start_time = time.time()
    from ml.predict import predict_batch
    from models.transaction import Transaction, RiskLevel, TransactionStatus
    import os

    task_id = str(uuid.uuid4())
    if self and hasattr(self, "request") and self.request and hasattr(self.request, "id"):
        task_id = self.request.id

    actor_uuid = None
    role = None
    if user_id:
        try:
            actor_uuid = uuid.UUID(user_id)
            async with AsyncSessionLocal() as db:
                user = await db.get(User, actor_uuid)
                if user:
                    role = user.role.value if hasattr(user.role, "value") else str(user.role)
        except Exception:
            pass

    total_records = len(transactions)
    logger.info(
        "Batch task started",
        extra={"event_type": "batch_started", "task_id": task_id, "user_id": user_id, "total": total_records}
    )

    async with AsyncSessionLocal() as db:
        await log_audit_event(
            action="batch_started",
            resource_type="transaction",
            resource_id=task_id,
            status="success",
            actor_user_id=actor_uuid,
            actor_role=role,
            metadata={"task_id": task_id, "total": total_records},
            db=db
        )

    # Chunk size logic (default 10000)
    chunk_size = int(os.environ.get("BATCH_CHUNK_SIZE", 10000))

    predictions = []
    failed_details = []
    fraud_count = 0
    defer_shap = total_records > 1000

    risk_map = {
        "LOW":    RiskLevel.LOW,
        "MEDIUM": RiskLevel.MEDIUM,
        "HIGH":   RiskLevel.HIGH,
    }

    # Split transactions into chunks
    chunks = [transactions[i:i + chunk_size] for i in range(0, total_records, chunk_size)]
    total_chunks = len(chunks)

    processed_count = 0
    failed_count = 0

    try:
        for chunk_idx, chunk in enumerate(chunks, 1):
            # 1. Run predictions on this chunk using vectorized predict_batch
            try:
                results = predict_batch(chunk, defer_shap=defer_shap)
                if defer_shap and results:
                    fraud_indices = [i for i, r in enumerate(results) if r and not r.get("error") and r.get("is_fraud")]
                    if fraud_indices:
                        fraud_subset = [chunk[i] for i in fraud_indices]
                        try:
                            fraud_results = predict_batch(fraud_subset, defer_shap=False)
                            for idx, res in zip(fraud_indices, fraud_results):
                                if res and not res.get("error"):
                                    results[idx] = res
                        except Exception as shap_exc:
                            logger.warning(f"Failed to calculate SHAP for fraud subset in chunk: {shap_exc}")
            except Exception as e:
                # Entire chunk prediction failed
                for raw in chunk:
                    if len(failed_details) < 100:
                        failed_details.append({
                            "error": f"Prediction error: {str(e)}",
                            "raw_input": raw
                        })
                    failed_count += 1
                # Update Celery progress state
                elapsed = time.time() - start_time
                logger.info(
                    f"Batch task chunk {chunk_idx}/{total_chunks} processed",
                    extra={
                        "event_type": "chunk_progress",
                        "task_id": task_id,
                        "current_chunk": chunk_idx,
                        "total_chunks": total_chunks,
                        "processed": processed_count,
                        "failed": failed_count,
                    }
                )
                if self:
                    self.update_state(
                        state="PROGRESS",
                        meta={
                            "status": "processing",
                            "total": total_records,
                            "processed": processed_count,
                            "failed": failed_count,
                            "fraud_count": fraud_count,
                            "current_chunk": chunk_idx,
                            "total_chunks": total_chunks,
                            "duration": round(elapsed, 4)
                        }
                    )
                continue

            chunk_valid_txns = []
            chunk_predictions = []
            chunk_fraud_count = 0

            # Build transaction data for this chunk
            chunk_base_offset = (chunk_idx - 1) * chunk_size
            for item_idx, (raw, result) in enumerate(zip(chunk, results)):
                global_record_index = chunk_base_offset + item_idx
                if result is None:
                    if len(failed_details) < 100:
                        failed_details.append({
                            "error": "Prediction error: Unknown error",
                            "raw_input": raw
                        })
                    failed_count += 1
                    continue
                if "error" in result:
                    if len(failed_details) < 100:
                        failed_details.append({
                            "error": f"Prediction error: {result['error']}",
                            "raw_input": raw
                        })
                    failed_count += 1
                    continue

                try:
                    status_val = TransactionStatus.flagged if result["is_fraud"] else TransactionStatus.pending
                    # Deterministic UUID per batch task and item index to ensure idempotency across retries
                    txn_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{task_id}:{global_record_index}")
                    chunk_valid_txns.append((txn_id, raw, result, status_val))
                    if result["is_fraud"]:
                        chunk_fraud_count += 1
                except Exception as e:
                    if len(failed_details) < 100:
                        failed_details.append({
                            "error": f"Database preparation error: {str(e)}",
                            "raw_input": raw
                        })
                    failed_count += 1

            # Bulk insert using SQLAlchemy Core
            async with AsyncSessionLocal() as db:
                if chunk_valid_txns:
                    try:
                        insert_mappings = []
                        for txn_id, raw, result, status_val in chunk_valid_txns:
                            insert_mappings.append({
                                "id": txn_id,
                                "amount": raw.get("Amount", 0.0),
                                "merchant": raw.get("merchant"),
                                "merchant_category": raw.get("merchant_category"),
                                "location": raw.get("location"),
                                "card_last4": raw.get("card_last4"),
                                "transaction_time": raw.get("Time", 0.0),
                                "v_features": {f"V{i}": raw.get(f"V{i}", 0.0) for i in range(1, 29)},
                                "fraud_score": result["fraud_score"],
                                "is_fraud": result["is_fraud"],
                                "risk_level": risk_map[result["risk_level"]],
                                "explanation": result["explanation"],
                                "top_features": result["top_features"],
                                "shap_values": result["all_shap_values"],
                                "status": status_val,
                            })
                        await db.execute(insert(Transaction), insert_mappings)
                        await db.commit()

                        # Build predictions response payload
                        for txn_id, raw, result, status_val in chunk_valid_txns:
                            chunk_predictions.append({
                                "transaction_id":   str(txn_id),
                                "fraud_score":      result["fraud_score"],
                                "fraud_percentage": result["fraud_percentage"],
                                "is_fraud":         result["is_fraud"],
                                "risk_level":       result["risk_level"],
                                "risk_color":       result["risk_color"],
                                "explanation":      result["explanation"],
                                "status":           status_val.value,
                            })
                        fraud_count += chunk_fraud_count
                        processed_count += len(chunk_predictions)

                    except Exception as commit_exc:
                        await db.rollback()
                        # Retry one by one if bulk write fails (SQLite / constraint failures)
                        for txn_id, raw, result, status_val in chunk_valid_txns:
                            try:
                                txn_obj = Transaction(
                                    id                 = txn_id,
                                    amount             = raw.get("Amount", 0.0),
                                    merchant           = raw.get("merchant"),
                                    merchant_category  = raw.get("merchant_category"),
                                    location           = raw.get("location"),
                                    card_last4         = raw.get("card_last4"),
                                    transaction_time   = raw.get("Time", 0.0),
                                    v_features         = {f"V{i}": raw.get(f"V{i}", 0.0) for i in range(1, 29)},
                                    fraud_score        = result["fraud_score"],
                                    is_fraud           = result["is_fraud"],
                                    risk_level         = risk_map[result["risk_level"]],
                                    explanation        = result["explanation"],
                                    top_features       = result["top_features"],
                                    shap_values        = result["all_shap_values"],
                                    status             = status_val,
                                )
                                db.add(txn_obj)
                                await db.commit()
                                chunk_predictions.append({
                                    "transaction_id":   str(txn_id),
                                    "fraud_score":      result["fraud_score"],
                                    "fraud_percentage": result["fraud_percentage"],
                                    "is_fraud":         result["is_fraud"],
                                    "risk_level":       result["risk_level"],
                                    "risk_color":       result["risk_color"],
                                    "explanation":      result["explanation"],
                                    "status":           status_val.value,
                                })
                                if result["is_fraud"]:
                                    fraud_count += 1
                                processed_count += 1
                            except Exception as ind_exc:
                                await db.rollback()
                                # Check for idempotent replay: if record already exists, treat as already committed
                                try:
                                    existing = await db.get(Transaction, txn_id)
                                except Exception:
                                    existing = None

                                if existing is not None:
                                    chunk_predictions.append({
                                        "transaction_id":   str(txn_id),
                                        "fraud_score":      result["fraud_score"],
                                        "fraud_percentage": result["fraud_percentage"],
                                        "is_fraud":         result["is_fraud"],
                                        "risk_level":       result["risk_level"],
                                        "risk_color":       result["risk_color"],
                                        "explanation":      result["explanation"],
                                        "status":           status_val.value,
                                    })
                                    if result["is_fraud"]:
                                        fraud_count += 1
                                    processed_count += 1
                                else:
                                    if len(failed_details) < 100:
                                        failed_details.append({
                                            "error": f"Database write error: {str(ind_exc)}",
                                            "raw_input": {
                                                "Amount": raw.get("Amount"),
                                                "merchant": raw.get("merchant"),
                                                "Time": raw.get("Time")
                                            }
                                        })
                                    failed_count += 1

            # Memory safety: for very large uploads, only return first 100 predictions
            if total_records <= 1000:
                predictions.extend(chunk_predictions)
            else:
                if len(predictions) < 100:
                    predictions.extend(chunk_predictions[:100 - len(predictions)])

            # Update Celery state after each chunk
            elapsed = time.time() - start_time
            records_per_sec = round((processed_count + failed_count) / elapsed, 2) if elapsed > 0 else 0.0
            logger.info(
                f"Batch task chunk {chunk_idx}/{total_chunks} processed",
                extra={
                    "event_type": "chunk_progress",
                    "task_id": task_id,
                    "current_chunk": chunk_idx,
                    "total_chunks": total_chunks,
                    "processed": processed_count,
                    "failed": failed_count,
                }
            )
            if self:
                self.update_state(
                    state="PROGRESS",
                    meta={
                        "status": "processing",
                        "total": total_records,
                        "processed": processed_count,
                        "failed": failed_count,
                        "fraud_count": fraud_count,
                        "current_chunk": chunk_idx,
                        "total_chunks": total_chunks,
                        "duration": round(elapsed, 4),
                        "records_per_second": records_per_sec
                    }
                )

        duration = time.time() - start_time
        logger.info(
            "Batch task completed",
            extra={
                "event_type": "batch_completed",
                "task_id": task_id,
                "processed": processed_count,
                "failed": failed_count,
                "fraud_count": fraud_count
            }
        )
        async with AsyncSessionLocal() as db:
            await log_audit_event(
                action="batch_completed",
                resource_type="transaction",
                resource_id=task_id,
                status="success",
                actor_user_id=actor_uuid,
                actor_role=role,
                metadata={
                    "task_id": task_id,
                    "total": total_records,
                    "processed": processed_count,
                    "failed": failed_count,
                    "fraud_count": fraud_count
                },
                db=db
            )

        return {
            "total":          total_records,
            "processed":      processed_count,
            "failed":         failed_count,
            "fraud_count":    fraud_count,
            "duration":       round(duration, 4),
            "predictions":    predictions,
            "failed_details": failed_details,
        }
    except Exception as exc:
        logger.error(
            "Batch task failed",
            exc_info=True,
            extra={"event_type": "batch_failed", "task_id": task_id, "error_category": exc.__class__.__name__}
        )
        async with AsyncSessionLocal() as db:
            await log_audit_event(
                action="batch_failed",
                resource_type="transaction",
                resource_id=task_id,
                status="failure",
                actor_user_id=actor_uuid,
                actor_role=role,
                metadata={"task_id": task_id, "error_category": exc.__class__.__name__},
                db=db
            )
        raise exc


@celery_app.task(bind=True, name="tasks.predict_tasks.process_batch_file")
def process_batch_file(self, file_path: str, user_id: str) -> dict:
    """
    Celery task that streams a CSV file from disk, runs predictions in chunks,
    saves the transactions to the database, updates the progress metadata, and
    cleans up the temporary CSV file upon completion or final exhaustion/failure.
    """
    import os
    task_id = self.request.id if (hasattr(self, "request") and self.request and hasattr(self.request, "id")) else "unknown"
    current_retries = self.request.retries if (hasattr(self, "request") and self.request and hasattr(self.request, "retries")) else 0
    max_retries = getattr(self, "max_retries", 3)
    cleanup_file = True

    try:
        return asyncio.run(_async_process_batch_file(file_path, user_id, self))
    except NON_RETRYABLE_EXCEPTIONS as fatal_exc:
        logger.error(
            f"Permanent failure in process_batch_file (task {task_id}): {fatal_exc.__class__.__name__}: {str(fatal_exc)}"
        )
        try:
            record_dead_letter_sync(
                task_id=task_id,
                task_name="tasks.predict_tasks.process_batch_file",
                exc=fatal_exc,
                retries=current_retries,
                user_id=user_id,
                extra_metadata={"permanent": True, "file_path": file_path}
            )
        except Exception as dl_err:
            logger.warning(f"Could not write dead letter for permanent file failure: {dl_err}")
        raise fatal_exc
    except Exception as exc:
        if current_retries >= max_retries:
            logger.error(
                f"Retries exhausted for process_batch_file (task {task_id}) after {current_retries} attempts."
            )
            try:
                record_dead_letter_sync(
                    task_id=task_id,
                    task_name="tasks.predict_tasks.process_batch_file",
                    exc=exc,
                    retries=current_retries,
                    user_id=user_id,
                    extra_metadata={"exhausted": True, "file_path": file_path}
                )
            except Exception as dl_err:
                logger.warning(f"Could not write dead letter on file task exhaustion: {dl_err}")
            raise exc

        # Transient failure: keep the temporary file on disk so the subsequent retry can read it!
        cleanup_file = False
        countdown = calculate_backoff_countdown(current_retries)
        logger.warning(
            f"Transient failure in process_batch_file (task {task_id}, retry {current_retries + 1}/{max_retries}). "
            f"Retrying in {countdown}s. Error: {exc.__class__.__name__}: {str(exc)}"
        )
        self.retry(exc=exc, countdown=countdown, max_retries=max_retries)
    finally:
        if cleanup_file and os.path.exists(file_path):
            try:
                os.unlink(file_path)
            except Exception:
                pass


def validate_chunk_pandas(chunk_df: pd.DataFrame, raw_rows: list, headers: list) -> tuple:
    # 1. Normalize column names to lowercase for uniform lookup
    df_lower = chunk_df.copy()
    df_lower.columns = [c.strip().lower() for c in df_lower.columns]
    
    # Get Amount and Time column names
    amount_col = next((c for c in chunk_df.columns if c.strip().lower() == "amount"), "Amount")
    time_col = next((c for c in chunk_df.columns if c.strip().lower() == "time"), "Time")
    
    # 2. Coerce Amount and Time to numeric.
    amount_numeric = pd.to_numeric(df_lower["amount"], errors='coerce')
    time_numeric = pd.to_numeric(df_lower["time"], errors='coerce')
    
    # Validation masks
    amount_valid = (
        amount_numeric.notna() &
        (~np.isinf(amount_numeric)) &
        (amount_numeric > 0)
    )
    
    time_valid = (
        time_numeric.notna() &
        (~np.isinf(time_numeric)) &
        (time_numeric >= 0)
    )
    
    # 3. Check V features
    v_cols = [f"v{i}" for i in range(1, 29)]
    for col in v_cols:
        if col not in df_lower.columns:
            df_lower[col] = np.nan
            
    v_df = df_lower[v_cols].apply(pd.to_numeric, errors='coerce')
    
    # At least one V feature must be provided and non-zero
    v_not_null = v_df.notna() & (~np.isinf(v_df))
    v_non_zero = v_df != 0.0
    v_valid = (v_not_null & v_non_zero).any(axis=1)
    
    # Overall valid mask
    valid_mask = amount_valid & time_valid & v_valid
    
    # Extract valid rows
    df_valid = df_lower[valid_mask].copy()
    
    parsed_txns = []
    failed_details = []
    
    if not df_valid.empty:
        v_df_valid = v_df[valid_mask].fillna(0.0)
        v_df_valid = v_df_valid.replace([np.inf, -np.inf], 0.0)
        for col in v_cols:
            df_valid[col] = v_df_valid[col]
            
        for col_key in ["merchant", "merchant_category", "location", "card_last4"]:
            match = next((c for c in chunk_df.columns if c.strip().lower() == col_key), None)
            if match:
                df_valid[col_key] = chunk_df.loc[valid_mask, match].where(pd.notna(chunk_df.loc[valid_mask, match]), None)
            else:
                df_valid[col_key] = None
                
        rename_dict = {"amount": "Amount", "time": "Time"}
        for i in range(1, 29):
            rename_dict[f"v{i}"] = f"V{i}"
        df_valid = df_valid.rename(columns=rename_dict)
        
        keep_cols = ["Amount", "Time", "merchant", "merchant_category", "location", "card_last4"] + [f"V{i}" for i in range(1, 29)]
        df_valid = df_valid[keep_cols]
        parsed_txns = df_valid.to_dict(orient="records")
        
    # Process invalid rows
    invalid_indices = chunk_df.index[~valid_mask]
    for idx in invalid_indices:
        raw_row = raw_rows[idx - chunk_df.index[0]]
        
        amt_val = amount_numeric.loc[idx]
        t_val = time_numeric.loc[idx]
        v_row = v_df.loc[idx]
        
        raw_amt_str = str(raw_row.get(amount_col, "0"))
        raw_time_str = str(raw_row.get(time_col, "0"))
        
        if pd.isna(amt_val) or np.isinf(amt_val):
            err_msg = f"Invalid Amount: {raw_amt_str}"
        elif amt_val <= 0:
            err_msg = "Amount must be greater than 0"
        elif pd.isna(t_val) or np.isinf(t_val):
            err_msg = f"Invalid Time: {raw_time_str}"
        elif t_val < 0:
            err_msg = "Time must be non-negative"
        else:
            v_present = v_row.notna().any()
            v_nz = (v_row != 0.0).any()
            if not v_present or not v_nz:
                err_msg = "At least one PCA feature (V1–V28) must be provided and non-zero."
            else:
                err_msg = "Unknown validation error"
                
        failed_details.append({
            "error": err_msg,
            "raw_input": raw_row
        })
        
    return parsed_txns, failed_details


async def _async_process_batch_file(file_path: str, user_id: str, self=None) -> dict:
    import os
    import time
    from database.db import AsyncSessionLocal
    from models.transaction import Transaction, RiskLevel, TransactionStatus

    start_time = time.time()

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Temporary file not found: {file_path}")

    # Get file size safely
    file_size = 0
    try:
        file_size = os.path.getsize(file_path)
    except Exception:
        pass

    # No pre-scan is performed. Set total and total_chunks to None during processing.
    total_records = None
    total_chunks = None

    task_id = str(uuid.uuid4())
    if self and hasattr(self, "request") and self.request and hasattr(self.request, "id"):
        task_id = self.request.id

    actor_uuid = None
    role = None
    if user_id:
        try:
            actor_uuid = uuid.UUID(user_id)
            async with AsyncSessionLocal() as db:
                user = await db.get(User, actor_uuid)
                if user:
                    role = user.role.value if hasattr(user.role, "value") else str(user.role)
        except Exception:
            pass

    logger.info(
        "Batch file task started",
        extra={"event_type": "batch_file_started", "task_id": task_id, "user_id": user_id, "total": None, "file_size": file_size}
    )

    async with AsyncSessionLocal() as db:
        await log_audit_event(
            action="batch_file_started",
            resource_type="transaction",
            resource_id=task_id,
            status="success",
            actor_user_id=actor_uuid,
            actor_role=role,
            metadata={"task_id": task_id, "total": None, "file_size": file_size},
            db=db
        )

    processed_count = 0
    failed_count = 0
    fraud_count = 0
    predictions = []
    failed_details = []

    risk_map = {
        "LOW":    RiskLevel.LOW,
        "MEDIUM": RiskLevel.MEDIUM,
        "HIGH":   RiskLevel.HIGH,
    }

    chunk_size = int(os.environ.get("BATCH_CHUNK_SIZE", 10000))
    defer_shap = True  # Default to True for all file-based batch uploads

    try:
        # Validate columns first
        try:
            header_df = pd.read_csv(file_path, nrows=0)
            headers = [h.strip() for h in header_df.columns]
            normalized_headers = {h.lower() for h in headers}
        except Exception as e:
            raise ValueError(f"Failed to read CSV headers: {str(e)}")

        v_headers = {f"v{i}" for i in range(1, 29)}
        has_v = any(vh in normalized_headers for vh in v_headers)

        if "amount" not in normalized_headers or "time" not in normalized_headers or not has_v:
            raise ValueError("CSV is missing required columns. Must include 'Amount', 'Time', and at least one 'V1'-'V28' feature.")

        chunk_idx = 1
        # Stream file using pandas by passing file handle to track bytes processed via f.tell()
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for chunk_df in pd.read_csv(f, chunksize=chunk_size):
                raw_rows = chunk_df.to_dict(orient='records')
                
                # Vectorized validation
                parsed_txns, failed_details_chunk = validate_chunk_pandas(chunk_df, raw_rows, headers)
                
                # Update failed count and details (with bounding to avoid OOM)
                failed_count += len(failed_details_chunk)
                if len(failed_details) < 100:
                    failed_details.extend(failed_details_chunk[:100 - len(failed_details)])
                    
                bytes_processed = f.tell()
                
                if parsed_txns:
                    processed_this, failed_this, fraud_this = await _process_chunk_data(
                        parsed_txns, chunk_idx, total_chunks,
                        total_records, start_time, risk_map, defer_shap,
                        predictions, failed_details, self,
                        bytes_processed=bytes_processed, file_size=file_size
                    )
                    processed_count += processed_this
                    failed_count += failed_this
                    fraud_count += fraud_this
                else:
                    # Update progress for totally failed chunks
                    elapsed = time.time() - start_time
                    records_per_sec = round((processed_count + failed_count) / elapsed, 2) if elapsed > 0 else 0.0
                    if self:
                        self.update_state(
                            state="PROGRESS",
                            meta={
                                "status": "processing",
                                "total": None,
                                "processed": processed_count,
                                "failed": failed_count,
                                "fraud_count": fraud_count,
                                "bytes_processed": bytes_processed,
                                "file_size": file_size,
                                "approximate_progress_percent": int(100 * bytes_processed / file_size) if file_size > 0 else 0,
                                "current_chunk": chunk_idx,
                                "total_chunks": None,
                                "duration": round(elapsed, 4),
                                "records_per_second": records_per_sec
                            }
                        )
                chunk_idx += 1

        duration = time.time() - start_time
        final_total = processed_count + failed_count
        records_per_sec = round(final_total / duration, 2) if duration > 0 else 0.0
        
        logger.info(
            "Batch file task completed",
            extra={
                "event_type": "batch_file_completed",
                "task_id": task_id,
                "processed": processed_count,
                "failed": failed_count,
                "fraud_count": fraud_count
            }
        )
        async with AsyncSessionLocal() as db:
            await log_audit_event(
                action="batch_file_completed",
                resource_type="transaction",
                resource_id=task_id,
                status="success",
                actor_user_id=actor_uuid,
                actor_role=role,
                metadata={
                    "task_id": task_id,
                    "total": final_total,
                    "processed": processed_count,
                    "failed": failed_count,
                    "fraud_count": fraud_count,
                    "file_size": file_size
                },
                db=db
            )

        return {
            "total":          final_total,  # Set exact total_records upon completion
            "processed":      processed_count,
            "failed":         failed_count,
            "fraud_count":    fraud_count,
            "duration":       round(duration, 4),
            "records_per_second": records_per_sec,
            "predictions":    predictions,
            "failed_details": failed_details,
        }

    except Exception as exc:
        logger.error(
            "Batch file task failed",
            exc_info=True,
            extra={"event_type": "batch_file_failed", "task_id": task_id, "error_category": exc.__class__.__name__}
        )
        async with AsyncSessionLocal() as db:
            await log_audit_event(
                action="batch_file_failed",
                resource_type="transaction",
                resource_id=task_id,
                status="failure",
                actor_user_id=actor_uuid,
                actor_role=role,
                metadata={"task_id": task_id, "error_category": exc.__class__.__name__},
                db=db
            )
        raise exc


async def _process_chunk_data(
    chunk: list, chunk_idx: int, total_chunks: int,
    total_records: int, start_time: float, risk_map: dict, defer_shap: bool,
    predictions: list, failed_details: list, self=None,
    bytes_processed: int = 0, file_size: int = 0
) -> tuple:
    from ml.predict import predict_batch
    from database.db import AsyncSessionLocal
    from models.transaction import Transaction, TransactionStatus
    import time
    import uuid
    import json

    # Coerce string types safely to str or None
    for raw_parsed in chunk:
        for col in ["merchant", "merchant_category", "location", "card_last4"]:
            val = raw_parsed.get(col)
            if val is None or (isinstance(val, float) and np.isnan(val)):
                raw_parsed[col] = None
            else:
                raw_parsed[col] = str(val)

    processed_count = 0
    failed_count = 0
    fraud_count = 0

    try:
        results = predict_batch(chunk, defer_shap=defer_shap)
        if defer_shap and results:
            fraud_indices = [i for i, r in enumerate(results) if r and not r.get("error") and r.get("is_fraud")]
            if fraud_indices:
                fraud_subset = [chunk[i] for i in fraud_indices]
                try:
                    fraud_results = predict_batch(fraud_subset, defer_shap=False)
                    for idx, res in zip(fraud_indices, fraud_results):
                        if res and not res.get("error"):
                            results[idx] = res
                except Exception as shap_exc:
                    logger.warning(f"Failed to calculate SHAP for fraud subset in chunk: {shap_exc}")
    except Exception as e:
        for raw in chunk:
            if len(failed_details) < 100:
                failed_details.append({
                    "error": f"Prediction error: {str(e)}",
                    "raw_input": raw
                })
            failed_count += 1
        elapsed = time.time() - start_time
        records_per_sec = round((len(predictions) + len(failed_details)) / elapsed, 2) if elapsed > 0 else 0.0
        if self:
            task_id = self.request.id if (hasattr(self, "request") and self.request and hasattr(self.request, "id")) else None
            logger.info(
                f"Batch file task chunk {chunk_idx} processed (failed)",
                extra={
                    "event_type": "chunk_progress",
                    "task_id": task_id,
                    "current_chunk": chunk_idx,
                    "total_chunks": total_chunks,
                    "processed": len(predictions),
                    "failed": len(failed_details),
                }
            )
            self.update_state(
                state="PROGRESS",
                meta={
                    "status": "processing",
                    "total": total_records,
                    "processed": len(predictions),
                    "failed": len(failed_details),
                    "fraud_count": fraud_count,
                    "bytes_processed": bytes_processed,
                    "file_size": file_size,
                    "approximate_progress_percent": int(100 * bytes_processed / file_size) if file_size > 0 else 0,
                    "current_chunk": chunk_idx,
                    "total_chunks": total_chunks,
                    "duration": round(elapsed, 4),
                    "records_per_second": records_per_sec
                }
            )
        return 0, failed_count, 0

    chunk_valid_txns = []
    chunk_predictions = []
    chunk_fraud_count = 0

    for idx, (raw_parsed, result) in enumerate(zip(chunk, results)):
        if result is None:
            if len(failed_details) < 100:
                failed_details.append({
                    "error": "Prediction error: Unknown error",
                    "raw_input": raw_parsed
                })
            failed_count += 1
            continue
        if "error" in result:
            if len(failed_details) < 100:
                failed_details.append({
                    "error": f"Prediction error: {result['error']}",
                    "raw_input": raw_parsed
                })
            failed_count += 1
            continue

        try:
            status_val = (
                TransactionStatus.flagged if result["is_fraud"]
                else TransactionStatus.pending
            )
            # Deterministic UUID per batch task, chunk index, and item offset to ensure idempotency across retries
            task_identifier = self.request.id if (self and hasattr(self, "request") and self.request and hasattr(self.request, "id")) else "file_batch"
            txn_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{task_identifier}:{chunk_idx}:{idx}")
            chunk_valid_txns.append((txn_id, raw_parsed, result, status_val))
            if result["is_fraud"]:
                chunk_fraud_count += 1
        except Exception as e:
            if len(failed_details) < 100:
                failed_details.append({
                    "error": f"Database preparation error: {str(e)}",
                    "raw_input": raw_parsed
                })
            failed_count += 1

    # Database Ingestion
    if chunk_valid_txns:
        async with AsyncSessionLocal() as db:
            connection = await db.connection()
            is_postgres = connection.dialect.name == "postgresql"
            
            if is_postgres:
                # PostgreSQL COPY Fast Path
                try:
                    raw_connection = await connection.get_raw_connection()
                    driver_conn = raw_connection.driver_connection
                    
                    if hasattr(driver_conn, "copy_records_to_table"):
                        columns = [
                            "id", "amount", "merchant", "merchant_category", "location", "card_last4",
                            "transaction_time", "v_features", "fraud_score", "is_fraud", "risk_level",
                            "explanation", "top_features", "shap_values", "status"
                        ]
                        
                        records = []
                        for txn_id, raw_parsed, result, status_val in chunk_valid_txns:
                            # Extract and format V features
                            v_feat = raw_parsed.get("v_features") if "v_features" in raw_parsed else {f"V{i}": raw_parsed.get(f"V{i}", 0.0) for i in range(1, 29)}
                            v_feat_str = json.dumps(v_feat) if isinstance(v_feat, (dict, list)) else v_feat
                            
                            top_feat = result.get("top_features")
                            top_feat_str = json.dumps(top_feat) if isinstance(top_feat, (dict, list)) else top_feat
                            
                            shap_val = result.get("all_shap_values")
                            shap_val_str = json.dumps(shap_val) if isinstance(shap_val, (dict, list)) else shap_val
                            
                            # Helper to convert values to string safely for postgres COPY
                            def to_str(v):
                                if v is None or (isinstance(v, float) and np.isnan(v)):
                                    return None
                                return str(v)
                            
                            records.append((
                                txn_id,
                                float(raw_parsed.get("Amount", 0.0)),
                                to_str(raw_parsed.get("merchant")),
                                to_str(raw_parsed.get("merchant_category")),
                                to_str(raw_parsed.get("location")),
                                to_str(raw_parsed.get("card_last4")),
                                float(raw_parsed.get("Time", 0.0)),
                                v_feat_str,
                                float(result["fraud_score"]),
                                bool(result["is_fraud"]),
                                risk_map[result["risk_level"]].value,
                                to_str(result.get("explanation")),
                                top_feat_str,
                                shap_val_str,
                                status_val.value
                            ))
                        
                        await driver_conn.copy_records_to_table(
                            "transactions",
                            records=records,
                            columns=columns
                        )
                        await db.commit()
                        
                        for txn_id, result, status_val in [(t[0], t[2], t[3]) for t in chunk_valid_txns]:
                            chunk_predictions.append({
                                "transaction_id":   str(txn_id),
                                "fraud_score":      result["fraud_score"],
                                "fraud_percentage": result["fraud_percentage"],
                                "is_fraud":         result["is_fraud"],
                                "risk_level":       result["risk_level"],
                                "risk_color":       result["risk_color"],
                                "explanation":      result["explanation"],
                                "status":           status_val.value,
                            })
                        fraud_count += chunk_fraud_count
                        processed_count += len(chunk_predictions)
                        
                    else:
                        is_postgres = False
                except Exception as pg_exc:
                    await db.rollback()
                    logger.warning(
                        f"PostgreSQL COPY failed for chunk {chunk_idx}, rolling back chunk and falling back to row-by-row insertion. Error: {str(pg_exc)}"
                    )
                    # Safe COPY failure isolation and fallback:
                    # Fallback to inserting rows one-by-one to isolate specific database constraints/failures.
                    # This ensures database transaction boundaries are preserved and invalid rows are tracked.
                    # Documented: This row-by-row fallback is bounded and only executed if the batch COPY fails.
                    for txn_id, raw_parsed, result, status_val in chunk_valid_txns:
                        try:
                            async with AsyncSessionLocal() as row_db:
                                txn_obj = Transaction(
                                    id                 = txn_id,
                                    amount             = raw_parsed.get("Amount", 0.0),
                                    merchant           = raw_parsed.get("merchant"),
                                    merchant_category  = raw_parsed.get("merchant_category"),
                                    location           = raw_parsed.get("location"),
                                    card_last4         = raw_parsed.get("card_last4"),
                                    transaction_time   = raw_parsed.get("Time", 0.0),
                                    v_features         = {f"V{i}": raw_parsed.get(f"V{i}", 0.0) for i in range(1, 29)},
                                    fraud_score        = result["fraud_score"],
                                    is_fraud           = result["is_fraud"],
                                    risk_level         = risk_map[result["risk_level"]],
                                    explanation        = result["explanation"],
                                    top_features       = result["top_features"],
                                    shap_values        = result["all_shap_values"],
                                    status             = status_val,
                                )
                                row_db.add(txn_obj)
                                await row_db.commit()
                                
                                chunk_predictions.append({
                                    "transaction_id":   str(txn_id),
                                    "fraud_score":      result["fraud_score"],
                                    "fraud_percentage": result["fraud_percentage"],
                                    "is_fraud":         result["is_fraud"],
                                    "risk_level":       result["risk_level"],
                                    "risk_color":       result["risk_color"],
                                    "explanation":      result["explanation"],
                                    "status":           status_val.value,
                                })
                                if result["is_fraud"]:
                                    fraud_count += 1
                                processed_count += 1
                        except Exception as ind_exc:
                            # Check for idempotent replay: if record already exists, treat as already committed
                            try:
                                async with AsyncSessionLocal() as check_db:
                                    existing = await check_db.get(Transaction, txn_id)
                            except Exception:
                                existing = None

                            if existing is not None:
                                chunk_predictions.append({
                                    "transaction_id":   str(txn_id),
                                    "fraud_score":      result["fraud_score"],
                                    "fraud_percentage": result["fraud_percentage"],
                                    "is_fraud":         result["is_fraud"],
                                    "risk_level":       result["risk_level"],
                                    "risk_color":       result["risk_color"],
                                    "explanation":      result["explanation"],
                                    "status":           status_val.value,
                                })
                                if result["is_fraud"]:
                                    fraud_count += 1
                                processed_count += 1
                            else:
                                logger.error("Fallback row insert failed", exc_info=True)
                                if len(failed_details) < 100:
                                    failed_details.append({
                                        "error": f"Database write error: {str(ind_exc)}",
                                        "raw_input": {
                                            "Amount": raw_parsed.get("Amount"),
                                            "merchant": raw_parsed.get("merchant"),
                                            "Time": raw_parsed.get("Time")
                                        }
                                    })
                                failed_count += 1
            
            if not is_postgres:
                # SQLite Fallback (SQLAlchemy Core bulk insert)
                try:
                    insert_mappings = []
                    for txn_id, raw_parsed, result, status_val in chunk_valid_txns:
                        insert_mappings.append({
                            "id": txn_id,
                            "amount": raw_parsed.get("Amount", 0.0),
                            "merchant": raw_parsed.get("merchant"),
                            "merchant_category": raw_parsed.get("merchant_category"),
                            "location": raw_parsed.get("location"),
                            "card_last4": raw_parsed.get("card_last4"),
                            "transaction_time": raw_parsed.get("Time", 0.0),
                            "v_features": {f"V{i}": raw_parsed.get(f"V{i}", 0.0) for i in range(1, 29)},
                            "fraud_score": result["fraud_score"],
                            "is_fraud": result["is_fraud"],
                            "risk_level": risk_map[result["risk_level"]],
                            "explanation": result["explanation"],
                            "top_features": result["top_features"],
                            "shap_values": result["all_shap_values"],
                            "status": status_val,
                        })
                    await db.execute(insert(Transaction), insert_mappings)
                    await db.commit()

                    for txn_id, result, status_val in [(t[0], t[2], t[3]) for t in chunk_valid_txns]:
                        chunk_predictions.append({
                            "transaction_id":   str(txn_id),
                            "fraud_score":      result["fraud_score"],
                            "fraud_percentage": result["fraud_percentage"],
                            "is_fraud":         result["is_fraud"],
                            "risk_level":       result["risk_level"],
                            "risk_color":       result["risk_color"],
                            "explanation":      result["explanation"],
                            "status":           status_val.value,
                        })
                    fraud_count += chunk_fraud_count
                    processed_count += len(chunk_predictions)
                except Exception as commit_exc:
                    await db.rollback()
                    # Retry one by one if bulk write fails (SQLite / constraint failures)
                    for txn_id, raw_parsed, result, status_val in chunk_valid_txns:
                        try:
                            async with AsyncSessionLocal() as row_db:
                                txn_obj = Transaction(
                                    id                 = txn_id,
                                    amount             = raw_parsed.get("Amount", 0.0),
                                    merchant           = raw_parsed.get("merchant"),
                                    merchant_category  = raw_parsed.get("merchant_category"),
                                    location           = raw_parsed.get("location"),
                                    card_last4         = raw_parsed.get("card_last4"),
                                    transaction_time   = raw_parsed.get("Time", 0.0),
                                    v_features         = {f"V{i}": raw_parsed.get(f"V{i}", 0.0) for i in range(1, 29)},
                                    fraud_score        = result["fraud_score"],
                                    is_fraud           = result["is_fraud"],
                                    risk_level         = risk_map[result["risk_level"]],
                                    explanation        = result["explanation"],
                                    top_features       = result["top_features"],
                                    shap_values        = result["all_shap_values"],
                                    status             = status_val,
                                )
                                row_db.add(txn_obj)
                                await row_db.commit()
                                chunk_predictions.append({
                                    "transaction_id":   str(txn_id),
                                    "fraud_score":      result["fraud_score"],
                                    "fraud_percentage": result["fraud_percentage"],
                                    "is_fraud":         result["is_fraud"],
                                    "risk_level":       result["risk_level"],
                                    "risk_color":       result["risk_color"],
                                    "explanation":      result["explanation"],
                                    "status":           status_val.value,
                                })
                                if result["is_fraud"]:
                                    fraud_count += 1
                                processed_count += 1
                        except Exception as ind_exc:
                            # Check for idempotent replay: if record already exists, treat as already committed
                            try:
                                async with AsyncSessionLocal() as check_db:
                                    existing = await check_db.get(Transaction, txn_id)
                            except Exception:
                                existing = None

                            if existing is not None:
                                chunk_predictions.append({
                                    "transaction_id":   str(txn_id),
                                    "fraud_score":      result["fraud_score"],
                                    "fraud_percentage": result["fraud_percentage"],
                                    "is_fraud":         result["is_fraud"],
                                    "risk_level":       result["risk_level"],
                                    "risk_color":       result["risk_color"],
                                    "explanation":      result["explanation"],
                                    "status":           status_val.value,
                                })
                                if result["is_fraud"]:
                                    fraud_count += 1
                                processed_count += 1
                            else:
                                if len(failed_details) < 100:
                                    failed_details.append({
                                        "error": f"Database write error: {str(ind_exc)}",
                                        "raw_input": {
                                            "Amount": raw_parsed.get("Amount"),
                                            "merchant": raw_parsed.get("merchant"),
                                            "Time": raw_parsed.get("Time")
                                        }
                                    })
                                failed_count += 1

    # Memory safety: cap predictions list at 100
    if total_records is not None and total_records <= 1000:
        predictions.extend(chunk_predictions)
    else:
        if len(predictions) < 100:
            predictions.extend(chunk_predictions[:100 - len(predictions)])

    # Update Celery state after chunk success
    elapsed = time.time() - start_time
    records_per_sec = round((processed_count + failed_count) / elapsed, 2) if elapsed > 0 else 0.0
    if self:
        task_id = self.request.id if (hasattr(self, "request") and self.request and hasattr(self.request, "id")) else None
        logger.info(
            f"Batch file task chunk {chunk_idx} processed",
            extra={
                "event_type": "chunk_progress",
                "task_id": task_id,
                "current_chunk": chunk_idx,
                "total_chunks": total_chunks,
                "processed": processed_count,
                "failed": failed_count,
            }
        )
        self.update_state(
            state="PROGRESS",
            meta={
                "status": "processing",
                "total": total_records,
                "processed": processed_count,
                "failed": failed_count,
                "fraud_count": fraud_count,
                "bytes_processed": bytes_processed,
                "file_size": file_size,
                "approximate_progress_percent": int(100 * bytes_processed / file_size) if file_size > 0 else 0,
                "current_chunk": chunk_idx,
                "total_chunks": total_chunks,
                "duration": round(elapsed, 4),
                "records_per_second": records_per_sec
            }
        )

    return processed_count, failed_count, fraud_count

