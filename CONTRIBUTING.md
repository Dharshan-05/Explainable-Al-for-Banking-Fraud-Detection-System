# Contributing to Explainable AI Fraud Detection

Thank you for contributing to this project! To maintain MNC-level code quality, security, and stability, please review the following development guidelines before submitting pull requests.

---

## 1. Branch Workflow
We follow a standard Git branch workflow:
1. **Fork/Branch:** Create a descriptive feature branch from `main` (e.g., `feature/optimize-celery-pipeline` or `bugfix/ws-auth-handshake`).
2. **Commit Often:** Write clear, concise commit messages outlining the *what* and *why* of the change.
3. **Open PR:** Submit a Pull Request targeting the `main` branch. Provide a detailed summary of the changes and validation results in your description.

---

## 2. Pre-PR Checklist
Before opening a Pull Request, you **must** execute and pass all backend, frontend, and Docker validation checks locally.

### Backend Verification
Verify that your changes compile successfully and pass all unit tests with at least 80% coverage:
```bash
cd backend
# 1. Compile check python files
py -m compileall .

# 2. Run test suite
pytest

# 3. Verify coverage meets target (>80%)
pytest --cov=. --cov-report=term-missing
```

### Frontend Verification
Verify that the Next.js static site builder and type checks succeed:
```bash
cd frontend
# 1. Run eslint checks
npm run lint

# 2. Compile static pages
npm run build
```

### Docker Verification
Verify that your configurations merge and build cleanly:
```bash
# 1. Validate docker compose config syntax
docker compose config

# 2. Validate docker container compilation
docker compose build
```

---

## 3. Coding Standards
* **Python (PEP 8):** Keep functions small, document classes/methods, and preserve docstrings.
* **TypeScript:** Avoid using the `any` type. Define explicit interfaces or types for all API contracts and component props.
* **Component Design:** Keep UI components focused and reusable. Shift data aggregations and business logic to backend routes or frontend state stores (Zustand).

---

## 4. Security Guidelines

> [!CAUTION]
> **Never commit `.env` or credentials to version control!**
> The `.env` file is excluded from Git by [.gitignore](file:///.gitignore). All credentials, JWT keys, and passwords must remain local.

* **Secret Handling:** If a new credential or configuration parameter is added, document it with a safe placeholder value in `.env.example`, `backend/.env.example`, and `frontend/.env.example`.
* **Vulnerability Disclosure:** If you identify a security defect (e.g., an auth bypass or SQL injection vector), do not create a public issue. Email the project maintainer privately to resolve the issue securely.
