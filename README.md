# ProofGate AI

ProofGate AI is an evidence-first tool for inspecting AI-generated Python changes.
The current backend performs bounded, read-only source analysis, a narrow
deterministic behavioral-pattern check, and diff-structure inspection. **Submitted
source code and tests are never executed.** Syntax validity, a recognized
operator mismatch, and a well-formed diff are not proof that a fix works at
runtime.

## Architecture

- `backend/src/proofgate/analyzer.py` validates paths and inspects Python source
  without importing or executing it. It also applies one explicit AST rule for
  simple two-argument addition/subtraction requirements.
- `backend/src/proofgate/runner.py` collects the analysis and reports reproduction
  and regression checks as skipped.
- `backend/src/proofgate/policy.py` applies deterministic decision rules (policy
  `1.0.1`).
- `backend/src/proofgate/github.py` retrieves bounded public GitHub metadata and
  Python contents over the fixed GitHub API host, then invokes the existing
  syntax and diff analyzers. It has no write operations and no authentication.
- `frontend/` is a React + TypeScript single-page dashboard built with Vite. It
  sends schema-supported requests to the FastAPI API and renders the API's
  actual checks, static findings, coverage state, and policy decision.
- The Vite development server proxies `/api` to the backend. This avoids a broad
  development CORS policy; the backend does not enable unrestricted CORS.

## Prerequisites

- Windows 10/11.
- Python 3.12 and the existing backend virtual environment (or setup below).
- Node.js 20.19+ (or 22.12+) and npm.

## Backend setup

From a Windows CMD prompt at the repository root:

```cmd
cd /d backend
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

The backend uses the server-side `PROOFGATE_REPOSITORY_ROOT` environment variable
as its trusted root. It does not automatically load `.env`; `.env.example` shows
the local project path, but copy the value into the CMD process before starting
Uvicorn. Keep the backend bound to loopback because there is no authentication.

```cmd
cd /d C:\Users\DELL\Desktop\proofgate-ai\backend
set "PROOFGATE_REPOSITORY_ROOT=C:\Users\DELL\Desktop\proofgate-ai"
.venv\Scripts\python.exe -m uvicorn proofgate.api.main:app --host 127.0.0.1 --port 8000
```

If using the existing `cypher` Conda environment instead of the project `.venv`,
run the same app with that interpreter after setting the variable in the same
CMD window:

```cmd
cd /d C:\Users\DELL\Desktop\proofgate-ai\backend
set "PROOFGATE_REPOSITORY_ROOT=C:\Users\DELL\Desktop\proofgate-ai"
set "PYTHONPATH=C:\Users\DELL\Desktop\proofgate-ai\backend\src"
C:\Users\DELL\miniconda3\envs\cypher\python.exe -m uvicorn proofgate.api.main:app --host 127.0.0.1 --port 8000
```

If the value changes, stop Uvicorn with `Ctrl+C`, set the variable in the CMD
window that will run the backend, and restart Uvicorn there. Setting the value
in another CMD window or changing `.env.example` alone does not update a running
process. If no root is set, source-code verification still works and repository
analysis returns the backend's configured-root error.

## Frontend setup and run

In a separate CMD window at the repository root:

```cmd
cd /d frontend
npm ci
npm run dev
```

Open the local URL printed by Vite, normally `http://127.0.0.1:5173`. The
development proxy targets `http://127.0.0.1:8000`.

To use another backend, create a root `.env` from `.env.example` and set
`PROOFGATE_BACKEND_URL` to the backend origin. The browser-facing API base is
`VITE_PROOFGATE_API_URL` (defaults to `/api`); it must remain a public URL, not a
secret. In a production deployment, serve the frontend and configure a same-origin
reverse proxy for `/api`, or explicitly configure the public API base and the
backend's narrowly allowlisted CORS origins as appropriate. Do not put credentials
or secrets in any `VITE_` variable.

## Dashboard workflow

The **Verify a change** workspace accepts a bug description and either pasted
Python source or a repository-relative Python file path. A unified diff is
optional. It calls `POST /api/v1/verify` with the existing fields:
`bug_description`, exactly one of `source_code` or `repository_path`, optional
`unified_diff`, and `execution_mode: "analysis_only"`.

The **Analyze repository** workspace calls `POST /api/v1/analyze` with
`repository_path` and `max_files`. Repository paths are relative to the
server-configured root; use `.` to analyze that root.

