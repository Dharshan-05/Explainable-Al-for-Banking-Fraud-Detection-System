from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from models.transaction import Transaction, RiskLevel, TransactionStatus
from ml.predict import predict_transaction
from api.routes.ws import manager

async def predict_and_save_transaction(db: AsyncSession, data: any) -> dict:
    try:
        input_dict = data.to_dict()
        # Run prediction
        result = predict_transaction(input_dict)

        # Save to database
        risk_map   = {"LOW": RiskLevel.LOW, "MEDIUM": RiskLevel.MEDIUM, "HIGH": RiskLevel.HIGH}
        status_val = TransactionStatus.flagged if result["is_fraud"] else TransactionStatus.pending

        transaction = Transaction(
            amount            = data.Amount,
            merchant          = data.merchant,
            merchant_category = data.merchant_category,
            location          = data.location,
            card_last4        = data.card_last4,
            transaction_time  = data.Time,
            v_features        = {f"V{i}": input_dict.get(f"V{i}", 0.0) for i in range(1, 29)},
            fraud_score       = result["fraud_score"],
            is_fraud          = result["is_fraud"],
            risk_level        = risk_map[result["risk_level"]],
            explanation       = result["explanation"],
            top_features      = result["top_features"],
            shap_values       = result["all_shap_values"],
            status            = status_val
        )
        db.add(transaction)
        await db.commit()
        await db.refresh(transaction)

        # WebSocket broadcast for HIGH-risk fraud
        if result["is_fraud"] and result["risk_level"] == "HIGH":
            try:
                await manager.broadcast({
                    "type":           "fraud_alert",
                    "transaction_id": str(transaction.id),
                    "fraud_score":    result["fraud_score"],
                    "fraud_pct":      result["fraud_percentage"],
                    "risk_level":     result["risk_level"],
                    "amount":         data.Amount,
                    "merchant":       data.merchant,
                    "explanation":    result["explanation"],
                })
            except Exception:
                pass  # Do not fail prediction request if WS broadcast fails

        return {
            "transaction_id":   str(transaction.id),
            "fraud_score":      result["fraud_score"],
            "fraud_percentage": result["fraud_percentage"],
            "is_fraud":         result["is_fraud"],
            "risk_level":       result["risk_level"],
            "risk_color":       result["risk_color"],
            "explanation":      result["explanation"],
            "top_features":     result["top_features"],
            "shap_base_value":  result["shap_base_value"],
            "status":           status_val.value
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction error: {str(e)}")
