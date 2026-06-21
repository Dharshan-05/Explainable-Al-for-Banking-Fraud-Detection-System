import joblib
import numpy as np
import os
import logging

BASE_DIR    = os.path.dirname(__file__)
MODEL_PATH  = os.path.join(BASE_DIR, "model.pkl")
SCALER_PATH = os.path.join(BASE_DIR, "scaler.pkl")
SHAP_PATH   = os.path.join(BASE_DIR, "shap_explainer.pkl")

_model = None
_scaler = None
_explainer = None
_expected_value = 0.0
_feature_cols = None

def load_models():
    global _model, _scaler, _explainer, _expected_value, _feature_cols
    if _model is None:
        try:
            raw = joblib.load(MODEL_PATH)
            if isinstance(raw, dict):
                _model        = raw["model"]
                _scaler       = raw.get("scaler", None)
                _feature_cols = raw.get("feature_cols", [f"V{i}" for i in range(1, 29)] + ["Amount_Scaled", "Time_Scaled"])
            else:
                _model        = raw
                _feature_cols = [f"V{i}" for i in range(1, 29)] + ["Amount_Scaled", "Time_Scaled"]
        except Exception as e:
            logging.error(f"Failed to load XGBoost model from {MODEL_PATH}: {e}")
            raise RuntimeError(f"ML model loading failed: {e}")

        if _scaler is None:
            try:
                s = joblib.load(SCALER_PATH)
                _scaler = s if hasattr(s, "transform") else None
            except Exception as e:
                logging.warning(f"Failed to load scaler from {SCALER_PATH}: {e}")
                _scaler = None

        try:
            # Load SHAP explainer using joblib.load
            shap_data = joblib.load(SHAP_PATH)
            if isinstance(shap_data, dict):
                _explainer = shap_data.get("explainer")
                _expected_value = shap_data.get("expected_value", 0.0)
            else:
                _explainer = shap_data
                _expected_value = getattr(_explainer, "expected_value", 0.0)
        except Exception as e:
            logging.error(f"Failed to load SHAP explainer from {SHAP_PATH}: {e}")
            _explainer = None
            _expected_value = 0.0

    return _model, _scaler, _feature_cols, _explainer, _expected_value

