# ============================================================
#  api/routes/predict.py  —  Fraud Prediction + SHAP
#  POST /api/predict/transaction   — single transaction
#  POST /api/predict/batch         — async batch (Celery)
#  GET  /api/predict/batch/{id}    — poll Celery result
# ============================================================

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Any
import uuid
import tempfile
import os

from database.db import get_db
from api.deps import get_current_user
from models.user import User
from config import settings

router = APIRouter()

# Lazy load ML model
_predictor = None

def get_predictor():
    global _predictor
    if _predictor is None:
        from ml.predict import predict_transaction, predict_batch
        _predictor = {"single": predict_transaction, "batch": predict_batch}
    return _predictor


# ─────────────────────────────────────────
#  Schemas
# ─────────────────────────────────────────
class TransactionInput(BaseModel):
    # V features from PCA (V1-V28)
    V1: Optional[float] = None;  V2: Optional[float] = None
    V3: Optional[float] = None;  V4: Optional[float] = None
    V5: Optional[float] = None;  V6: Optional[float] = None
    V7: Optional[float] = None;  V8: Optional[float] = None
    V9: Optional[float] = None;  V10: Optional[float] = None
    V11: Optional[float] = None; V12: Optional[float] = None
    V13: Optional[float] = None; V14: Optional[float] = None
    V15: Optional[float] = None; V16: Optional[float] = None
    V17: Optional[float] = None; V18: Optional[float] = None
    V19: Optional[float] = None; V20: Optional[float] = None
    V21: Optional[float] = None; V22: Optional[float] = None
    V23: Optional[float] = None; V24: Optional[float] = None
    V25: Optional[float] = None; V26: Optional[float] = None
    V27: Optional[float] = None; V28: Optional[float] = None

    # Original features — Amount must be positive
    Amount: float = Field(gt=0, default=100.0, description="Transaction amount (must be > 0)")
    Time:   float = Field(ge=0, default=50000.0)

    # Optional metadata
    merchant          : Optional[str] = None
    merchant_category : Optional[str] = None
    location          : Optional[str] = None
    card_last4        : Optional[str] = None

    @model_validator(mode="after")
    def validate_v_features(self) -> "TransactionInput":
        """Reject transactions where all PCA features are missing/zero."""
        v_vals = [getattr(self, f"V{i}") for i in range(1, 29)]
        provided = [v for v in v_vals if v is not None]
        if not provided or all(v == 0.0 for v in provided):
            raise ValueError(
                "At least one PCA feature (V1–V28) must be provided and non-zero. "
                "All-zero or entirely absent V-features indicate missing data and "
                "will produce unreliable predictions."
            )
        return self

    def to_dict(self) -> dict:
        """Return a flat dict with zero defaults for missing V-features."""
        d = self.model_dump()
        for i in range(1, 29):
            key = f"V{i}"
            if d[key] is None:
                d[key] = 0.0
        return d


class FeatureExplanation(BaseModel):
    feature   : str
    shap_value: float
    direction : str
    impact    : str

class PredictionResponse(BaseModel):
    transaction_id    : str
    fraud_score       : float
    fraud_percentage  : float
    is_fraud          : bool
    risk_level        : str
    risk_color        : str
    explanation       : str
    top_features      : List[FeatureExplanation]
    shap_base_value   : float
    status            : str


