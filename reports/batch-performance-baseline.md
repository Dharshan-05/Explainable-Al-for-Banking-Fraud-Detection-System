# Ingestion Performance Baseline Report

This report documents the performance baseline of the batch transaction processing pipeline in FraudGuard XAI before applying optimizations.

The baseline measurements were conducted inside the Docker Compose environment using PostgreSQL for persistence, Redis as the broker, and Celery for background task execution.

## Measured Baseline Bottlenecks

Across all sizes, the primary bottlenecks are:
1. **Database Insertion & Commit (SQLAlchemy ORM):** Consumes **62% to 65%** of total processing time for large uploads. The row-by-row loops (`db.add(txn)`) incur high ORM overhead.
2. **CSV Parsing & Validation (built-in `csv.DictReader`):** Consumes **18% to 19%** of processing time. Row-by-row parsing and key normalization in Python loops add significant CPU overhead.
3. **ML Inference (XGBoost & SHAP):** When SHAP is enabled (for datasets $\le$ 1,000 rows), SHAP explainer computation consumes the vast majority of execution time (~4 seconds out of 5 seconds total). When SHAP is deferred ($\ge$ 1,000 rows), vectorized XGBoost inference is highly optimized and runs very fast.

---

## Detailed Performance Baseline Metrics

The following metrics were measured for different dataset sizes:

### 1. 1,000 Transactions (SHAP Enabled)
* **Mock Upload receive/write time:** 0.0216s
* **CSV Parsing & Validation:** 0.0507s (Parsed: 994, Failed: 6)
* **Vectorized XGBoost Inference:** 4.0443s (SHAP Explainer computation active)
* **DB Insertion & Commit:** 0.9230s
* **Total Time:** 5.0397s
* **Throughput:** 197.24 records/second
* **Peak Memory:** 310.86 MB

### 2. 10,000 Transactions (SHAP Deferred)
* **Mock Upload receive/write time:** 0.0253s
* **CSV Parsing & Validation:** 0.7776s (Parsed: 9885, Failed: 115)
* **Vectorized XGBoost Inference:** 1.8065s
* **DB Insertion & Commit:** 4.3698s
* **Total Time:** 6.9793s
* **Throughput:** 1,416.34 records/second
* **Peak Memory:** 448.81 MB

### 3. 50,000 Transactions (SHAP Deferred)
* **Mock Upload receive/write time:** 0.0096s
* **CSV Parsing & Validation:** 3.5059s (Parsed: 49572, Failed: 428)
* **Vectorized XGBoost Inference:** 2.9718s
* **DB Insertion & Commit:** 12.1663s
* **Total Time:** 18.6536s
* **Throughput:** 2,657.50 records/second
* **Peak Memory:** 1,003.89 MB

---

## Summary Table

| Dataset Size | SHAP Mode | CSV Parse & Val Time | ML Inference Time | DB Insert & Commit Time | Total Task Time | Throughput | Peak Process Memory |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1,000** | Enabled | 0.0507s | 4.0443s | 0.9230s | 5.0397s | 197.24 rec/s | 310.86 MB |
| **10,000** | Deferred | 0.7776s | 1.8065s | 4.3698s | 6.9793s | 1,416.34 rec/s | 448.81 MB |
| **50,000** | Deferred | 3.5059s | 2.9718s | 12.1663s | 18.6536s | 2,657.50 rec/s | 1,003.89 MB |

---

## Technical Recommendations for Optimization

1. **Implement SQLAlchemy Core Bulk Insertion:** Using `db.execute(insert(Transaction), list_of_dicts)` will bypass ORM state tracking overhead, reducing database commit time by ~50%.
2. **Implement Vectorized Pandas CSV Ingestion:** Replacing `csv.DictReader` with `pandas.read_csv` and vectorized validation filters will reduce CSV parsing/validation time by ~70% while remaining memory-safe.
3. **Controlled Concurrency:** Limit XGBoost parallel thread usage (`OMP_NUM_THREADS=1`) in workers to prevent CPU thread thrashing.
