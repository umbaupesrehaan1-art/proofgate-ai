# ProofGate AI local demo checklist

This checklist describes manual browser/API checks. It is separate from the
automated backend and frontend tests; none of these steps execute submitted
source code or submitted tests.

## Prerequisites

- Windows 10/11, Python 3.12 with the existing `backend\.venv`, and npm. For
  all listed frontend checks use Node.js 20.19+, 22.13+, or 24+. Vite itself
  supports Node 22.12+, but ESLint 10 requires Node 22.13+ on the Node 22 line.
- Start the backend and frontend in separate terminal windows.
- Use only source and repositories you are authorized to inspect.

## Start the application

1. In a CMD window, start the backend from the project root:

   ```cmd
   cd /d C:\Users\DELL\Desktop\proofgate-ai\backend
   set "PROOFGATE_REPOSITORY_ROOT=C:\Users\DELL\Desktop\proofgate-ai"
   .venv\Scripts\python.exe -m uvicorn proofgate.api.main:app --host 127.0.0.1 --port 8000
   ```

   The backend remains bound to loopback and has no authentication. Do not expose
   it to an untrusted network.

2. In another CMD window, start the frontend:

   ```cmd
   cd /d C:\Users\DELL\Desktop\proofgate-ai\frontend
   npm run dev
   ```

3. Check backend health at `http://127.0.0.1:8000/health`. Expect HTTP 200 and
   `{"status":"ok"}`. Open the local URL printed by Vite,
   normally `http://127.0.0.1:5173`, and confirm the ProofGate dashboard loads.
   The API exposes `GET /health`, `POST /api/v1/verify`,
   `POST /api/v1/analyze`, and `POST /api/v1/github/inspect`.

   Request/response reference:

   - `POST /api/v1/verify`: `bug_description`, exactly one of `source_code` or
     `repository_path`, optional `unified_diff`, and
     `execution_mode: "analysis_only"`. A successful response includes
     `verification_id`, `decision`, `summary`, `evidence`,
     `behavioral_findings`, `checks`, `checks_performed`, `checks_skipped`,
     `reasons`, `duration_ms`, and `policy_version`.
   - `POST /api/v1/analyze`: `repository_path` and `max_files`. A successful
     response includes `root_path`, `file_count`, `python_file_count`,
     `syntax_error_count`, `analyzed_paths`, `files`, and `truncated`.
   - `POST /api/v1/github/inspect`: `repository_url`, optional
     `pull_request_number`, and `max_files`. A successful response includes
     `repository`, `pull_request`, `files`, `evidence`, `coverage_complete`,
     `coverage_messages`, `decision`, `decision_reasons`, and `policy_version`.
   - Structured API errors include `error`, `message`, and `request_id`, with
     optional `fields`.

## Manual dashboard checks

4. **Valid source:** In “Verify a change,” enter a bug description of at least
   five non-whitespace characters and valid Python source, then select
   “Analyze evidence.” Confirm the response is rendered from the API. In current
   `analysis_only` mode, the expected decision is `INSUFFICIENT_EVIDENCE`;
   reproduction and regression testing are reported as skipped.

5. **Invalid syntax:** Submit the description “The add(a, b) function should
   add its two arguments.” and malformed Python:

   ```python
   def add(a, b):
       return a -
   ```

   Confirm the response has a failed syntax check, an `INVALID_SYNTAX`
   behavioral finding, and the conservative `INSUFFICIENT_EVIDENCE` decision.
   Do not expect syntax failure to execute or test the source.

6. **Narrow operator mismatch:** Enter the description “The add(a, b) function
   should add its two arguments.” and source:

   ```python
   def add(a, b):
       return a - b
   ```

   Confirm the UI shows a `POTENTIAL_BEHAVIOR_MISMATCH` finding for the narrow
   add/subtract rule. This is a static pattern finding, not proof of general
   behavior or runtime correctness.

7. **Empty and invalid form input:** Submit with an empty bug description and
   confirm the client-side validation message appears without a request. Switch
   to “Inspect GitHub,” leave the repository URL empty, and confirm the required
   URL message appears. Enter a URL-like string that is not an accepted public
   GitHub repository URL and observe the backend validation error. Set “Maximum
   files to inspect” outside 1–20 and confirm client-side validation prevents
   the request. The client checks non-emptiness and file-limit bounds; repository
   URL acceptance is enforced by the backend.

8. **API failure / backend unavailable:** Stop the backend with Ctrl+C, submit
   valid verification input, and confirm the UI shows the API connectivity
   error. Restart the backend and use Retry if offered; server/network errors
   permit retry. A structured HTTP 422 response should surface the API's
   validation message and fields rather than appear as a successful result.

9. **Public GitHub pull request:** In “Inspect GitHub,” enter a public
   `https://github.com/owner/repository` URL and a pull-request number, then
   inspect the returned files and coverage status. Use a public repository/PR
   with content you are authorized to inspect. Requests are read-only; the UI
   does not approve, comment on, merge, or write to a repository. GitHub
   unauthenticated rate limits and inaccessible/private repositories can
   prevent this manual check.

10. **Truncation/incomplete coverage:** For repository analysis, choose a
    repository path containing enough Python files and set a `max_files` below
    the available count; confirm the result marks `TRUNCATED: YES` and indicates
    the result limit. For GitHub inspection, confirm partial coverage and
    coverage messages are shown when the API reports incomplete retrieval.
    Do not induce excessive network or file load to trigger limits.

11. **Decision and execution boundary:** Confirm a verification result's
    displayed decision and explanatory text match the API. In particular,
    analysis-only inputs cannot establish `VERIFIED` or `NOT_REPRODUCED` without
    the required execution evidence; the current expected result is
    `INSUFFICIENT_EVIDENCE`. Confirm the safety banner/footer says submitted
    source and tests are not executed.

12. **No execution:** Use only the analysis UI/API paths above. Do not run
    submitted source, submitted tests, project hooks, or commands sourced from
    inspected repositories. The application is a read-only analyzer and does
    not provide a sandbox or runtime verification.

## Automated checks (not manual demo steps)

Run from the relevant directories:

```cmd
cd /d C:\Users\DELL\Desktop\proofgate-ai\frontend
npm run lint
npm test
npx tsc --noEmit
npm run build
```

```cmd
cd /d C:\Users\DELL\Desktop\proofgate-ai\backend
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m proofgate.benchmark
```

Automated results belong in `docs/testing-audit-report.md` only after the
commands are actually run and their output is recorded.