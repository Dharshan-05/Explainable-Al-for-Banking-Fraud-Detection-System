# ============================================================
#  models/transaction.py  —  Transaction DB Model
# ============================================================

from sqlalchemy import Column, String, Float, Boolean, DateTime, Enum, JSON, Text, Uuid
from sqlalchemy.sql import func
from database.db import Base
import uuid
import enum


class RiskLevel(str, enum.Enum):
    LOW    = "LOW"
    MEDIUM = "MEDIUM"
    HIGH   = "HIGH"


class TransactionStatus(str, enum.Enum):
    PENDING  = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FLAGGED  = "FLAGGED"
    # Backward compatible aliases
    pending  = "pending"
    approved = "approved"
    rejected = "rejected"
    flagged  = "flagged"


class Transaction(Base):
    __tablename__ = "transactions"

    id              = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Transaction details
    amount          = Column(Float, nullable=False)
    merchant        = Column(String(255), nullable=True)
    merchant_category = Column(String(100), nullable=True)
    location        = Column(String(255), nullable=True)
    card_last4      = Column(String(4),   nullable=True)
    transaction_time = Column(Float,      nullable=True)  # seconds from midnight

    # ML Features (V1-V28 from PCA)
    v_features      = Column(JSON, nullable=True)  # {"V1": 0.1, "V2": -0.5, ...}

    # Prediction results
    fraud_score     = Column(Float,   nullable=True)
    is_fraud        = Column(Boolean, nullable=True, index=True)
    risk_level      = Column(Enum(RiskLevel), nullable=True, index=True)
    explanation     = Column(Text,    nullable=True)
    top_features    = Column(JSON,    nullable=True)
    shap_values     = Column(JSON,    nullable=True)

    # Status
    status          = Column(Enum(TransactionStatus), default=TransactionStatus.pending, index=True)
    reviewed_by     = Column(String(255), nullable=True)
    review_notes    = Column(Text,        nullable=True)
    reviewed_at     = Column(DateTime(timezone=True), nullable=True)
    assigned_analyst = Column(String(255), nullable=True)

    # Timestamps
    created_at      = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<Transaction {self.id} amount={self.amount} fraud={self.is_fraud}>"

