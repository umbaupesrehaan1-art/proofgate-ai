<div align="center">ProofGate AI
Evidence-First Verification for AI-Generated Code
Inspect the change. Examine the evidence. Make a conservative decision.






Overview · Features · Architecture · Getting Started · API · Security
</div>🧠 Overview
AI coding tools can generate code quickly, but a plausible-looking patch is not proof that a reported bug has been fixed.

ProofGate AI is an evidence-first inspection system designed to assess AI-generated Python code changes. It combines bounded static analysis, structured evidence collection, deterministic policy evaluation, and a React dashboard to show what was actually checked—and what remains unknown.

The current implementation is deliberately analysis-only:
- It reads and analyzes source code as data.
- It checks Python syntax and selected structural patterns.
- It inspects unified-diff structure.
- It records checks, skipped checks, findings, and reasons.
- It does not execute submitted source code or tests.
[!IMPORTANT]
A successful syntax check or a matching static pattern does not prove that a change works at runtime. Since reproduction and regression-test execution are not implemented, the current system conservatively returns INSUFFICIENT_EVIDENCE when runtime evidence is required.

✨ Key Features
Feature	Description
Evidence-first decisions	Returns structured evidence, check statuses, reasons, and a policy version instead of relying on unsupported claims.
Python source analysis	Performs bounded, read-only Python source inspection and AST-based syntax analysis.
Behavioral pattern checks	Applies a narrow deterministic rule for explicit two-argument addition/subtraction requirements.
Diff inspection	Examines unified-diff structure and identifies changed-file information.
Repository analysis	Analyzes Python files beneath a server-configured repository root with path and resource safeguards.
GitHub inspection	Reads bounded public GitHub repository and pull-request content without writing to the repository.
Conservative policy engine	Applies deterministic decision rules and treats missing, skipped, or inconclusive evidence conservatively.
Interactive dashboard	Presents verification results, findings, evidence, coverage, and policy decisions in a React + TypeScript interface.
Automated tests and benchmark	Includes backend and frontend tests plus a deterministic offline policy benchmark.


🖥️ Application Workflow
1. Submit a change — provide a bug description and Python source or a repository-relative file path. A unified diff can also be supplied.
2. Inspect the input — ProofGate validates the request and performs bounded static analysis.
3. Collect evidence — completed checks, skipped checks, findings, and relevant metadata are recorded.
4. Evaluate the policy — the deterministic policy engine evaluates the available evidence.
5. Review the result — the dashboard displays the decision and explains what was—and was not—verified.
🏗️ Architecture
                  ┌─────────────────────────────┐
                  │       React Dashboard      │
                  │       React + TypeScript   │
                  └──────────────┬──────────────┘
                                 │ HTTP / JSON
                                 ▼
                  ┌─────────────────────────────┐
                  │         FastAPI API         │
                  │   Validation / Endpoints    │
                  └──────────────┬──────────────┘
                                 ▼
                  ┌─────────────────────────────┐
                  │       ProofGate Runner      │
                  │  Analysis & Evidence Flow   │
                  └────────┬───────────┬────────┘
                           │           │
                ┌──────────▼───┐  ┌────▼────────────┐
                │   Analyzer   │  │ Evidence Builder│
                │ Python AST   │  │ Structured Data │
                │ Diff Checks  │  │ & Check Results │
                └──────────┬───┘  └────┬────────────┘
                           │           │
                           └─────┬─────┘
                                 ▼
                  ┌─────────────────────────────┐
                  │       Policy Engine         │
                  │       Version 1.0.1         │
                  └──────────────┬──────────────┘
                                 ▼
                  ┌─────────────────────────────┐
                  │ Decision + Evidence Response│
                  └─────────────────────────────┘
Backend modules
Module	Responsibility
analyzer.py	Validates repository paths and performs bounded Python source and AST analysis.
runner.py	Orchestrates analysis, evidence collection, skipped checks, and policy evaluation.
evidence.py	Builds structured evidence records with bounded details and timing metadata.
policy.py	Applies deterministic verification rules (policy version 1.0.1).
models.py	Defines typed request and response models.
languages.py	Provides language-related analysis support.
github.py	Performs bounded, read-only inspection of public GitHub content.
benchmark.py	Runs the deterministic offline policy benchmark.
api/main.py	Exposes the FastAPI application and API endpoints.


Repository structure
proofgate-ai/
│
├── .github/
│   └── workflows/
│       └── tests.yml
│
├── backend/
│   ├── src/proofgate/
│   │   ├── api/
│   │   ├── analyzer.py
│   │   ├── benchmark.py
│   │   ├── evidence.py
│   │   ├── github.py
│   │   ├── languages.py
│   │   ├── models.py
│   │   ├── policy.py
│   │   └── runner.py
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
⚙️ Technology Stack
Backend
- Python 3.12 — core application and analysis logic
- FastAPI — REST API
- Pydantic — request and response validation
- Python AST — static source inspection
- pytest — automated backend tests
Frontend
- React — user interface
- TypeScript — typed frontend code
- Vite — development server and build tooling
- Vitest — frontend tests
Engineering practices
- Deterministic policy evaluation
- Bounded input and file processing
- Structured evidence records
- Explicit reporting of skipped checks
- Path validation and symlink/reparse-point safeguards
- Read-only GitHub inspection
🚀 Getting Started
Prerequisites
Install the following:
- Windows 10/11 (commands below use Windows PowerShell)
- Python 3.12
- Node.js compatible with the frontend toolchain (see docs/demo-readiness-checklist.md)
- npm
- Git
1. Clone the repository
git clone https://github.com/umbaupesrehaan1-art/proofgate-ai.git
cd proofgate-ai
2. Set up the backend
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
3. Configure the permitted repository root
The API only analyzes repository paths beneath a server-configured root. Set the root in the same PowerShell window used to start the backend.

