
# 🛡️ ProofGate AI

### An Evidence-First Verification System for AI-Generated Code Changes

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-Backend-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/React-Frontend-61DAFB?style=for-the-badge&logo=react&logoColor=black" />
  <img src="https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white" />
  <img src="https://img.shields.io/badge/Testing-pytest%20%7C%20Vitest-0A9EDC?style=for-the-badge" />
  <img src="https://img.shields.io/badge/License-MIT-555555?style=for-the-badge" />
</p>

<p align="center">
  <b>AI can generate code. ProofGate asks for the evidence.</b>
</p>

---

## 🚀 About the Project

AI coding assistants can generate code and suggest fixes in seconds. But how do we know whether a generated change actually addresses the reported issue?

**ProofGate AI** is an evidence-first system designed to inspect AI-generated Python code changes and present transparent, structured verification evidence.

Instead of trusting a generated answer, ProofGate analyzes source code, examines diff structure, records completed and skipped checks, and applies a deterministic policy to produce a conservative decision.

The project combines a **Python + FastAPI backend** with a **React + TypeScript dashboard** to make code inspection and verification results easier to understand.

> **Core principle:** A code change should not be considered verified just because it looks correct. Decisions must be supported by evidence.

## ✨ Key Features

- 🔍 **Static Python Analysis** — Inspects Python source code using AST-based analysis without importing or executing submitted code.
- 🧾 **Evidence Collection** — Records checks performed, checks skipped, findings, reasons, and verification metadata.
- ⚖️ **Deterministic Policy Engine** — Evaluates available evidence using explicit, versioned decision rules.
- 🔀 **Diff Inspection** — Examines unified diffs and reports available change information.
- 🐙 **GitHub Pull Request Inspection** — Retrieves bounded public repository and pull-request information through the GitHub API in read-only mode.
- 🧠 **Behavioral Pattern Checks** — Detects a narrow set of explicit addition/subtraction operator mismatches in supported Python functions.
- 📊 **Interactive Dashboard** — Displays decisions, evidence, findings, checks, and coverage information.
- 🧪 **Automated Tests** — Includes backend pytest tests, frontend Vitest tests, and an offline policy benchmark.
- 🔐 **Security-Focused Design** — Uses bounded inputs, repository-root restrictions, path validation, and read-only analysis.

## 🛠️ Built With

<p>
  <img src="https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/Pydantic-E92063?style=flat-square&logo=pydantic&logoColor=white" />
  <img src="https://img.shields.io/badge/React-20232A?style=flat-square&logo=react&logoColor=61DAFB" />
  <img src="https://img.shields.io/badge/TypeScript-3178C6?style=flat-square&logo=typescript&logoColor=white" />
  <img src="https://img.shields.io/badge/Vite-646CFF?style=flat-square&logo=vite&logoColor=white" />
  <img src="https://img.shields.io/badge/pytest-0A9EDC?style=flat-square&logo=pytest&logoColor=white" />
  <img src="https://img.shields.io/badge/Vitest-6E9F18?style=flat-square&logo=vitest&logoColor=white" />
  <img src="https://img.shields.io/badge/GitHub_API-181717?style=flat-square&logo=github&logoColor=white" />
</p>

| Layer | Technologies |
|---|---|
| Backend | Python 3.12+, FastAPI, Pydantic |
| Code Analysis | Python AST, unified-diff inspection |
| Frontend | React, TypeScript, Vite |
| Backend Testing | pytest, HTTPX |
| Frontend Testing | Vitest |
| Code Quality | Ruff |
| Integration | GitHub REST API |

## 🔄 How It Works

```text
      Bug Description + Python Source / Repository File
                           |
                           v
                  +------------------+
                  |   Input Checks   |
                  +------------------+
                           |
                           v
                  +------------------+
                  |  Static Analysis |
                  |   Python AST     |
                  +------------------+
                           |
                           v
                  +------------------+
                  | Evidence Builder |
                  +------------------+
                           |
                           v
                  +------------------+
                  |  Policy Engine   |
                  | Deterministic    |
                  +------------------+
                           |
                           v
                  +------------------+
                  | Verification     |
                  | Decision +       |
                  | Evidence         |
                  +------------------+
                           |
                           v
                  +------------------+
                  | React Dashboard  |
                  +------------------+
```

### Verification Workflow

1. **Provide the change** — Enter a bug description and paste Python source code or provide a repository-relative file path.
2. **Analyze the source** — ProofGate performs bounded, read-only source inspection and supported AST checks.
3. **Inspect the diff** — If supplied, the unified diff is examined for change structure.
4. **Collect evidence** — The system records findings, completed checks, skipped checks, and reasons.
5. **Apply the policy** — The deterministic policy engine evaluates the available evidence.
6. **Review the result** — The dashboard presents the decision and supporting evidence.

## 🏗️ Project Architecture

```text
proofgate-ai/
│
├── .github/
│   └── workflows/
│       └── tests.yml
│
├── backend/
│   ├── src/
│   │   └── proofgate/
│   │       ├── api/
│   │       │   └── main.py
│   │       ├── analyzer.py
│   │       ├── benchmark.py
│   │       ├── evidence.py
│   │       ├── github.py
│   │       ├── languages.py
│   │       ├── models.py
│   │       ├── policy.py
│   │       └── runner.py
│   ├── tests/
│   └── pyproject.toml
│
├── benchmark/
│   ├── fixtures/
│   └── README.md
│
├── docs/
│   ├── architecture.md
│   ├── benchmark-methodology.md
│   ├── demo-readiness-checklist.md
│   ├── testing-audit-report.md
│   ├── threat-model.md
│   └── verification-policy.md
│
├── frontend/
│   ├── src/
│   ├── package.json
│   └── vite.config.ts
│
├── sandbox/
│   ├── Dockerfile
│   └── worker.py
│
├── .env.example
├── .gitignore
├── LICENSE
└── README.md
```

