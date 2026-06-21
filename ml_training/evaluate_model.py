# ============================================================
#  evaluate_model.py  —  Full Model Evaluation Report
#  Run AFTER train_model.py
#  Run: python evaluate_model.py
# ============================================================

import joblib
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    classification_report, confusion_matrix,
    roc_auc_score, average_precision_score,
    precision_recall_curve, roc_curve,
    f1_score, precision_score, recall_score, accuracy_score
)
import warnings
warnings.filterwarnings("ignore")

MODEL_PATH = "../backend/ml/model.pkl"
DATA_PATH  = "data/creditcard.csv"
PLOTS_DIR  = "plots"

import os
os.makedirs(PLOTS_DIR, exist_ok=True)

print("=" * 60)
print("  📊 Model Evaluation Report")
print("=" * 60)

# Load
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

_, X_test, _, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

y_pred       = model.predict(X_test)
y_pred_proba = model.predict_proba(X_test)[:, 1]

# ─── Metrics ───────────────────────────
accuracy  = accuracy_score(y_test, y_pred)
precision = precision_score(y_test, y_pred)
recall    = recall_score(y_test, y_pred)
f1        = f1_score(y_test, y_pred)
roc_auc   = roc_auc_score(y_test, y_pred_proba)
avg_prec  = average_precision_score(y_test, y_pred_proba)

print(f"\n  {'Metric':<28} {'Score':>10}")
print("  " + "─" * 40)
print(f"  {'Accuracy':<28} {accuracy:>10.4f}")
print(f"  {'Precision (Fraud)':<28} {precision:>10.4f}")
print(f"  {'Recall (Fraud)':<28} {recall:>10.4f}")
print(f"  {'F1-Score (Fraud)':<28} {f1:>10.4f}")
print(f"  {'ROC-AUC':<28} {roc_auc:>10.4f}")
print(f"  {'Average Precision':<28} {avg_prec:>10.4f}")
print("  " + "─" * 40)

# Full classification report
print("\n" + classification_report(y_test, y_pred, target_names=["Legit", "Fraud"]))

# ─── Precision-Recall Curve ────────────
prec, rec, thresholds = precision_recall_curve(y_test, y_pred_proba)
plt.figure(figsize=(7, 5))
plt.plot(rec, prec, color="#00e5ff", lw=2, label=f"Avg Precision = {avg_prec:.4f}")
plt.xlabel("Recall"); plt.ylabel("Precision")
plt.title("Precision-Recall Curve", fontsize=14, fontweight="bold")
plt.legend(); plt.grid(alpha=0.3); plt.tight_layout()
plt.savefig(f"{PLOTS_DIR}/precision_recall.png", dpi=150)
print(f"\n  📈 Saved: {PLOTS_DIR}/precision_recall.png")

# ─── Threshold Analysis ─────────────────
print("\n  📊 Threshold Sensitivity:")
print(f"  {'Threshold':<12} {'Precision':>10} {'Recall':>10} {'F1':>10}")
print("  " + "─" * 44)
for thresh in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
    preds = (y_pred_proba >= thresh).astype(int)
    p = precision_score(y_test, preds, zero_division=0)
    r = recall_score(y_test, preds, zero_division=0)
    f = f1_score(y_test, preds, zero_division=0)
    marker = " ← default" if thresh == 0.5 else ""
    print(f"  {thresh:<12.1f} {p:>10.4f} {r:>10.4f} {f:>10.4f}{marker}")

print("\n" + "=" * 60)
print("  ✅ Evaluation Complete!")
print("=" * 60)
