# 🛡️ FraudGuard XAI — Real-Time Explainable AI Banking Fraud Detection System

<p align="center">
  <img src="screenshots/dashboard.png" alt="FraudGuard XAI Dashboard" width="100%" />
</p>

<p align="center">
  <strong>An enterprise-grade, role-based banking fraud intelligence and real-time monitoring platform powered by XGBoost, SHAP explainability, FastAPI, Next.js 14, Celery, and PostgreSQL.</strong>
</p>

<p align="center">
  <a href="https://github.com/Dharshan-05/Explainable-Al-for-Banking-Fraud-Detection-System/actions"><img src="https://img.shields.io/badge/CI%2FCD-Passing-emerald?style=for-the-badge&logo=githubactions&logoColor=white" alt="CI/CD Status" /></a>
  <a href="#-machine-learning--xai-pipeline"><img src="https://img.shields.io/badge/Model-XGBoost%202.0-blue?style=for-the-badge&logo=scikitlearn&logoColor=white" alt="Model" /></a>
  <a href="#-machine-learning--xai-pipeline"><img src="https://img.shields.io/badge/XAI-TreeSHAP-orange?style=for-the-badge" alt="Explainability" /></a>
  <a href="#-tech-stack"><img src="https://img.shields.io/badge/FastAPI-0.109-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" /></a>
  <a href="#-tech-stack"><img src="https://img.shields.io/badge/Next.js-14%20App%20Router-black?style=for-the-badge&logo=next.js&logoColor=white" alt="Next.js" /></a>
  <a href="#-tech-stack"><img src="https://img.shields.io/badge/TypeScript-5.3-3178C6?style=for-the-badge&logo=typescript&logoColor=white" alt="TypeScript" /></a>
  <a href="#-tech-stack"><img src="https://img.shields.io/badge/Celery-5.3%20%7C%20Redis%207-green?style=for-the-badge&logo=celery&logoColor=white" alt="Celery" /></a>
  <a href="#-tech-stack"><img src="https://img.shields.io/badge/PostgreSQL-15-336791?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL" /></a>
  <a href="#-enterprise-readiness--audit"><img src="https://img.shields.io/badge/Readiness%20Score-95%2F100-success?style=for-the-badge" alt="Readiness" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" alt="License" /></a>
</p>

---

> [!NOTE]
> **Project Classification:** Enterprise-grade portfolio / startup MVP demonstration showcase. Demonstrates multi-tenant banking security protocols, scalable asynchronous message queuing, generation-fenced durable batch pipelines, and game-theoretic explainable ML. *Not affiliated with or connected to live commercial banking networks.*

---

## 📑 Table of Contents

