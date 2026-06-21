import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from ml.predict import predict_transaction, load_models

def test_ml_safety_checks_nan_inf():
    # NaN check
    with pytest.raises(ValueError, match="contains invalid numeric value"):
        predict_transaction({"V1": float('nan'), "Amount": 100.0})

    # Infinity check
    with pytest.raises(ValueError, match="contains invalid numeric value"):
        predict_transaction({"V1": float('inf'), "Amount": 100.0})

def test_ml_safety_checks_ranges():
    # Negative amount
    with pytest.raises(ValueError, match="Amount must be greater than 0"):
        predict_transaction({"V1": 0.5, "Amount": -10.0})

    # Zero amount
    with pytest.raises(ValueError, match="Amount must be greater than 0"):
        predict_transaction({"V1": 0.5, "Amount": 0.0})

    # Negative time
    with pytest.raises(ValueError, match="Time must be non-negative"):
        predict_transaction({"V1": 0.5, "Amount": 100.0, "Time": -1.0})

def test_scaler_applied():
    model, scaler, feature_cols, explainer, expected_value = load_models()
    if scaler is not None:
        mock_scaler = MagicMock(wraps=scaler)
        with patch('ml.predict._scaler', mock_scaler):
            predict_transaction({"Amount": 250.0, "Time": 12345.0, "V1": 0.1})
            assert mock_scaler.transform.call_count >= 1

def test_feature_order_is_preserved():
    model, scaler, feature_cols, explainer, expected_value = load_models()
    mock_model = MagicMock(wraps=model)
    with patch('ml.predict._model', mock_model):
        predict_transaction({"Amount": 100.0, "Time": 50000.0, "V1": 0.5})
        args, kwargs = mock_model.predict_proba.call_args
        features_array = args[0]
        assert features_array.shape == (1, len(feature_cols))
        v1_idx = feature_cols.index("V1")
        assert features_array[0][v1_idx] == 0.5

def test_shap_values_real_or_unavailable():
    model, scaler, feature_cols, explainer, expected_value = load_models()
    if explainer is not None:
        res = predict_transaction({"Amount": 100.0, "Time": 50000.0, "V1": 0.5})
        assert "top_features" in res
        assert "all_shap_values" in res
        assert res["shap_base_value"] is not None
        assert "ASSESSMENT" in res["explanation"].upper() or "RISK" in res["explanation"].upper()
        assert "Explanation unavailable" not in res["explanation"]

    with patch('ml.predict._explainer', None):
        res = predict_transaction({"Amount": 100.0, "Time": 50000.0, "V1": 0.5})
        assert res["top_features"] == []
        assert res["all_shap_values"] == {}
        assert res["shap_base_value"] == 0.0
        assert "Explanation unavailable" in res["explanation"]
