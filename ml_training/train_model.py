# ============================================================
#  train_model.py  —  Fraud Detection XAI
#  XGBoost + SMOTE + SHAP + MLflow Experiment Tracking
#  Run: python train_model.py
# ============================================================

import os
import joblib
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import mlflow
import mlflow.xgboost

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    classification_report, confusion_matrix,
    roc_auc_score, roc_curve,
    average_precision_score
)
from imblearn.over_sampling import SMOTE
from xgboost import XGBClassifier
import shap
import warnings
warnings.filterwarnings("ignore")

# ─────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────
DATA_PATH   = "data/creditcard.csv"
MODEL_DIR   = "../backend/ml"
MODEL_PATH  = os.path.join(MODEL_DIR, "model.pkl")
SCALER_PATH = os.path.join(MODEL_DIR, "scaler.pkl")
PLOTS_DIR   = "plots"
MLFLOW_URI  = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5001")

os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(PLOTS_DIR, exist_ok=True)

# ─────────────────────────────────────────
#  MLflow Setup
# ─────────────────────────────────────────
mlflow.set_tracking_uri(MLFLOW_URI)
mlflow.set_experiment("fraud-detection-xgboost")

print("=" * 60)
print("  🏦 Fraud Detection — XGBoost Training Pipeline")
print("=" * 60)