def predict_transaction(input_dict: dict) -> dict:
    model, scaler, feature_cols, explainer, expected_value = load_models()

    # ── ML Inference Safety & Schema Checks ──────────
    for k, v in input_dict.items():
        if k in feature_cols or k in ["Amount", "Time"]:
            if v is not None:
                try:
                    f_val = float(v)
                except (TypeError, ValueError):
                    raise ValueError(f"Feature '{k}' must be a valid number.")
                if np.isnan(f_val) or np.isinf(f_val):
                    raise ValueError(f"Feature '{k}' contains invalid numeric value (NaN or Infinity).")

    # Validate range for Amount
    amount = input_dict.get("Amount", 100.0)
    try:
        amt_val = float(amount)
    except (TypeError, ValueError):
        raise ValueError("Amount must be a valid positive number.")
    if amt_val <= 0:
        raise ValueError("Amount must be greater than 0.")

    # Validate range for Time
    time_val = input_dict.get("Time", 50000.0)
    try:
        t_val = float(time_val)
    except (TypeError, ValueError):
        raise ValueError("Time must be a valid non-negative number.")
    if t_val < 0:
        raise ValueError("Time must be non-negative.")

    # Build feature vector matching training feature order exactly
    feat_vals = []
    for col in feature_cols:
        if col == "Amount_Scaled":
            val = float(input_dict.get("Amount", 100.0))
        elif col == "Time_Scaled":
            val = float(input_dict.get("Time", 50000.0))
        else:
            val = float(input_dict.get(col, 0.0))
        feat_vals.append(val)
    features = np.array([feat_vals])

    # Apply scaling transformation used during model training
    if scaler is not None:
        if hasattr(scaler, "transform"):
            try:
                amt_idx = feature_cols.index("Amount_Scaled") if "Amount_Scaled" in feature_cols else None
                time_idx = feature_cols.index("Time_Scaled") if "Time_Scaled" in feature_cols else None
                if amt_idx is not None:
                    features[0][amt_idx] = float(scaler.transform([[features[0][amt_idx]]])[0][0])
                if time_idx is not None:
                    features[0][time_idx] = float(scaler.transform([[features[0][time_idx]]])[0][0])
            except Exception as e:
                logging.error(f"Error during feature scaling: {e}")
                raise ValueError(f"Feature scaling failed: {e}")
        else:
            raise ValueError("Loaded scaler is invalid (missing 'transform' method).")

    # Run prediction
    fraud_score = float(model.predict_proba(features)[0][1])
    is_fraud = fraud_score > 0.5

    if fraud_score > 0.7:
        risk_level = "HIGH"
        risk_color = "#ef4444"
    elif fraud_score > 0.4:
        risk_level = "MEDIUM"
        risk_color = "#f59e0b"
    else:
        risk_level = "LOW"
        risk_color = "#10b981"

    top_features = []
    all_shap_vals = {}
    shap_base = 0.0
    explanation_status = "unavailable"

    # Compute actual SHAP explanations
    if explainer is not None:
        try:
            shap_vals = explainer.shap_values(features)
            # Handle list/ndarray output from TreeExplainer
            if isinstance(shap_vals, list):
                vals = shap_vals[1][0] if len(shap_vals) > 1 else shap_vals[0][0]
            elif isinstance(shap_vals, np.ndarray):
                if len(shap_vals.shape) == 3:  # (samples, classes, features)
                    vals = shap_vals[0][1] if shap_vals.shape[1] > 1 else shap_vals[0][0]
                elif len(shap_vals.shape) == 2:  # (samples, features)
                    vals = shap_vals[0]
                else:
                    vals = shap_vals
            else:
                vals = shap_vals

            # expected_value output formatting
            if isinstance(expected_value, (list, np.ndarray)):
                shap_base = float(expected_value[1] if len(expected_value) > 1 else expected_value[0])
            else:
                shap_base = float(expected_value)

            all_shap_vals = {feature_cols[i]: float(vals[i]) for i in range(len(feature_cols))}

            # Sort features by absolute SHAP value
            sorted_indices = np.argsort(np.abs(vals))[::-1]
            for idx in sorted_indices[:10]:
                sval = float(vals[idx])
                top_features.append({
                    "feature": feature_cols[idx],
                    "shap_value": round(sval, 4),
                    "direction": "increases fraud risk" if sval > 0 else "decreases fraud risk",
                    "impact": "HIGH" if abs(sval) > 0.1 else "MEDIUM" if abs(sval) > 0.05 else "LOW"
                })
            explanation_status = "explained"
        except Exception as e:
            logging.error(f"SHAP explanation calculation failed: {e}")
            top_features = []
            all_shap_vals = {}
            shap_base = 0.0
            explanation_status = "failed"

    # Set explanation text
    if explanation_status == "explained":
        top_name = top_features[0]["feature"] if top_features else "anomalous pattern"
        explanation = f"HIGH FRAUD RISK ({fraud_score*100:.1f}%): Flagged due to {top_name} anomaly." if is_fraud else f"LOW FRAUD RISK ({fraud_score*100:.1f}%): Transaction appears legitimate."
    else:
        explanation = f"FRAUD RISK ASSESSMENT ({fraud_score*100:.1f}%): Explanation unavailable (SHAP engine offline)."

    return {
        "fraud_score":      round(fraud_score, 4),
        "fraud_percentage": round(fraud_score * 100, 2),
        "is_fraud":         is_fraud,
        "risk_level":       risk_level,
        "risk_color":       risk_color,
        "explanation":      explanation,
        "top_features":     top_features,
        "all_shap_values":  all_shap_vals,
        "shap_base_value":  shap_base,
    }

