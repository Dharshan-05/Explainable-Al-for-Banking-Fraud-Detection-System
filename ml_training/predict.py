import joblib
import pickle
import numpy as np
import os

BASE_DIR    = os.path.dirname(__file__)
MODEL_PATH  = os.path.join(BASE_DIR, 'model.pkl')
SCALER_PATH = os.path.join(BASE_DIR, 'scaler.pkl')
SHAP_PATH   = os.path.join(BASE_DIR, 'shap_explainer.pkl')

_model        = None
_scaler       = None
_explainer    = None
_feature_cols = None

# Default feature names matching train_model.py output
DEFAULT_FEATURES = [f'V{i}' for i in range(1, 29)] + ['Amount_Scaled', 'Time_Scaled']


def load_models():
    global _model, _scaler, _explainer, _feature_cols

    if _model is None:
        # Load model — supports both joblib dict and raw pickle
        raw = joblib.load(MODEL_PATH)
        if isinstance(raw, dict):
            _model        = raw['model']
            _scaler       = raw.get('scaler', None)
            _feature_cols = raw.get('feature_cols', DEFAULT_FEATURES)
        else:
            _model        = raw
            _feature_cols = DEFAULT_FEATURES

        # Load scaler separately if not already loaded from dict
        if _scaler is None:
            try:
                s = joblib.load(SCALER_PATH)
                _scaler = s if hasattr(s, 'transform') else None
            except:
                _scaler = None

        # Load SHAP explainer
        try:
            with open(SHAP_PATH, 'rb') as f:
                _explainer = pickle.load(f)
        except:
            _explainer = None

    return _model, _scaler, _feature_cols, _explainer


def predict_transaction(input_dict: dict) -> dict:
    model, scaler, feature_cols, explainer = load_models()

    # Build feature vector — handle both scaled and raw Amount/Time
    feat_vals = []
    for col in feature_cols:
        if col == 'Amount_Scaled':
            val = float(input_dict.get('Amount', input_dict.get('Amount_Scaled', 100)))
        elif col == 'Time_Scaled':
            val = float(input_dict.get('Time', input_dict.get('Time_Scaled', 50000)))
        else:
            val = float(input_dict.get(col, 0))
        feat_vals.append(val)

    features = np.array([feat_vals])

    # Scale Amount/Time columns if scaler available
    if scaler and hasattr(scaler, 'transform'):
        try:
            # Only scale Amount_Scaled and Time_Scaled columns
            amt_idx  = feature_cols.index('Amount_Scaled') if 'Amount_Scaled' in feature_cols else None
            time_idx = feature_cols.index('Time_Scaled')   if 'Time_Scaled'   in feature_cols else None
            if amt_idx is not None:
                features[0][amt_idx] = scaler.transform([[features[0][amt_idx]]])[0][0]
            if time_idx is not None:
                features[0][time_idx] = scaler.transform([[features[0][time_idx]]])[0][0]
        except:
            pass

    fraud_score = float(model.predict_proba(features)[0][1])
    is_fraud    = fraud_score > 0.5

    if fraud_score > 0.7:
        risk_level = 'HIGH';   risk_color = '#ef4444'
    elif fraud_score > 0.4:
        risk_level = 'MEDIUM'; risk_color = '#f59e0b'
    else:
        risk_level = 'LOW';    risk_color = '#10b981'

    top_features  = []
    all_shap_vals = {}
    shap_base     = 0.0

    try:
        if explainer:
            shap_vals = explainer.shap_values(features)
            vals = shap_vals[1][0] if isinstance(shap_vals, list) else shap_vals[0]
            shap_base = float(
                explainer.expected_value[1]
                if isinstance(explainer.expected_value, (list, np.ndarray))
                else explainer.expected_value
            )
            all_shap_vals = {feature_cols[i]: float(vals[i]) for i in range(len(feature_cols))}
            for idx in np.argsort(np.abs(vals))[::-1][:10]:
                sval = float(vals[idx])
                top_features.append({
                    'feature':    feature_cols[idx],
                    'shap_value': round(sval, 4),
                    'direction':  'increases fraud risk' if sval > 0 else 'decreases fraud risk',
                    'impact':     'HIGH' if abs(sval) > 0.1 else 'MEDIUM' if abs(sval) > 0.05 else 'LOW',
                })
    except:
        try:
            importances = model.feature_importances_
            for idx in np.argsort(importances)[::-1][:10]:
                imp = float(importances[idx])
                top_features.append({
                    'feature':    feature_cols[idx],
                    'shap_value': round(imp * (1 if is_fraud else -1), 4),
                    'direction':  'increases fraud risk' if is_fraud else 'decreases fraud risk',
                    'impact':     'HIGH' if imp > 0.1 else 'MEDIUM' if imp > 0.05 else 'LOW',
                })
        except:
            pass

    top_name    = top_features[0]['feature'] if top_features else 'anomalous pattern'
    explanation = (
        f"HIGH FRAUD RISK ({fraud_score*100:.1f}%): Flagged due to {top_name} anomaly."
        if is_fraud else
        f"LOW FRAUD RISK ({fraud_score*100:.1f}%): Transaction appears legitimate."
    )

    return {
        'fraud_score':      round(fraud_score, 4),
        'fraud_percentage': round(fraud_score * 100, 2),
        'is_fraud':         is_fraud,
        'risk_level':       risk_level,
        'risk_color':       risk_color,
        'explanation':      explanation,
        'top_features':     top_features,
        'all_shap_values':  all_shap_vals,
        'shap_base_value':  shap_base,
    }


def predict_batch(input_list: list) -> list:
    return [predict_transaction(item) for item in input_list]
