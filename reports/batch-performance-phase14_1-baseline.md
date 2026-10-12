# Ingestion Performance Phase 14.1 Baseline Report

This report documents the detailed profiling baseline of the optimized batch transaction processing pipeline before applying Phase 14.1 PostgreSQL COPY optimizations.

## Environment & Configuration
* **Database Type:** PostgreSQL (Docker container)
* **Default Chunk Size:** 5,000
* **Celery Worker Concurrency:** 4
* **Measured Run Count:** 3 iterations after 1 warm-up iteration

## Stage-by-Stage Profiling Breakdown (Medians)

### 1,000 Transactions (SHAP Enabled)
* **CSV read/parsing time:** 0.0184s
* **validation/transformation time:** 0.0314s
* **XGBoost inference time:** 0.4882s
* **Python mapping/dictionary construction time:** 0.0279s
* **database insert time:** 0.5205s
* **database commit time:** 0.0259s
* **total median time:** 1.2126s
* **median throughput:** 824.66 records/sec
* **peak memory:** 332.67 MB

### 10,000 Transactions (SHAP Deferred)
* **CSV read/parsing time:** 0.0439s
* **validation/transformation time:** 0.1226s
* **XGBoost inference time:** 0.6050s
* **Python mapping/dictionary construction time:** 0.1693s
* **database insert time:** 1.2111s
* **database commit time:** 0.0656s
* **total median time:** 2.2175s
* **median throughput:** 4509.56 records/sec
* **peak memory:** 413.01 MB

### 50,000 Transactions (SHAP Deferred)
* **CSV read/parsing time:** 0.2131s
* **validation/transformation time:** 0.5114s
* **XGBoost inference time:** 3.3214s
* **Python mapping/dictionary construction time:** 0.9246s
* **database insert time:** 4.7363s
* **database commit time:** 0.1525s
* **total median time:** 9.5568s
* **median throughput:** 5231.86 records/sec
* **peak memory:** 453.30 MB

## Summary Table

| Dataset | CSV Read (Median) | Validation (Median) | XGBoost ML (Median) | DB Mapping (Median) | DB Insert (Median) | DB Commit (Median) | Total Time | Throughput |
|--------:|------------------:|--------------------:|--------------------:|--------------------:|-------------------:|-------------------:|-----------:|-----------:|
| 1,000 | 0.0184s | 0.0314s | 0.4882s | 0.0279s | 0.5205s | 0.0259s | 1.2126s | 824.66 rec/s |
| 10,000 | 0.0439s | 0.1226s | 0.6050s | 0.1693s | 1.2111s | 0.0656s | 2.2175s | 4509.56 rec/s |
| 50,000 | 0.2131s | 0.5114s | 3.3214s | 0.9246s | 4.7363s | 0.1525s | 9.5568s | 5231.86 rec/s |

## Bottleneck Analysis

Based on the profiling results:
1. The primary bottleneck for large batches (50,000 rows) is **DB Insertion**, taking **4.7363s** (49.6% of total).
2. The secondary bottleneck is **XGBoost inference**, taking **3.3214s** (34.8% of total).