The **Inspect GitHub** workspace calls `POST /api/v1/github/inspect` with a
public `https://github.com/owner/repository` URL, an optional pull-request
number, and a file limit from 1 to 20. No token or additional environment
variable is required. Without a pull-request number, the API lists Python files
on the repository's default branch. For a pull request, it retrieves the PR
metadata and changed-file patches, and reads supported Python blobs at the PR
head. Non-Python files are listed but not parsed. The dashboard lets you select
a changed file to inspect its available patch, added/deleted/context line numbers,
Python syntax diagnostics, and associated evidence details.

GitHub retrieval is read-only and limited to `api.github.com`; arbitrary URLs
are rejected and redirects are not followed. Each Python file is limited to
100 KB, retrieved source to 1 MB total, and each displayed patch to 20 KB.
API responses are bounded to 1 MB (blob responses to 200 KB); each upstream
request uses a 5-second timeout, with a 20-second retrieval budget checked
between API calls. Repository analysis is pinned to a commit, and pull-request
head/base revisions are rechecked after file retrieval. A truncated tree,
missing, oversized, malformed, or truncated diff, inaccessible file, structured
line-count mismatch, line-location cap, or file-count cap is reported as
incomplete coverage, never as a complete inspection. The GitHub pull-request
files API may omit a patch for a binary file or an unavailable/oversized diff,
but does not reliably
identify which case applies; ProofGate labels such patches as missing rather
than asserting that a file is binary. If a pull-request file record omits its
size, the bounded Git blob response's reported size is checked against the
decoded contents instead. GitHub unauthenticated rate limits apply;
private repositories are unsupported and may be indistinguishable from missing
repositories.

The dashboard displays the backend's returned decision, summary, checks,
performed/skipped checks, reasons, typed behavioral findings, evidence records,
and policy version. It never
infers verification from the submitted text or inserts evidence into requests.
“Load example” only fills the source editor; it does not execute code. Current
analysis-only requests should return `INSUFFICIENT_EVIDENCE` for verification
because reproduction and regression testing are not implemented.

The behavioral-pattern rule is intentionally narrow. It recognizes explicit
requirements such as “The `add(a, b)` function should add its two arguments” or
“The `subtract(a, b)` function should subtract its two arguments.” It checks only
a named top-level function with two required positional arguments and one direct
binary return using those arguments. It can report
`POTENTIAL_BEHAVIOR_MISMATCH` when the detected operator is the opposite
addition/subtraction operator. Ambiguous wording, unrecognized requirements,
different function names, and unsupported expressions are reported as
unsupported/inconclusive, not guessed. A matching operator means only that this
rule did not detect a mismatch. Findings are static evidence with an
`inconclusive` outcome; they do not change the policy decision or establish that
the function—or program—behaves correctly at runtime.

GitHub inspection shows static syntax findings, diff structure, retrieval
coverage, and the actual analysis-only policy decision. That decision remains
`INSUFFICIENT_EVIDENCE`; static analysis is not proof that a patch works at
runtime. Syntax diagnostic line numbers refer to the retrieved pull-request-head
source; diff line mappings refer to the returned patch text. Structured diff
line mappings are capped at 2,500 records per inspection; if that cap is hit,
the result marks coverage incomplete while retaining the bounded raw patch.
GitHub content, names, and diffs are untrusted input. The service does not check
out repositories, execute code, install dependencies, create commits, post
comments, approve, or merge pull requests.

## API and checks

- `GET /health`
- `GET /docs`
- `POST /api/v1/analyze`
- `POST /api/v1/verify`
- `POST /api/v1/github/inspect`

Run backend validation from `backend`:

```cmd
.venv\Scripts\python.exe -m pytest -v
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -m ruff check src tests
.venv\Scripts\python.exe -m ruff format --check src tests
```

Run the deterministic offline policy benchmark from the repository root:

```cmd
cd /d backend && .venv\Scripts\python.exe -m proofgate.benchmark
```

## Limitations

There is no execution worker, runtime reproduction, regression-test execution,
GitHub authentication, persistence, or repository write integration. GitHub
inspection is public-only and subject to unauthenticated API rate limits.
`isolated_sandbox` is
currently unsupported; requesting it does not run code or imply that a sandbox
exists. Evidence and decisions reflect only the analysis actually performed.
Repository inspection is restricted to the root configured by the backend
operator. Do not expose the development API to an untrusted network.