# ─────────────────────────────────────────
#  Single Transaction Prediction
# ─────────────────────────────────────────
@router.post("/transaction", response_model=PredictionResponse)
async def predict_single(
    data: TransactionInput,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from services.predict_service import predict_and_save_transaction
    res = await predict_and_save_transaction(db, data)
    return res


# ─────────────────────────────────────────
#  Async Batch Prediction (Celery)
# ─────────────────────────────────────────
class BatchInput(BaseModel):
    transactions: List[TransactionInput]

class BatchSubmitResponse(BaseModel):
    task_id    : str
    status     : str
    total      : int
    message    : str

class BatchResultResponse(BaseModel):
    task_id    : str
    status     : str  # PENDING | STARTED | SUCCESS | FAILURE
    result     : Optional[Any] = None
    error      : Optional[str] = None


@router.post("/batch", response_model=BatchSubmitResponse)
async def predict_batch_submit(
    data: BatchInput,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Submit a batch of transactions for async background processing.
    Returns immediately with a task_id to poll.
    """
    from tasks.predict_tasks import process_batch
    from services.audit_service import log_audit_event

    ip_addr = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    raw_transactions = [t.to_dict() for t in data.transactions]
    task = process_batch.delay(raw_transactions, str(current_user.id))

    await log_audit_event(
        action="batch_json_submitted",
        resource_type="transaction",
        resource_id=task.id,
        status="success",
        actor_user_id=current_user.id,
        actor_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        ip_address=ip_addr,
        user_agent=user_agent,
        metadata={"task_id": task.id, "total": len(raw_transactions)},
        db=db
    )

    return BatchSubmitResponse(
        task_id = task.id,
        status  = "PENDING",
        total   = len(raw_transactions),
        message = f"Batch of {len(raw_transactions)} transactions queued. Poll /api/predict/batch/{task.id} for results.",
    )


@router.get("/batch/{task_id}", response_model=BatchResultResponse)
async def predict_batch_result(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Poll the status of an async batch prediction task.
    Status values: PENDING | STARTED | SUCCESS | FAILURE
    """
    from worker import celery_app
    from celery.result import AsyncResult

    task_result = AsyncResult(task_id, app=celery_app)

    if task_result.state == "FAILURE":
        return BatchResultResponse(
            task_id = task_id,
            status  = "FAILURE",
            error   = str(task_result.result),
        )

    info = task_result.info
    if isinstance(info, Exception):
        info = str(info)

    return BatchResultResponse(
        task_id = task_id,
        status  = task_result.state,
        result  = info,
    )


# ─────────────────────────────────────────
#  Async Batch CSV File Prediction (Celery)
# ─────────────────────────────────────────
@router.post("/batch-file", response_model=BatchSubmitResponse)
async def predict_batch_file_submit(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Submit a CSV file of transactions for async background processing.
    Saves the file to a temporary location and enqueues Celery task.
    """
    from tasks.predict_tasks import process_batch_file
    from services.audit_service import log_audit_event

    ip_addr = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    filename = file.filename or ""
    content_type = file.content_type or ""

    # Primary: extension validation (case-insensitive)
    if not filename.lower().endswith(".csv"):
        await log_audit_event(
            action="batch_file_rejected",
            resource_type="transaction",
            status="failure",
            actor_user_id=current_user.id,
            actor_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
            ip_address=ip_addr,
            user_agent=user_agent,
            metadata={"error_category": "InvalidFileType", "error_detail": "Only CSV files are supported."},
            db=db
        )
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")

    # Secondary: content-type validation (supporting csv, plain, excel, octet-stream)
    allowed_types = ["csv", "plain", "excel", "octet-stream"]
    if not any(t in content_type.lower() for t in allowed_types):
        await log_audit_event(
            action="batch_file_rejected",
            resource_type="transaction",
            status="failure",
            actor_user_id=current_user.id,
            actor_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
            ip_address=ip_addr,
            user_agent=user_agent,
            metadata={"error_category": "InvalidContentType", "error_detail": "Only CSV files are supported."},
            db=db
        )
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")

    # Create temporary file with secure random name and suffix .csv
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    temp_file_path = temp_file.name
    
    try:
        cumulative_bytes = 0
        while True:
            chunk = await file.read(settings.UPLOAD_CHUNK_SIZE)
            if not chunk:
                break
            cumulative_bytes += len(chunk)
            if cumulative_bytes > settings.MAX_UPLOAD_SIZE:
                temp_file.close()
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
                await log_audit_event(
                    action="batch_file_rejected",
                    resource_type="transaction",
                    status="failure",
                    actor_user_id=current_user.id,
                    actor_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
                    ip_address=ip_addr,
                    user_agent=user_agent,
                    metadata={"error_category": "PayloadTooLarge", "file_size": cumulative_bytes},
                    db=db
                )
                raise HTTPException(status_code=413, detail="Payload Too Large. Maximum upload size is 50MB.")
            temp_file.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        temp_file.close()
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
        await log_audit_event(
            action="batch_file_rejected",
            resource_type="transaction",
            status="failure",
            actor_user_id=current_user.id,
            actor_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
            ip_address=ip_addr,
            user_agent=user_agent,
            metadata={"error_category": "FileSaveError", "error_detail": str(e)},
            db=db
        )
        raise HTTPException(status_code=500, detail=f"File save error: {str(e)}")
    finally:
        temp_file.close()

    # Enqueue Celery task with the path of the temporary file
    task = process_batch_file.delay(temp_file_path, str(current_user.id))

    await log_audit_event(
        action="batch_file_submitted",
        resource_type="transaction",
        resource_id=task.id,
        status="success",
        actor_user_id=current_user.id,
        actor_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        ip_address=ip_addr,
        user_agent=user_agent,
        metadata={"task_id": task.id, "file_size": cumulative_bytes},
        db=db
    )

    return BatchSubmitResponse(
        task_id = task.id,
        status  = "PENDING",
        total   = -1,  # Total count calculated asynchronously in background
        message = f"Batch CSV file uploaded successfully. Queued background prediction. Poll /api/predict/batch/{task.id} for progress.",
    )
