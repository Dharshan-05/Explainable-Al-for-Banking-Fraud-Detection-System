# ============================================================
#  tasks/predict_tasks.py  —  Async Batch Prediction
#  Celery task that processes a list of transactions in the
#  background, writes results to Postgres, and returns a
#  summary dict consumable via GET /api/predict/batch/{task_id}
# ============================================================

import uuid
import asyncio
import time
import logging
from worker import celery_app
from services.audit_service import log_audit_event
from database.db import AsyncSessionLocal
from models.user import User

logger = logging.getLogger("tasks")



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
    try:
        return asyncio.run(_async_process_batch(transactions, user_id, self))
    except Exception as exc:
        self.retry(exc=exc, countdown=5, max_retries=3)


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

    # Chunk size logic (default 1000)
    chunk_size = int(os.environ.get("BATCH_CHUNK_SIZE", 1000))

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
            except Exception as e:
                # Entire chunk prediction failed
                for raw in chunk:
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

            # Build transaction objects for this chunk
            for raw, result in zip(chunk, results):
                if result is None:
                    failed_details.append({
                        "error": "Prediction error: Unknown error",
                        "raw_input": raw
                    })
                    failed_count += 1
                    continue
                if "error" in result:
                    failed_details.append({
                        "error": f"Prediction error: {result['error']}",
                        "raw_input": raw
                    })
                    failed_count += 1
                    continue

                try:
                    status_val = TransactionStatus.flagged if result["is_fraud"] else TransactionStatus.pending
                    txn = Transaction(
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
                    chunk_valid_txns.append((txn, result, status_val))
                    if result["is_fraud"]:
                        chunk_fraud_count += 1
                except Exception as e:
                    failed_details.append({
                        "error": f"Database preparation error: {str(e)}",
                        "raw_input": raw
                    })
                    failed_count += 1

            # Bulk insert
            async with AsyncSessionLocal() as db:
                if chunk_valid_txns:
                    try:
                        for txn, _, _ in chunk_valid_txns:
                            db.add(txn)
                        await db.commit()

                        # Build predictions response payload
                        for txn, result, status_val in chunk_valid_txns:
                            chunk_predictions.append({
                                "transaction_id":   str(txn.id),
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
                        # Retry one by one if bulk write fails
                        for txn, result, status_val in chunk_valid_txns:
                            try:
                                db.add(txn)
                                await db.commit()
                                chunk_predictions.append({
                                    "transaction_id":   str(txn.id),
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
                                failed_details.append({
                                    "error": f"Database write error: {str(ind_exc)}",
                                    "raw_input": {
                                        "Amount": txn.amount,
                                        "merchant": txn.merchant,
                                        "Time": txn.transaction_time
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
    cleans up the temporary CSV file in a finally block.
    """
    import os
    try:
        return asyncio.run(_async_process_batch_file(file_path, user_id, self))
    except Exception as exc:
        if isinstance(exc, (ValueError, FileNotFoundError)):
            raise exc
        self.retry(exc=exc, countdown=5, max_retries=3)
    finally:
        if os.path.exists(file_path):
            try:
                os.unlink(file_path)
            except Exception:
                pass


async def _async_process_batch_file(file_path: str, user_id: str, self=None) -> dict:
    import os
    import csv
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

    # Count total records (low-memory line scan)
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            total_records = max(0, sum(1 for _ in f) - 1)
    except Exception as e:
        raise ValueError(f"Failed to scan CSV lines: {str(e)}")

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
        extra={"event_type": "batch_file_started", "task_id": task_id, "user_id": user_id, "total": total_records, "file_size": file_size}
    )

    async with AsyncSessionLocal() as db:
        await log_audit_event(
            action="batch_file_started",
            resource_type="transaction",
            resource_id=task_id,
            status="success",
            actor_user_id=actor_uuid,
            actor_role=role,
            metadata={"task_id": task_id, "total": total_records, "file_size": file_size},
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

    chunk_size = int(os.environ.get("BATCH_CHUNK_SIZE", 1000))
    defer_shap = total_records > 1000
    total_chunks = (total_records + chunk_size - 1) // chunk_size if total_records > 0 else 1

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.DictReader(f)
            headers = [h.strip() for h in (reader.fieldnames or [])]
            normalized_headers = {h.lower() for h in headers}

            # Required headers validation
            v_headers = {f"v{i}" for i in range(1, 29)}
            has_v = any(vh in normalized_headers for vh in v_headers)

            if "amount" not in normalized_headers or "time" not in normalized_headers or not has_v:
                raise ValueError("CSV is missing required columns. Must include 'Amount', 'Time', and at least one 'V1'-'V28' feature.")

            chunk = []
            chunk_raw_rows = []
            chunk_idx = 1

            for row in reader:
                # Normalize keys case-insensitively
                normalized_row = {k.strip().lower() if k else "": v for k, v in row.items()}

                if not normalized_row or all(not val for val in normalized_row.values()):
                    continue

                amount_str = normalized_row.get("amount", "0")
                time_str = normalized_row.get("time", "0")

                try:
                    amount = float(amount_str) if amount_str else 0.0
                except ValueError:
                    failed_details.append({
                        "error": f"Invalid Amount: {amount_str}",
                        "raw_input": row
                    })
                    failed_count += 1
                    continue

                try:
                    time_val = float(time_str) if time_str else 0.0
                except ValueError:
                    failed_details.append({
                        "error": f"Invalid Time: {time_str}",
                        "raw_input": row
                    })
                    failed_count += 1
                    continue

                if amount <= 0:
                    failed_details.append({
                        "error": "Amount must be greater than 0",
                        "raw_input": row
                    })
                    failed_count += 1
                    continue

                if time_val < 0:
                    failed_details.append({
                        "error": "Time must be non-negative",
                        "raw_input": row
                    })
                    failed_count += 1
                    continue

                # Parse V features
                v_features = {}
                v_provided = False
                v_non_zero = False
                for i in range(1, 29):
                    v_key = f"v{i}"
                    val_str = normalized_row.get(v_key)
                    if val_str:
                        try:
                            val = float(val_str)
                            v_features[f"V{i}"] = val
                            v_provided = True
                            if val != 0.0:
                                v_non_zero = True
                        except ValueError:
                            v_features[f"V{i}"] = 0.0
                    else:
                        v_features[f"V{i}"] = 0.0

                if not v_provided or not v_non_zero:
                    failed_details.append({
                        "error": "At least one PCA feature (V1–V28) must be provided and non-zero.",
                        "raw_input": row
                    })
                    failed_count += 1
                    continue

                parsed_txn = {
                    "Amount": amount,
                    "Time": time_val,
                    "merchant": row.get("merchant") or row.get("Merchant"),
                    "merchant_category": row.get("merchant_category") or row.get("Merchant_Category") or row.get("MerchantCategory"),
                    "location": row.get("location") or row.get("Location"),
                    "card_last4": row.get("card_last4") or row.get("Card_Last4") or row.get("CardLast4"),
                    **v_features
                }

                chunk.append(parsed_txn)
                chunk_raw_rows.append(row)

                if len(chunk) >= chunk_size:
                    processed_this, failed_this, fraud_this = await _process_chunk_data(
                        chunk, chunk_raw_rows, chunk_idx, total_chunks,
                        total_records, start_time, risk_map, defer_shap,
                        predictions, failed_details, self
                    )
                    processed_count += processed_this
                    failed_count += failed_this
                    fraud_count += fraud_this

                    chunk = []
                    chunk_raw_rows = []
                    chunk_idx += 1

            if chunk:
                processed_this, failed_this, fraud_this = await _process_chunk_data(
                    chunk, chunk_raw_rows, chunk_idx, total_chunks,
                    total_records, start_time, risk_map, defer_shap,
                    predictions, failed_details, self
                )
                processed_count += processed_this
                failed_count += failed_this
                fraud_count += fraud_this

        duration = time.time() - start_time
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
                    "total": total_records,
                    "processed": processed_count,
                    "failed": failed_count,
                    "fraud_count": fraud_count,
                    "file_size": file_size
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
    chunk: list, raw_rows: list, chunk_idx: int, total_chunks: int,
    total_records: int, start_time: float, risk_map: dict, defer_shap: bool,
    predictions: list, failed_details: list, self=None
) -> tuple:
    from ml.predict import predict_batch
    from database.db import AsyncSessionLocal
    from models.transaction import Transaction, TransactionStatus
    import time

    processed_count = 0
    failed_count = 0
    fraud_count = 0

    try:
        results = predict_batch(chunk, defer_shap=defer_shap)
    except Exception as e:
        for raw in raw_rows:
            failed_details.append({
                "error": f"Prediction error: {str(e)}",
                "raw_input": raw
            })
            failed_count += 1
        elapsed = time.time() - start_time
        if self:
            task_id = self.request.id if (hasattr(self, "request") and self.request and hasattr(self.request, "id")) else None
            logger.info(
                f"Batch file task chunk {chunk_idx}/{total_chunks} processed",
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
                    "current_chunk": chunk_idx,
                    "total_chunks": total_chunks,
                    "duration": round(elapsed, 4)
                }
            )
        return 0, failed_count, 0

    chunk_valid_txns = []
    chunk_predictions = []
    chunk_fraud_count = 0

    for raw_parsed, raw, result in zip(chunk, raw_rows, results):
        if result is None:
            failed_details.append({
                "error": "Prediction error: Unknown error",
                "raw_input": raw
            })
            failed_count += 1
            continue
        if "error" in result:
            failed_details.append({
                "error": f"Prediction error: {result['error']}",
                "raw_input": raw
            })
            failed_count += 1
            continue

        try:
            status_val = (
                TransactionStatus.flagged if result["is_fraud"]
                else TransactionStatus.pending
            )

            txn = Transaction(
                amount             = raw_parsed.get("Amount", 0),
                merchant           = raw_parsed.get("merchant"),
                merchant_category  = raw_parsed.get("merchant_category"),
                location           = raw_parsed.get("location"),
                card_last4         = raw_parsed.get("card_last4"),
                transaction_time   = raw_parsed.get("Time", 0),
                v_features         = {f"V{i}": raw_parsed.get(f"V{i}", 0.0) for i in range(1, 29)},
                fraud_score        = result["fraud_score"],
                is_fraud           = result["is_fraud"],
                risk_level         = risk_map[result["risk_level"]],
                explanation        = result["explanation"],
                top_features       = result["top_features"],
                shap_values        = result["all_shap_values"],
                status             = status_val,
            )
            chunk_valid_txns.append((txn, result, status_val))
            if result["is_fraud"]:
                chunk_fraud_count += 1
        except Exception as e:
            failed_details.append({
                "error": f"Database preparation error: {str(e)}",
                "raw_input": raw
            })
            failed_count += 1

    # Bulk insert
    async with AsyncSessionLocal() as db:
        if chunk_valid_txns:
            try:
                for txn, _, _ in chunk_valid_txns:
                    db.add(txn)
                await db.commit()

                for txn, result, status_val in chunk_valid_txns:
                    chunk_predictions.append({
                        "transaction_id":   str(txn.id),
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
                # Retry one by one if bulk write fails
                for txn, result, status_val in chunk_valid_txns:
                    try:
                        db.add(txn)
                        await db.commit()
                        chunk_predictions.append({
                            "transaction_id":   str(txn.id),
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
                        failed_details.append({
                            "error": f"Database write error: {str(ind_exc)}",
                            "raw_input": {
                                "Amount": txn.amount,
                                "merchant": txn.merchant,
                                "Time": txn.transaction_time
                            }
                        })
                        failed_count += 1

    # Memory safety: cap predictions list at 100
    if total_records <= 1000:
        predictions.extend(chunk_predictions)
    else:
        if len(predictions) < 100:
            predictions.extend(chunk_predictions[:100 - len(predictions)])

    # Update Celery state after chunk success
    elapsed = time.time() - start_time
    if self:
        task_id = self.request.id if (hasattr(self, "request") and self.request and hasattr(self.request, "id")) else None
        logger.info(
            f"Batch file task chunk {chunk_idx}/{total_chunks} processed",
            extra={
                "event_type": "chunk_progress",
                "task_id": task_id,
                "current_chunk": chunk_idx,
                "total_chunks": total_chunks,
                "processed": len(predictions) if total_records <= 1000 else processed_count,
                "failed": len(failed_details),
            }
        )
        self.update_state(
            state="PROGRESS",
            meta={
                "status": "processing",
                "total": total_records,
                "processed": len(predictions) if total_records <= 1000 else processed_count,
                "failed": len(failed_details),
                "fraud_count": fraud_count,
                "current_chunk": chunk_idx,
                "total_chunks": total_chunks,
                "duration": round(elapsed, 4)
            }
        )

    return processed_count, failed_count, fraud_count

