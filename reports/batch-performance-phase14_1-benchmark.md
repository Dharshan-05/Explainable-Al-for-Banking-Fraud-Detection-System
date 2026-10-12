# Ingestion Performance Phase 14.1 Benchmark Report

This report documents the performance measurements of the batch transaction processing pipeline after implementing Phase 14.1 PostgreSQL COPY fast path optimization.

## Environment & Configuration
* **Database Type:** PostgreSQL (Docker container)
* **Optimized Chunk Size:** 10,000
* **Celery Worker Concurrency:** 4
* **Measured Run Count:** 3 iterations after 1 warm-up iteration

## Stage-by-Stage Profiling Breakdown (Medians)

### 1,000 Transactions (SHAP Enabled)
* **CSV read/parsing & validation time:** 0.0297s
* **XGBoost inference time:** 0.3499s
* **Python mapping/dictionary construction time:** 0.0704s
* **database COPY insert time:** 0.1791s
* **database commit time:** 0.0003s
* **total median time:** 0.6427s
* **median throughput:** 1556.01 records/sec
* **peak memory:** 329.23 MB

### 10,000 Transactions (SHAP Deferred)
* **CSV read/parsing & validation time:** 0.1749s
* **XGBoost inference time:** 0.9150s
* **Python mapping/dictionary construction time:** 0.3484s
* **database COPY insert time:** 0.5374s
* **database commit time:** 0.0002s
* **total median time:** 2.0229s
* **median throughput:** 4943.49 records/sec
* **peak memory:** 433.94 MB

### 50,000 Transactions (SHAP Deferred)
* **CSV read/parsing & validation time:** 0.9303s
* **XGBoost inference time:** 3.0852s
* **Python mapping/dictionary construction time:** 2.2721s
* **database COPY insert time:** 2.1264s
* **database commit time:** 0.0021s
* **total median time:** 8.2860s
* **median throughput:** 6034.28 records/sec
* **peak memory:** 507.94 MB

## Final Comparison Table

| Dataset | Previous Median Time | New Median Time | Previous Throughput | New Throughput | Improvement | Chunk Size | DB Path | SHAP Mode |
| ------- | -------------------: | --------------: | ------------------: | -------------: | ----------: | ---------: | ------- | --------- |
| 1,000 | 1.2126s | 0.6427s | 824.66 rec/s | 1556.01 rec/s | 47.00% | 10000 | PostgreSQL COPY | Enabled |
| 10,000 | 2.2175s | 2.0229s | 4509.56 rec/s | 4943.49 rec/s | 8.78% | 10000 | PostgreSQL COPY | Deferred |
| 50,000 | 9.5568s | 8.2860s | 5231.86 rec/s | 6034.28 rec/s | 13.30% | 10000 | PostgreSQL COPY | Deferred |

## Key Findings

1. **Database Persistence Bottleneck Resolved:** PostgreSQL COPY fast-path insertion reduces database persistence time significantly compared to SQLAlchemy bulk insert.
2. **Redundant CSV Line Scan Removed:** Stream-based Pandas chunk processing and dynamic byte-progress tracking completely avoid the line-by-line pre-scan overhead.