For example, to allow analysis of the cloned project root:
$env:PROOFGATE_REPOSITORY_ROOT = (Resolve-Path ..).Path
4. Start the backend
Run from the backend directory:
.\.venv\Scripts\python.exe -m uvicorn proofgate.api.main:app --host 127.0.0.1 --port 8000
The API is available at:
- Health check: http://127.0.0.1:8000/health
- Interactive API docs: http://127.0.0.1:8000/docs
Keep this local development server bound to 127.0.0.1. It has no authentication.
5. Set up the frontend
Open a second terminal from the project root:
cd frontend
npm ci
npm run dev
Open the local URL printed by Vite, normally:
http://127.0.0.1:5173
The Vite development server proxies /api requests to the backend at http://127.0.0.1:8000.
🔌 API Reference
Method	Endpoint	Purpose
GET	/health	Health check
GET	/docs	Interactive API documentation
GET	/api/v1	API endpoint index
POST	/api/v1/analyze	Read-only analysis of a permitted repository path
POST	/api/v1/verify	Evidence collection and policy evaluation
POST	/api/v1/github/inspect	Bounded, read-only inspection of public GitHub content


Verification request
POST /api/v1/verify accepts a bug description and exactly one source input: pasted source_code or a repository_path. An optional unified_diff may also be provided. The current supported execution mode is analysis_only.

A verification response includes fields such as:
- verification_id
- decision
- summary
- evidence
- behavioral_findings
- checks
- checks_performed
- checks_skipped
- reasons
- duration_ms
- policy_version
See the interactive API documentation at /docs for the exact schemas.
🧪 Testing & Benchmarking
Backend tests
From the repository root:
cd backend
.\.venv\Scripts\python.exe -m pytest -v
Optional quality checks, when installed in the development environment:
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m ruff format --check src tests
Frontend tests
Open another terminal:
cd frontend
npm test
npm run lint
npx tsc --noEmit
npm run build
Offline policy benchmark
From the repository root:
cd backend
.\.venv\Scripts\python.exe -m proofgate.benchmark
Only publish test or benchmark results that have actually been run. The methodology and audit notes are documented in docs/.
🛡️ Security & Trust Model
ProofGate treats submitted source, diffs, repository files, and GitHub content as untrusted input.

Current safeguards include:
- No importing or executing submitted Python source.
- No execution of submitted tests, project hooks, or repository commands.
- Bounded request bodies, source files, repository traversal, and GitHub retrieval.
- Repository analysis restricted to a server-configured root.
- Path validation and symlink/reparse-point protections for file-content access.
- Structured errors that avoid returning host paths and exception traces.
- GitHub inspection restricted to the official API host, using read-only requests.
Important deployment warning
The API currently has no authentication or rate limiting. It is intended for local development and must not be exposed to an untrusted network without a security review and appropriate authentication, authorization, rate limiting, and deployment hardening.

Read the full [Threat Model](docs/threat-model.md) before deploying or integrating ProofGate into another system.
⚖️ Current Limitations
ProofGate is an active engineering project. The following capabilities are not implemented in the current version:
- Runtime reproduction of bugs
- Regression-test execution
- An active isolated execution worker
- GitHub authentication or private repository access
- Repository write operations, pull-request comments, approvals, or merges
- Persistent storage of verification history
The sandbox/ directory does not mean that a production-ready sandbox is active. The current API does not launch it. Requesting an isolated execution mode does not establish that isolation exists.
Decision meanings
Decision	Meaning
VERIFIED	All mandatory evidence requirements are satisfied. The current analysis-only workflow cannot establish this result.
NOT_REPRODUCED	A valid pre-patch reproduction attempt did not reproduce the issue under recorded conditions. The current workflow does not run that attempt.
INSUFFICIENT_EVIDENCE	Required evidence is missing, skipped, inconclusive, or otherwise insufficient. This is the expected conservative result for current analysis-only verification.


🗺️ Roadmap
Potential future work, subject to design and security review:
- A separately reviewed execution-worker architecture
- Trusted launcher observations and validated worker reports
- Reproduction and regression evidence under a versioned policy
- Authentication and authorization for team deployments
- Persistent verification history and audit views
- Expanded language and behavioral-analysis support
These are future directions, not claims about current functionality.
📚 Documentation
- [Architecture](docs/architecture.md)
- [Verification Policy](docs/verification-policy.md)
- [Threat Model](docs/threat-model.md)
- [Benchmark Methodology](docs/benchmark-methodology.md)
- [Testing Audit Report](docs/testing-audit-report.md)
- [Local Demo Readiness Checklist](docs/demo-readiness-checklist.md)
🤝 Contributing
Contributions, issue reports, and thoughtful feedback are welcome.
1. Fork the repository.
2. Create a feature branch.
3. Keep changes focused and add or update tests.
4. Run the relevant backend and frontend checks.
5. Open a pull request describing the change, test evidence, and any security implications.
Please do not submit secrets, private source code, or data you are not authorized to share.
📄 License
This project is distributed under the license in the LICENSE file.
<div align="center">ProofGate AI — Evidence before confidence.

Built to make AI-generated code changes easier to inspect, question, and evaluate.

Back to top
</div>