### Main Backend Modules

| File | Responsibility |
|---|---|
| `analyzer.py` | Validates repository paths and performs read-only Python source and diff analysis. |
| `runner.py` | Coordinates analysis, evidence collection, skipped checks, and policy evaluation. |
| `evidence.py` | Creates structured evidence records. |
| `policy.py` | Applies deterministic verification rules (policy version `1.0.1`). |
| `models.py` | Defines typed request and response models. |
| `github.py` | Retrieves bounded public GitHub repository and pull-request information. |
| `benchmark.py` | Runs the offline policy benchmark. |
| `api/main.py` | Exposes the FastAPI endpoints. |

## ⚙️ Installation & Setup

### Prerequisites

- Python 3.12+
- Node.js 20.19+ or 22.12+
- npm
- Git

### 1. Clone the Repository

```bash
git clone https://github.com/umbaupesrehaan1-art/proofgate-ai.git
cd proofgate-ai
```

### 2. Set Up the Backend

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

### 3. Configure the Repository Root

```powershell
$env:PROOFGATE_REPOSITORY_ROOT = (Resolve-Path ..).Path
```

### 4. Start the Backend

Run from the `backend` directory:

```powershell
.\.venv\Scripts\python.exe -m uvicorn proofgate.api.main:app --host 127.0.0.1 --port 8000
```

Backend API:

- Health: `http://127.0.0.1:8000/health`
- API documentation: `http://127.0.0.1:8000/docs`

### 5. Set Up the Frontend

Open a new terminal from the project root:

```bash
cd frontend
npm ci
npm run dev
```

Open the local URL printed by Vite, normally:

```text
http://127.0.0.1:5173
```

## 🔌 API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Checks backend health. |
| `GET` | `/docs` | Opens interactive API documentation. |
| `POST` | `/api/v1/analyze` | Analyzes a permitted repository path. |
| `POST` | `/api/v1/verify` | Collects evidence and evaluates a code change. |
| `POST` | `/api/v1/github/inspect` | Inspects public GitHub repository or pull-request content. |

For request schemas and response details, start the backend and visit `http://127.0.0.1:8000/docs`.

## 🧪 Running Tests

### Backend Tests

From the `backend` directory:

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

### Backend Quality Checks

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m ruff format --check src tests
```

### Frontend Tests

From the `frontend` directory:

```bash
npm test
npm run lint
npx tsc --noEmit
npm run build
```

### Offline Policy Benchmark

From the `backend` directory:

```powershell
.\.venv\Scripts\python.exe -m proofgate.benchmark
```

## 🔐 Security & Important Limitations

ProofGate treats submitted source code, repository files, diffs, and GitHub content as untrusted input.

Current safeguards include:

- Submitted Python source code is **not imported or executed**.
- Submitted tests and repository commands are **not run**.
- Repository analysis is restricted to a server-configured root.
- File access and input sizes are bounded.
- Path validation and symlink/reparse-point protections are applied.
- GitHub inspection uses bounded, read-only requests to the GitHub API.

**Current limitations:**

- Runtime bug reproduction is not implemented.
- Regression tests are not executed by the verification workflow.
- The `sandbox/` directory does not mean an active, production-ready sandbox is running.
- GitHub inspection is limited to public repositories.
- The API currently has no authentication or rate limiting. Keep it bound to `127.0.0.1` for local development.

Because runtime evidence is not currently available, analysis-only verification should conservatively return **`INSUFFICIENT_EVIDENCE`** when runtime proof is required.

Static analysis can identify useful signals, but it cannot prove that a change works at runtime.

Read the [Threat Model](docs/threat-model.md) and [Verification Policy](docs/verification-policy.md) for details.

## 📚 Documentation

- [System Architecture](docs/architecture.md)
- [Verification Policy](docs/verification-policy.md)
- [Security Threat Model](docs/threat-model.md)
- [Benchmark Methodology](docs/benchmark-methodology.md)
- [Testing Audit Report](docs/testing-audit-report.md)
- [Demo Readiness Checklist](docs/demo-readiness-checklist.md)

## 🚧 Future Scope

- Secure, independently reviewed isolated execution architecture.
- Runtime bug reproduction and regression-test evidence.
- Stronger verification evidence and policy capabilities.
- Authentication and authorization for team deployments.
- Persistent verification history and audit reports.
- Broader language and code-analysis support.

*These are planned directions, not currently implemented features.*

## 🤝 Contributing

Contributions and suggestions are welcome.

1. Fork the repository.
2. Create a feature branch.
3. Make your changes and add relevant tests.
4. Run the applicable backend and frontend checks.
5. Submit a pull request with a clear explanation of your changes.

Please do not commit API keys, passwords, private source code, or other sensitive information.

## 📄 License

This project is licensed under the terms of the [MIT License](LICENSE).

---

<p align="center">
  <b>🛡️ ProofGate AI — Evidence before confidence.</b>
  <br />
  <i>Making AI-generated code changes easier to inspect, question, and evaluate.</i>
</p>