with mlflow.start_run(run_name="xgboost-smote-training"):

    # ─────────────────────────────────────────
    #  1. LOAD DATA
    # ─────────────────────────────────────────
    print("\n[1/7] Loading dataset...")
    df = pd.read_csv(DATA_PATH)
    print(f"  ✅ Loaded {len(df):,} transactions")
    print(f"  ✅ Features : {df.shape[1]} columns")
    print(f"  ✅ Fraud    : {df['Class'].sum():,} ({df['Class'].mean()*100:.3f}%)")
    print(f"  ✅ Legit    : {(df['Class']==0).sum():,}")

    # ─────────────────────────────────────────
    #  2. PREPROCESSING
    # ─────────────────────────────────────────
    print("\n[2/7] Preprocessing...")

    # Scale Amount and Time (V1-V28 are already PCA-transformed)
    scaler = StandardScaler()
    df["Amount_Scaled"] = scaler.fit_transform(df[["Amount"]])
    df["Time_Scaled"]   = scaler.fit_transform(df[["Time"]])
    df.drop(columns=["Amount", "Time"], inplace=True)

    # Features & Target
    FEATURE_COLS = [c for c in df.columns if c != "Class"]
    X = df[FEATURE_COLS].values
    y = df["Class"].values
    print(f"  ✅ Feature columns : {len(FEATURE_COLS)}")

    # ─────────────────────────────────────────
    #  3. TRAIN / TEST SPLIT
    # ─────────────────────────────────────────
    print("\n[3/7] Splitting data...")
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    print(f"  ✅ Train : {len(X_train):,} | Test : {len(X_test):,}")

    # ─────────────────────────────────────────
    #  4. SMOTE — Handle Class Imbalance
    # ─────────────────────────────────────────
    print("\n[4/7] Applying SMOTE to balance classes...")
    smote = SMOTE(random_state=42)
    X_train_res, y_train_res = smote.fit_resample(X_train, y_train)
    print(f"  ✅ After SMOTE — Fraud: {y_train_res.sum():,} | Legit: {(y_train_res==0).sum():,}")

    # ─────────────────────────────────────────
    #  5. TRAIN XGBOOST MODEL
    # ─────────────────────────────────────────
    print("\n[5/7] Training XGBoost model...")

    PARAMS = {
        "n_estimators":     300,
        "max_depth":        6,
        "learning_rate":    0.05,
        "subsample":        0.8,
        "colsample_bytree": 0.8,
        "scale_pos_weight": 1,   # balanced by SMOTE
        "eval_metric":      "auc",
        "random_state":     42,
        "n_jobs":           -1,
    }
    mlflow.log_params({**PARAMS, "smote": True, "test_size": 0.2})

    model = XGBClassifier(use_label_encoder=False, **PARAMS)
    model.fit(
        X_train_res, y_train_res,
        eval_set=[(X_test, y_test)],
        verbose=50
    )
    print("  ✅ Training complete!")

    # ─────────────────────────────────────────
    #  6. EVALUATE
    # ─────────────────────────────────────────
    print("\n[6/7] Evaluating model...")

    y_pred       = model.predict(X_test)
    y_pred_proba = model.predict_proba(X_test)[:, 1]
    roc_auc      = roc_auc_score(y_test, y_pred_proba)
    avg_prec     = average_precision_score(y_test, y_pred_proba)

    print("\n" + "─" * 50)
    print("  📊 MODEL PERFORMANCE REPORT")
    print("─" * 50)
    print(classification_report(y_test, y_pred, target_names=["Legit", "Fraud"]))
    print(f"  ROC-AUC Score          : {roc_auc:.4f}")
    print(f"  Average Precision Score: {avg_prec:.4f}")
    print("─" * 50)

    # Log metrics to MLflow
    mlflow.log_metrics({
        "roc_auc":       roc_auc,
        "avg_precision": avg_prec,
        "train_samples": int(len(X_train_res)),
        "test_samples":  int(len(X_test)),
    })

    # Confusion Matrix Plot
    cm = confusion_matrix(y_test, y_pred)
    plt.figure(figsize=(6, 5))
    sns.heatmap(cm, annot=True, fmt="d", cmap="Blues",
                xticklabels=["Legit", "Fraud"],
                yticklabels=["Legit", "Fraud"])
    plt.title("Confusion Matrix", fontsize=14, fontweight="bold")
    plt.ylabel("Actual"); plt.xlabel("Predicted")
    plt.tight_layout()
    plt.savefig(f"{PLOTS_DIR}/confusion_matrix.png", dpi=150)
    mlflow.log_artifact(f"{PLOTS_DIR}/confusion_matrix.png", "plots")
    print(f"\n  📈 Saved: {PLOTS_DIR}/confusion_matrix.png")

    # ROC Curve
    fpr, tpr, _ = roc_curve(y_test, y_pred_proba)
    plt.figure(figsize=(7, 5))
    plt.plot(fpr, tpr, color="#00e5ff", lw=2, label=f"ROC AUC = {roc_auc:.4f}")
    plt.plot([0,1],[0,1],"k--", lw=1)
    plt.xlabel("False Positive Rate"); plt.ylabel("True Positive Rate")
    plt.title("ROC Curve — Fraud Detection", fontsize=14, fontweight="bold")
    plt.legend(); plt.tight_layout()
    plt.savefig(f"{PLOTS_DIR}/roc_curve.png", dpi=150)
    mlflow.log_artifact(f"{PLOTS_DIR}/roc_curve.png", "plots")
    print(f"  📈 Saved: {PLOTS_DIR}/roc_curve.png")

    # Feature Importance
    feat_imp = pd.Series(model.feature_importances_, index=FEATURE_COLS)
    top20 = feat_imp.nlargest(20)
    plt.figure(figsize=(8, 7))
    top20.sort_values().plot(kind="barh", color="#a855f7")
    plt.title("Top 20 Feature Importances", fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.savefig(f"{PLOTS_DIR}/feature_importance.png", dpi=150)
    mlflow.log_artifact(f"{PLOTS_DIR}/feature_importance.png", "plots")
    print(f"  📈 Saved: {PLOTS_DIR}/feature_importance.png")

    # ─────────────────────────────────────────
    #  7. SAVE MODEL
    # ─────────────────────────────────────────
    print("\n[7/7] Saving model...")

    model_data = {
        "model"        : model,
        "scaler"       : scaler,
        "feature_cols" : FEATURE_COLS,
        "roc_auc"      : roc_auc,
        "avg_precision": avg_prec,
        "n_features"   : len(FEATURE_COLS)
    }

    joblib.dump(model_data, MODEL_PATH)
    joblib.dump(scaler,     SCALER_PATH)

    print(f"  ✅ Model saved  → {MODEL_PATH}")
    print(f"  ✅ Scaler saved → {SCALER_PATH}")

    # Log model artifact to MLflow
    mlflow.xgboost.log_model(model, artifact_path="xgboost_model")
    mlflow.log_artifact(MODEL_PATH, artifact_path="joblib_artifacts")
    print(f"  ✅ MLflow run logged → {MLFLOW_URI}")

    print("\n" + "=" * 60)
    print("  🎉 Training Pipeline Complete!")
    print(f"  ROC-AUC: {roc_auc:.4f}  |  Avg Precision: {avg_prec:.4f}")
    print("=" * 60)
