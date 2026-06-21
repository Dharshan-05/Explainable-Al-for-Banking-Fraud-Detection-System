# Resume and Interview Guide
**Project:** Real-Time Explainable AI Banking Fraud Detection System  
**Target Roles:** Full Stack Engineer, Backend Engineer, ML/DevOps Engineer, Software Engineer (Intern/Entry-Level)

---

## 1. Resume Optimization

### Project Title
**Real-Time Explainable AI Banking Fraud Detection System**

### Tech Stack Line
* **Languages & Frameworks:** Python, TypeScript, FastAPI, Next.js, SQL, HTML/CSS
* **Databases & Cache:** PostgreSQL, Redis, Celery (Task Queue), SQLAlchemy (Async)
* **ML & Explainability:** XGBoost, Scikit-learn, SHAP, Joblib
* **Tools & DevOps:** Docker, Docker Compose, GitHub Actions, Pytest, Git, ESLint

### Safe Resume Bullet Points
* Built a full-stack fraud monitoring platform using FastAPI, Next.js, PostgreSQL, Redis, Celery, and XGBoost for real-time and batch transaction risk prediction.
* Integrated SHAP-based explainability and StandardScaler preprocessing to provide transaction-level feature explanations for fraud decisions.
* Implemented JWT authentication, RBAC-protected analytics/transaction APIs, secured WebSocket alerts, Dockerized deployment, CI checks, and 80%+ backend test coverage.
* Optimized database latency by migrating daily analytics queries from nested N+1 loops into a single SQL aggregation query, reducing API response times.
* Streamlined the CSV batch processor to use Celery asynchronous tasks with bulk commits (commit-once-per-batch) and rollback failover recovery.

---

## 2. Interview Elevator Pitches

### The 60-Second Overview (Elevator Pitch)
> "I built an Explainable AI Banking Fraud Detection System that allows analysts to review real-time transaction risks with mathematical explanations. The backend is built on FastAPI and uses a trained XGBoost classifier, while the frontend dashboard is a Next.js TypeScript app. For transparency, which is critical in banking compliance, the API generates real-time feature-level explanations using SHAP values, explaining exactly why a transaction was flagged as high-risk. High-risk actions are pushed instantly to the analyst dashboard via WebSockets. To handle large transaction uploads, I built an async queue using Redis and Celery that processes batch CSV predictions asynchronously."

### The 2-Minute Deep Dive
> "My project is a full-stack transaction monitoring platform designed with security and scalability in mind. The core system architecture separates synchronous API requests from heavy asynchronous calculations. 
> 
> When a user uploads a transaction file, Next.js sends it as a single request to the FastAPI backend, which queues a background job in Celery via Redis. The Celery worker processes the rows in-memory and saves them in optimized database chunks with rollback error isolation, ensuring database write limits aren't bottlenecked. 
> 
> I designed the database schema on PostgreSQL, placing strategic indexes on transaction timestamps and status fields to speed up analytics queries. I also refactored the daily trends analytics endpoint from N+1 query loops to a single SQL grouping statement. 
> 
> For security, the system uses JWT authentication with Role-Based Access Control, ensuring that customer roles cannot access transaction histories or update review statuses. The entire application is containerized using multi-stage Docker builds running under non-root users, and the code compiles with 81% backend test coverage verified through a GitHub Actions CI pipeline."

---

## 3. Architecture Breakdowns

### Machine Learning & XAI
* **Preprocessing:** Scaling must match model training. I aligned column sequences and StandardScaler settings. Added safety constraints rejecting `NaN` or `Infinity` inputs.
* **Explainability:** SHAP values calculate localized feature impacts. The application is resilient: if the SHAP explainer fails, the route logs the exception and returns a clean fallback description, ensuring system availability.

### Security
* **Authentication:** Uses secure JWT bearer tokens.
* **Role Guards (RBAC):** Centralized inside `deps.py` using FastAPI dependency injection. Only `analyst` and `admin` roles can query transactions or view dashboards.
* **WebSocket Handshake:** WebSocket tokens are authenticated during connection setup. Stale or invalid tokens are dropped immediately to prevent information leaks.

### Backend & Database
* **SQLAlchemy Async:** Uses asynchronous engines (`create_async_engine`) and async sessions to prevent blocking threads during database queries.
* **N+1 Optimization:** Shunted date-filtering analytics to a single SQL query using database-specific formatting (`strftime` for SQLite / `to_char` for PostgreSQL).

### Frontend
* **Decoupled Pages:** State is managed via Zustand. Axios interceptors automatically attach JWT headers and handle 401 logouts.
* **Async Indicators:** UI displays skeleton loading states, empty folders, and manual retry triggers to ensure a premium user experience.

---

## 4. Common Technical Interview Q&A

#### Q: Why did you use Celery for CSV batch uploads?
**A:** "Parsing a large CSV file and running ML models on each row is compute-intensive and network-slow. If we did this synchronously inside a REST route, the request would time out, and the event loop would freeze. By using Celery with a Redis broker, the route immediately returns a task ID. The browser then polls the task status asynchronously, keeping the UI responsive while the worker processes the file in the background."

#### Q: How did you optimize the database inserts inside the Celery worker?
**A:** "Initially, the task committed each record to the database individually inside a loop. This caused a high transaction commit overhead. I refactored it to accumulate valid objects in-memory and write them in bulk using a single session commit. To make it resilient, I wrapped the commit in a try-except block: if the bulk write fails (due to a duplicate key or validation error), the database rolls back and writes them one-by-one, capturing specific failure reasons without crashing the entire batch."

#### Q: Why did you choose a multi-stage Docker build for the frontend?
**A:** "A standard Node.js image copies compiler tools and development packages into the final container, creating bloated image sizes. A multi-stage build separates the build environment from the runtime environment. I use one stage to install dependencies and compile the Next.js static files, and a final lightweight stage that copies only the runtime bundles. This reduced the container image size, sped up deployments, and minimized the security attack surface."

---

## 5. Ethical Guidelines: What NOT to Claim
When discussing this project with recruiters and engineers, keep it professional and honest:
* **Do NOT claim:**
  * "This is deployed live at a major bank."
  * "The system is fully PCI-DSS certified."
  * "It handles millions of real live bank payments."
  * "It is a production-grade MNC software system."
* **DO say:**
  * "It is a production-style, containerized portfolio application."
  * "It demonstrates MNC-level security and performance engineering principles."
  * "It mimics real-world banking compliance requirements by incorporating explainable AI (XAI)."
  * "It is designed as an educational/portfolio project to show full-stack and DevOps maturity."