def predict_batch(input_list: list, defer_shap: bool = False) -> list:
    if not input_list:
        return []

    model, scaler, feature_cols, explainer, expected_value = load_models()

    # 1. Parse and validate inputs in a fast loop
    feat_matrix = []
    valid_inputs = []
    errors = []

    # Pre-parse mapping of columns to indices
    amt_idx = feature_cols.index("Amount_Scaled") if "Amount_Scaled" in feature_cols else None
    time_idx = feature_cols.index("Time_Scaled") if "Time_Scaled" in feature_cols else None

    for idx, raw in enumerate(input_list):
        try:
            # Check NaN/Infinity ranges on input columns
            for k, v in raw.items():
                if k in feature_cols or k in ["Amount", "Time"]:
                    if v is not None:
                        try:
                            f_val = float(v)
                        except (TypeError, ValueError):
                            raise ValueError(f"Feature '{k}' must be a valid number.")
                        if np.isnan(f_val) or np.isinf(f_val):
                            raise ValueError(f"Feature '{k}' contains invalid numeric value (NaN or Infinity).")

            amount = float(raw.get("Amount", 100.0))
            if amount <= 0:
                raise ValueError("Amount must be greater than 0.")
            time_val = float(raw.get("Time", 50000.0))
            if time_val < 0:
                raise ValueError("Time must be non-negative.")

            feat_vals = []
            for col in feature_cols:
                if col == "Amount_Scaled":
                    val = amount
                elif col == "Time_Scaled":
                    val = time_val
                else:
                    val = float(raw.get(col, 0.0))
                feat_vals.append(val)
            
            feat_matrix.append(feat_vals)
            valid_inputs.append((idx, raw))
        except Exception as e:
            errors.append((idx, f"Validation error: {str(e)}"))

    if not feat_matrix:
        results = [None] * len(input_list)
        for idx, err in errors:
            results[idx] = {"error": err}
        return results

    features = np.array(feat_matrix)

    # 2. Vectorized Scaling
    if scaler is not None and hasattr(scaler, "transform"):
        try:
            if amt_idx is not None:
                features[:, amt_idx] = scaler.transform(features[:, amt_idx:amt_idx+1]).flatten()
            if time_idx is not None:
                features[:, time_idx] = scaler.transform(features[:, time_idx:time_idx+1]).flatten()
        except Exception as e:
            logging.error(f"Batch scaling failed: {e}")
            raise ValueError(f"Batch scaling failed: {e}")

    # 3. Batch Predict Proba
    try:
        prob_scores = model.predict_proba(features)[:, 1]
    except Exception as e:
        logging.error(f"Batch model prediction failed: {e}")
        raise ValueError(f"Batch model prediction failed: {e}")

    # 4. Batch SHAP values computation
    shap_vals_all = None
    shap_base = 0.0
    if explainer is not None and not defer_shap:
        try:
            shap_vals_raw = explainer.shap_values(features)
            if isinstance(shap_vals_raw, list):
                shap_vals_all = shap_vals_raw[1] if len(shap_vals_raw) > 1 else shap_vals_raw[0]
            elif isinstance(shap_vals_raw, np.ndarray):
                if len(shap_vals_raw.shape) == 3:
                    shap_vals_all = shap_vals_raw[:, 1, :] if shap_vals_raw.shape[1] > 1 else shap_vals_raw[:, 0, :]
                else:
                    shap_vals_all = shap_vals_raw
            
            if isinstance(expected_value, (list, np.ndarray)):
                shap_base = float(expected_value[1] if len(expected_value) > 1 else expected_value[0])
            else:
                shap_base = float(expected_value)
        except Exception as e:
            logging.error(f"Batch SHAP calculation failed: {e}")
            shap_vals_all = None

    # 5. Build results list matching the original order
    results = [None] * len(input_list)
    for idx, err in errors:
        results[idx] = {"error": err}

    for i, (original_idx, raw) in enumerate(valid_inputs):
        fraud_score = float(prob_scores[i])
        is_fraud = fraud_score > 0.5
        
        if fraud_score > 0.7:
            risk_level = "HIGH"
            risk_color = "#ef4444"
        elif fraud_score > 0.4:
            risk_level = "MEDIUM"
            risk_color = "#f59e0b"
        else:
            risk_level = "LOW"
            risk_color = "#10b981"

        top_features = []
        all_shap_vals = {}
        
        if shap_vals_all is not None:
            vals = shap_vals_all[i]
            all_shap_vals = {feature_cols[k]: float(vals[k]) for k in range(len(feature_cols))}
            sorted_indices = np.argsort(np.abs(vals))[::-1]
            for idx in sorted_indices[:10]:
                sval = float(vals[idx])
                top_features.append({
                    "feature": feature_cols[idx],
                    "shap_value": round(sval, 4),
                    "direction": "increases fraud risk" if sval > 0 else "decreases fraud risk",
                    "impact": "HIGH" if abs(sval) > 0.1 else "MEDIUM" if abs(sval) > 0.05 else "LOW"
                })
            top_name = top_features[0]["feature"] if top_features else "anomalous pattern"
            explanation = f"HIGH FRAUD RISK ({fraud_score*100:.1f}%): Flagged due to {top_name} anomaly." if is_fraud else f"LOW FRAUD RISK ({fraud_score*100:.1f}%): Transaction appears legitimate."
        else:
            if defer_shap:
                explanation = f"FRAUD RISK ASSESSMENT ({fraud_score*100:.1f}%): Explanation deferred for batch processing."
            else:
                explanation = f"FRAUD RISK ASSESSMENT ({fraud_score*100:.1f}%): Explanation unavailable (SHAP engine offline)."

        results[original_idx] = {
            "fraud_score":      round(fraud_score, 4),
            "fraud_percentage": round(fraud_score * 100, 2),
            "is_fraud":         is_fraud,
            "risk_level":       risk_level,
            "risk_color":       risk_color,
            "explanation":      explanation,
            "top_features":     top_features,
            "all_shap_values":  all_shap_vals,
            "shap_base_value":  shap_base,
        }

    return results

