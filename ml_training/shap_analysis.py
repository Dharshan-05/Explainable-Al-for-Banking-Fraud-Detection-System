# ============================================================
#  shap_analysis.py  —  SHAP Explainability for Fraud Detection
#  Run AFTER train_model.py
#  Run: python shap_analysis.py
# ============================================================

import joblib
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use("Agg")
import shap
import warnings
warnings.filterwarnings("ignore")

MODEL_PATH = "../backend/ml/model.pkl"
DATA_PATH  = "data/creditcard.csv"
PLOTS_DIR  = "plots"

import os
os.makedirs(PLOTS_DIR, exist_ok=True)

print("=" * 60)
print("  🔍 SHAP Explainability Analysis")
print("=" * 60)

# ─────────────────────────────────────────
#  Load model & data
# ─────────────────────────────────────────
print("\n[1/4] Loading model and data...")
model_data   = joblib.load(MODEL_PATH)
model        = model_data["model"]
scaler       = model_data["scaler"]
feature_cols = model_data["feature_cols"]

df = pd.read_csv(DATA_PATH)
df["Amount_Scaled"] = scaler.fit_transform(df[["Amount"]])
df["Time_Scaled"]   = scaler.fit_transform(df[["Time"]])
df.drop(columns=["Amount", "Time"], inplace=True)

X = df[feature_cols].values
y = df["Class"].values

# Use sample for speed (SHAP is slow on full dataset)
SAMPLE_SIZE = 1000
idx = np.random.choice(len(X), SAMPLE_SIZE, replace=False)
X_sample = X[idx]
print(f"  ✅ Using {SAMPLE_SIZE} samples for SHAP analysis")

# ─────────────────────────────────────────
#  Compute SHAP values
# ─────────────────────────────────────────
print("\n[2/4] Computing SHAP values (this may take ~30 seconds)...")
explainer   = shap.TreeExplainer(model)
shap_values = explainer.shap_values(X_sample)
print("  ✅ SHAP values computed!")

# ─────────────────────────────────────────
#  Plot 1: Summary Plot (Beeswarm)
# ─────────────────────────────────────────
print("\n[3/4] Generating plots...")

plt.figure()
shap.summary_plot(
    shap_values, X_sample,
    feature_names=feature_cols,
    show=False, max_display=20
)
plt.title("SHAP Summary — Feature Impact on Fraud Detection", fontweight="bold")
plt.tight_layout()
plt.savefig(f"{PLOTS_DIR}/shap_summary.png", dpi=150, bbox_inches="tight")
print(f"  📈 Saved: {PLOTS_DIR}/shap_summary.png")

# Plot 2: Bar Plot (mean |SHAP|)
plt.figure()
shap.summary_plot(
    shap_values, X_sample,
    feature_names=feature_cols,
    plot_type="bar", show=False, max_display=20
)
plt.title("Top Features by Mean |SHAP| Value", fontweight="bold")
plt.tight_layout()
plt.savefig(f"{PLOTS_DIR}/shap_bar.png", dpi=150, bbox_inches="tight")
print(f"  📈 Saved: {PLOTS_DIR}/shap_bar.png")

# Plot 3: Waterfall for a FRAUD transaction
fraud_idx = np.where(y[idx] == 1)[0]
if len(fraud_idx) > 0:
    i = fraud_idx[0]
    plt.figure()
    shap.waterfall_plot(
        shap.Explanation(
            values        = shap_values[i],
            base_values   = explainer.expected_value,
            data          = X_sample[i],
            feature_names = feature_cols
        ),
        show=False, max_display=15
    )
    plt.title("SHAP Waterfall — Why This Transaction Was Flagged", fontweight="bold")
    plt.tight_layout()
    plt.savefig(f"{PLOTS_DIR}/shap_waterfall_fraud.png", dpi=150, bbox_inches="tight")
    print(f"  📈 Saved: {PLOTS_DIR}/shap_waterfall_fraud.png")

# ─────────────────────────────────────────
#  Save SHAP explainer for API use
# ─────────────────────────────────────────
print("\n[4/4] Saving SHAP explainer...")
shap_data = {
    "explainer"      : explainer,
    "expected_value" : explainer.expected_value,
    "feature_cols"   : feature_cols
}
joblib.dump(shap_data, "../backend/ml/shap_explainer.pkl")
print("  ✅ Saved: ../backend/ml/shap_explainer.pkl")

print("\n" + "=" * 60)
print("  🎉 SHAP Analysis Complete!")
print("  The API will use the explainer to explain every prediction.")
print("=" * 60)