- [Executive Overview](#-executive-overview)
- [System Architecture & Data Flow](#-system-architecture--data-flow)
- [Key Features & Capabilities](#-key-features--capabilities)
- [UI & Explainability Showcase](#-ui--explainability-showcase)
- [Technology Stack Matrix](#-technology-stack-matrix)
- [Machine Learning & XAI Pipeline](#-machine-learning--xai-pipeline)
- [Comprehensive REST & WebSocket API](#-comprehensive-rest--websocket-api)
- [Database Architecture & Migrations](#-database-architecture--migrations)
- [Security Model & Role-Based Access Control](#-security-model--role-based-access-control)
- [Audit Logging & Observability](#-audit-logging--observability)
- [Quickstart & Setup Instructions](#-quickstart--setup-instructions)
- [Running Tests & Quality Assurance](#-running-tests--quality-assurance)
- [Enterprise Readiness & Audit](#-enterprise-readiness--audit)
- [Full Documentation & Reports](#-full-documentation--reports)
- [License & Authors](#-license--authors)

---

## 🚀 Executive Overview

In financial fraud detection, traditional machine learning models operate as opaque black boxes. When an algorithm flags a legitimate customer transaction or misses a complex fraud pattern, risk analysts face critical operational friction:
1. **Lack of Decision Transparency:** Compliance officers and fraud analysts cannot immediately verify *why* a transaction was assigned a high risk probability.
2. **Regulatory Mandates:** Legal frameworks (such as GDPR Article 22, FCRA, and the EU AI Act) strictly mandate actionable explanations for automated decision systems that materially impact financial transactions.
3. **Operational Bottlenecks:** Without clear feature attribution, manual investigator reviews require combing through raw ledger logs and disparate data sources.

**FraudGuard XAI** solves this challenge by pairing a high-performance **XGBoost** classification pipeline with real-time **SHAP (SHapley Additive exPlanations)**. The system provides instantaneous risk probabilities alongside mathematically grounded feature impact directions (e.g., *"Amount deviation +$840 increases risk by +28%"*), streams instant alerts via authenticated **WebSockets**, and handles high-throughput batch uploads of hundreds of thousands of records via a durable, generation-fenced PostgreSQL-backed Celery worker architecture.

---

## 🏗️ System Architecture & Data Flow

The platform operates as a decoupled microservice architecture orchestrated via Docker Compose:

```mermaid
flowchart TD
    subgraph ClientLayer ["Client Presentation Layer (Next.js 14)"]
        Browser["Analyst / Admin Browser"]
        Zustand["Zustand Central Store"]
        UI["Tailwind CSS + Recharts UI"]
        Browser <--> Zustand
        Zustand <--> UI
    end

    subgraph APILayer ["API Gateway & Core Service Layer (FastAPI)"]
        Gateway["FastAPI ASGI Gatekeeper (Port 8000)"]
        Security["deps.py (JWT Cookie Auth + CSRF Validator + RBAC)"]
        AuditService["Audit & Structured JSON Logging"]
        WSManager["WebSocket Alert Channel Manager"]
        
        Gateway --> Security
        Security --> AuditService
        Gateway --> WSManager
    end

    subgraph AsyncWorkerLayer ["Asynchronous Batch & ML Layer"]
        RedisQueue[("Redis 7 (Broker & Result Cache)")]
        CeleryWorker["Celery 5 Worker Pool (Concurrency=4)"]
        SharedVolume[("Shared Uploads Volume (/app/uploads)")]
        MLModel["XGBoost 2.0 Classifier"]
        SHAPEngine["SHAP 0.44 TreeExplainer"]
        
        Gateway -- "1. Upload CSV" --> SharedVolume
        Gateway -- "2. Enqueue Task" --> RedisQueue
        RedisQueue --> CeleryWorker
        SharedVolume -. "3. Stream 5k-Row Chunks" .-> CeleryWorker
        CeleryWorker --> MLModel
        CeleryWorker --> SHAPEngine
    end

    subgraph StorageLayer ["Persistence & Governance Layer"]
        Postgres[("PostgreSQL 15 (frauddb)")]
        Alembic["Alembic Migrations Engine"]
        Reconciler["Celery Beat Background Reconciler"]
        
        Gateway -- "Async Queries" --> Postgres
        CeleryWorker -- "Atomic Chunk Writes & COPY" --> Postgres
        Reconciler -- "Lease Heartbeats & CAS Recovery" --> Postgres
        Alembic -. "Schema Sync" .-> Postgres
    end

    Browser <== "HTTP-Only REST & CSRF Headers" ==> Gateway
    WSManager <== "Live WSS Fraud Alerts" ==> Browser
```

---

## ⚡ Key Features & Capabilities

### 1. Real-Time Explainable Inference (<15ms)
- Predicts transaction risk with an optimized XGBoost model.
- Automatically computes game-theoretic **SHAP** values for single transactions, identifying top risk-increasing and risk-decreasing features.
- Validates input arrays for missing values, infinite limits, and strict schema ordering before model execution.

### 2. High-Throughput Batch Processing (~6,000+ recs/sec)
- Partitions massive CSV uploads (e.g., 284k+ rows) into configurable 5,000-record chunks.
- Executes fully vectorized NumPy/Pandas scaling, matrix model inference, and bulk commits.
- Uses **SHAP Deferral Logic**: Dynamically skips expensive individual Shapley computation for large bulk workloads (>1,000 rows) to preserve high throughput while transparently marking explanation status.
- **Memory-Safe Payloads**: Celery task results truncate return arrays to the first 100 sample predictions for bulk runs, preventing JSON serialization memory bloat and API OOM errors.

### 3. Durable PostgreSQL-Backed Batch Pipeline
- Full state machine backed by `BatchJob` and `BatchJobChunk` database tables.
- **Generation Fencing (CAS Tokens)**: Prevents split-brain worker races and duplicate chunk processing.
- **Background Lease Reconciler (`batch_reconciler.py`)**: Runs every 60 seconds via Celery Beat, reclaiming orphaned or stalled jobs after worker node failures without data loss.

### 4. Real-Time WebSocket Alerts
- Automatically broadcasts newly predicted high-risk transactions (`risk_score >= 0.70` or `is_fraud = True`) to all connected fraud analysts.
- Handshake token authentication drops unauthenticated listeners immediately.

### 5. Comprehensive Risk Analyst Workflow
- Interactive transaction history with multi-criteria filtering (`status`, `risk_level`, `date_range`, `search`).
- Single-click review actions (`Approved`, `Rejected`, `Flagged`, `Under Review`) with auditor notes.
- Bulk review endpoint allowing analysts to clear queues in batches.
- Sanitized CSV export with formula injection protection (stripping leading `=`, `+`, `-`, `@` characters).

### 6. Enterprise-Grade Security & Governance
- **Role-Based Access Control (RBAC)**: Enforces access tiers across `admin`, `analyst`, `fraud_analyst`, `staff`, and `customer`.
- **Session Protection**: HttpOnly cookie-based JWT tokens combined with Double-Submit CSRF header verification.
- **Structured JSON Logging**: Stdout formatted JSON logs with correlation tracking (`X-Request-ID`).
- **Fail-Safe Audit Logging**: Async database audit entries recording authentication, predictions, review modifications, and WebSocket connections with recursive PII/credential redaction.

---

## 📸 UI & Explainability Showcase

### 1. Analyst Operations Dashboard
Real-time KPI metrics, 24-hour alert feed, and dynamic risk distribution charts.
![Dashboard Screenshot](screenshots/dashboard.png)

### 2. Single Transaction Prediction & Local SHAP Waterfall
Interactive form input evaluating transaction features with instant Shapley contribution attributions.
![SHAP Prediction Result](screenshots/shap_prediction.png)

### 3. Transaction Monitoring & Auditor Review Console
Live paginated tabular ledger supporting sorting, filtering, bulk status updates, and sanitized CSV exports.
![Transaction Monitoring](screenshots/transactions_monitor.png)

### 4. Analytics & Risk Intelligence
30-day temporal trend charts, fraud volume breakdown, and risk distribution analysis powered by Recharts.
![Analytics Overview](screenshots/analytics.png)

### 5. Role-Protected Login Portal
Secure JWT authentication portal with rate-limiting protection against brute-force attacks.
![Authentication Portal](screenshots/login.png)

---

## 📊 Machine Learning & XAI Pipeline

### Dataset
The model is trained on the benchmark **Kaggle Credit Card Fraud Detection** dataset:
- **Total Transactions:** 284,807
- **Fraudulent Instances:** 492 (0.172% extreme class imbalance)
- **Features:** 30 numerical inputs (28 PCA components `V1-V28`, transaction `Time`, and `Amount`).

### Model Performance Benchmarks
Trained with class weight balancing (`scale_pos_weight`), early stopping, and hyperparameter tuning:

| Metric | Score / Benchmark | Description |
| :--- | :--- | :--- |
| **ROC-AUC** | **0.982** | Exceptional discriminative power separating fraud from legitimate |
| **PR-AUC** | **0.864** | Primary metric for highly imbalanced fraud classification |
| **Recall (Fraud)** | **88.2%** | High sensitivity capturing fraudulent transactions |
| **Precision (Fraud)** | **84.6%** | Low false positive rate minimizing analyst review fatigue |
| **Inference Latency** | **<15ms** | Real-time single transaction scoring |
| **Batch Throughput** | **~5,388 - 6,200 recs/sec** | Vectorized chunk processing with PostgreSQL COPY |

<p align="center">
  <img src="ml_training/plots/roc_curve.png" width="48%" alt="ROC Curve" />
  <img src="ml_training/plots/confusion_matrix.png" width="48%" alt="Confusion Matrix" />
</p>

### Global Feature Importance & SHAP Attribution
TreeSHAP calculates exact additive feature contributions:
$$\phi_i(x) = \sum_{S \subseteq F \setminus \{i\}} \frac{|S|!(|F| - |S| - 1)!}{|F|!} \left[ f(S \cup \{i\}) - f(S) \right]$$

<p align="center">
  <img src="ml_training/plots/shap_summary.png" width="70%" alt="SHAP Summary Plot" />
</p>

---

## 💻 Technology Stack Matrix

| Layer | Component | Version | Description |
| :--- | :--- | :--- | :--- |
| **Frontend** | [Next.js](https://nextjs.org/) | `14.1.0` | React framework with App Router, SSR, and API route handlers |
| **UI Library** | [React](https://react.dev/) | `18.2.0` | Declarative component UI library |
| **Language** | [TypeScript](https://www.typescriptlang.org/) | `5.3.3` | Type-safe interfaces across state, props, and API schemas |
| **Styling** | [Tailwind CSS](https://tailwindcss.com/) | `3.4.1` | Utility-first responsive design system |
| **Visuals** | [Recharts](https://recharts.org/) | `2.12.0` | Composable SVG chart visualizer |
| **State** | [Zustand](https://zustand-demo.pmnd.rs/) | `4.5.0` | Lightweight centralized client state management |
| **Backend** | [FastAPI](https://fastapi.tiangolo.com/) | `0.109.0` | Modern, high-performance async ASGI web framework |
| **ORM** | [SQLAlchemy](https://www.sqlalchemy.org/) | `2.0.25` | Async relational mapping via `asyncpg` |
| **Validation** | [Pydantic](https://docs.pydantic.dev/) | `2.6.0` | Data validation and schema enforcement |
| **Database** | [PostgreSQL](https://www.postgresql.org/) | `15-alpine` | ACID-compliant relational storage with custom indexes |
| **Migrations** | [Alembic](https://alembic.sqlalchemy.org/) | `1.13.1` | Relational schema versioning and execution |
| **Queue** | [Celery](https://docs.celeryq.dev/) | `5.3.6` | Distributed task queue for asynchronous batch processing |
| **Broker/Cache**| [Redis](https://redis.io/) | `7-alpine` | High-speed in-memory message broker & cache |
| **ML Engine** | [XGBoost](https://xgboost.readthedocs.io/) | `2.0.3` | Gradient boosted tree classifier |
| **XAI Engine** | [SHAP](https://shap.readthedocs.io/) | `0.44.1` | Game-theoretic feature attribution library |
| **DevOps** | [Docker Compose](https://docs.docker.com/compose/) | `v2` | Multi-container orchestration with non-root security |

---

## 📡 Comprehensive REST & WebSocket API

### 1. Authentication & Session Management
| Method | Endpoint | Description | Role Required |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/auth/register` | Register new system account | Anonymous |
| `POST` | `/api/auth/login` | Authenticate user, issue HttpOnly JWT & CSRF cookies | Anonymous |
| `POST` | `/api/auth/logout` | Clear session cookies and invalidate token | Authenticated |
| `GET`  | `/api/auth/me` | Retrieve current authenticated user profile | Authenticated |

### 2. Fraud Prediction & Batch Pipeline
| Method | Endpoint | Description | Role Required |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/predict/transaction` | Real-time prediction with localized SHAP attributions | `analyst`, `admin` |
| `POST` | `/api/predict/batch` | Async JSON batch prediction (Celery queued) | `analyst`, `admin` |
| `POST` | `/api/predict/batch-file` | Streamed multipart CSV upload for vectorized chunking | `analyst`, `admin` |
| `POST` | `/api/predict/batch/durable` | Ingest durable PostgreSQL-backed batch job | `analyst`, `admin` |
| `GET`  | `/api/predict/batch/{job_id}` | Query execution state, chunk counts, and live progress | `analyst`, `admin` |

### 3. Transaction Monitoring & Review Workflow
| Method | Endpoint | Description | Role Required |
| :--- | :--- | :--- | :--- |
| `GET`  | `/api/transactions` | Query paginated transactions with multi-field filters | `analyst`, `admin` |
| `GET`  | `/api/transactions/{id}` | Retrieve specific transaction details and SHAP vector | `analyst`, `admin` |
| `PUT`  | `/api/transactions/{id}/review` | Update review status (`approved`, `rejected`, `flagged`) | `analyst`, `admin` |
| `PUT`  | `/api/transactions/bulk-review` | Bulk review multiple transactions with auditor notes | `analyst`, `admin` |
| `POST` | `/api/transactions/export` | Export filtered transaction ledger to sanitized CSV | `analyst`, `admin` |

### 4. Analytics & Governance
| Method | Endpoint | Description | Role Required |
| :--- | :--- | :--- | :--- |
| `GET`  | `/api/analytics/stats` | High-level KPI metrics (total volume, fraud rate, risk mix)| `analyst`, `admin` |
| `GET`  | `/api/analytics/trends` | 30-day grouped transaction volume and fraud frequency | `analyst`, `admin` |
| `GET`  | `/api/audit-logs` | Paginated immutable audit trail with actor details | `admin` |
| `GET`  | `/health` | Live PostgreSQL and Redis connection health check | Anonymous |

### 5. WebSocket Live Feeds
| Protocol | Endpoint | Description | Role Required |
| :--- | :--- | :--- | :--- |
| `WSS` | `/api/ws/alerts` | Bidirectional real-time push alert stream for flagged fraud | `analyst`, `admin` |

---

## 🗄️ Database Architecture & Migrations

The PostgreSQL relational database is structured with targeted B-tree composite indexes to support rapid time-series filtering and high-frequency analytical grouping:

```sql
-- Core Transactions Schema
CREATE TABLE transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    amount NUMERIC(12, 2) NOT NULL,
    risk_score NUMERIC(5, 4) NOT NULL,
    risk_level VARCHAR(20) NOT NULL,
    is_fraud BOOLEAN NOT NULL DEFAULT FALSE,
    review_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    reviewer_notes TEXT,
    reviewed_by VARCHAR(100),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    shap_explanation JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Performance Indexes
CREATE INDEX ix_transactions_created_at ON transactions (created_at DESC);
CREATE INDEX ix_transactions_risk_level ON transactions (risk_level);
CREATE INDEX ix_transactions_is_fraud ON transactions (is_fraud);
CREATE INDEX ix_transactions_review_status ON transactions (review_status);
```

### Alembic Migration Management
Production environments utilize Alembic migrations rather than runtime ORM table creation:
```bash
# Apply all pending schema migrations
docker compose exec backend alembic upgrade head

# Inspect current schema revision
docker compose exec backend alembic current

# View migration history tree
docker compose exec backend alembic history
```

---

## 🔐 Security Model & Role-Based Access Control

### 1. Multi-Tier RBAC Matrix
| Role | Dashboard | Predict API | Review Actions | Audit Logs | User Admin |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **`admin`** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **`fraud_analyst`** | ✅ | ✅ | ✅ | ❌ | ❌ |
| **`analyst`** | ✅ | ✅ | ✅ | ❌ | ❌ |
| **`staff`** | ✅ (Read) | ❌ | ❌ | ❌ | ❌ |
| **`customer`** | ❌ | ❌ | ❌ | ❌ | ❌ |

### 2. Defense-in-Depth Mechanisms
* **Cookie-Based JWT Tokens:** Employs `HttpOnly`, `SameSite=Lax`, and `Secure` cookie flags to prevent XSS session theft.
* **Double-Submit CSRF Defense:** Mutation endpoints require matching `csrf_token` cookie and `X-CSRF-Token` HTTP headers.
* **Dialect-Safe CSV Injection Defense:** Formula injection vectors (`=`, `+`, `-`, `@`) in transaction export files are automatically sanitized with leading single quotes.
* **Strict Parameter Sanitization:** UUID lookups and status transitions are validated through Pydantic models; invalid input returns `400 Bad Request` rather than unhandled `500` errors.

---

## 📋 Audit Logging & Observability

1. **Structured JSON Logs:** Emitted to stdout in standard JSON with fields: `timestamp`, `level`, `logger`, `correlation_id`, `message`, `module`.
2. **Request Tracing:** The `RequestIdMiddleware` assigns each inbound request an `X-Request-ID` header, propagating correlation identifiers through log records.
3. **Fail-Safe Audit Table:** The `audit_logs` table persists security-relevant actions (`login`, `batch_file_submitted`, `transaction_review_updated`, `websocket_connect_success`). Failures to record audit logs are logged to stderr and never block operational endpoints.
4. **Recursive PII Redaction:** Fields matching keys such as `password`, `token`, `secret`, `card`, `pan`, `cvv`, `payload`, `transactions` are recursively scrubbed to `[REDACTED]` prior to persistence or logging.

---

## 🚀 Quickstart & Setup Instructions

### Prerequisites
- [Docker](https://www.docker.com/) & [Docker Compose](https://docs.docker.com/compose/) (v2.20+)
- Python 3.11+ (for local bare-metal execution)
- Node.js 20+ (for local frontend execution)

---

### Option A: One-Command Docker Deployment (Recommended)

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Dharshan-05/Explainable-Al-for-Banking-Fraud-Detection-System.git
   cd Explainable-Al-for-Banking-Fraud-Detection-System
   ```

2. **Configure environment variables:**
   ```bash
   cp .env.example .env
   cp backend/.env.example backend/.env
   cp frontend/.env.example frontend/.env
   ```

3. **Launch the platform:**
   ```bash
   docker compose up -d --build
   ```

4. **Verify container health:**
   ```bash
   curl http://localhost:8000/health
   # Expected response: {"status":"healthy","database":"ok","redis":"ok"}
   ```

5. **Seed initial development users:**
   ```bash
   docker compose exec backend python seed_users.py
   ```

6. **Access applications:**
   - **Analyst Web Dashboard:** [http://localhost:3000](http://localhost:3000)
   - **FastAPI OpenAPI Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
   - **MLflow Tracking UI:** [http://localhost:5001](http://localhost:5001)

---

### Option B: Local Bare-Metal Development

#### 1. Backend & Celery Setup
```bash
cd backend
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
alembic upgrade head
python seed_users.py

# Launch FastAPI Server
uvicorn main:app --reload --port 8000

# In a separate terminal, launch Celery Worker
celery -A worker worker --loglevel=info --concurrency=4
```

#### 2. Frontend Setup
```bash
cd frontend
npm install
npm run dev
# Dashboard accessible at http://localhost:3000
```

---

### 🔑 Default Development Credentials

When seeded via `seed_users.py`, the following test accounts are initialized:

| Role | Username | Password | Permitted Actions |
| :--- | :--- | :--- | :--- |
| **Admin** | `admin` | `Admin1234` | System control, audit logs, user management, full access |
| **Analyst** | `analyst` | `Analyst1234` | Fraud predictions, batch uploads, transaction reviews, analytics |
| **Fraud Analyst** | `fraud_analyst` | `Fraud@1234` | Real-time monitoring, transaction reviews, CSV export |
| **Staff** | `staff` | `Staff@1234` | Read-only access to transaction ledger |
| **Customer** | `customer` | `Customer1234` | Restricted customer portal (blocked from analyst routes) |

---

## 🧪 Running Tests & Quality Assurance

The test suite covers unit logic, security constraints, role boundaries, and durable batch operations:

```bash
# 1. Run backend Pytest suite with strict configuration
cd backend
pytest -c pytest.ini -v

# 2. Run test suite with line-by-line coverage
pytest -c pytest.ini --cov=. --cov-report=term-missing

# 3. Run frontend unit and integration tests (Vitest)
cd ../frontend
npm test

# 4. Execute Ephemeral Integration Test Script (Requires Docker)
cd ..
powershell -ExecutionPolicy Bypass -File scripts/run_durable_e2e.ps1
```

---

## 🏆 Enterprise Readiness & Audit

In an independent comprehensive technical audit, FraudGuard XAI achieved an overall **95/100 Enterprise Readiness Score**:

```
[==================================================] 95 / 100
Production-Style Prototype & Architecture Foundation
```

### Key Engineering Transformations
- **Fixed Preprocessing & Explainability:** Aligned standard scalers, resolved pickle serialization errors with Joblib, and eliminated mock explainers in favor of mathematical TreeSHAP.
- **Durable Batch Job Resiliency:** Replaced in-memory tasks with generation-fenced database state tracking and automated crash recovery.
- **Security Hardening:** Enforced HttpOnly JWT sessions, Double-Submit CSRF tokens, strict 5-tier RBAC, and PII log redaction.
- **N+1 Database Optimization:** Refactored loop-based time series queries into optimized single-pass SQL aggregations with indexed B-trees.

---

## 📚 Full Documentation & Reports

Detailed technical blueprints, benchmarks, and architectural analyses are maintained in the repository:

- 📄 **[Master Project Report & Architecture (master-full-project-report.md)](reports/master-full-project-report.md)** — Complete 380+ line technical architecture, system blueprints, and code audits.
- 📋 **[Full Technical Project Report (full-project-report.md)](reports/full-project-report.md)** — Comprehensive deep dive on algorithms, training pipelines, and failure modes.
- 🔍 **[Final Enterprise Audit Report (final-enterprise-audit-report.md)](reports/final-enterprise-audit-report.md)** — Verification results, test coverage matrices, and before-vs-after comparisons.
- ⏱️ **[Batch Performance Benchmarks (batch-performance-benchmark.md)](reports/batch-performance-benchmark.md)** — Throughput metrics, chunk profiling, and PostgreSQL COPY evaluation.
- 🎯 **[Interview Defense & Technical Guide (resume-interview-guide.md)](reports/resume-interview-guide.md)** — High-frequency architecture questions, design trade-offs, and resume talking points.

---

## 📄 License & Authors

Distributed under the **MIT License**. See [LICENSE](LICENSE) for details.

Developed & Maintained by **Dharshan S V**  
- **GitHub:** [@Dharshan-05](https://github.com/Dharshan-05)  
- **Repository:** [Explainable-Al-for-Banking-Fraud-Detection-System](https://github.com/Dharshan-05/Explainable-Al-for-Banking-Fraud-Detection-System)
