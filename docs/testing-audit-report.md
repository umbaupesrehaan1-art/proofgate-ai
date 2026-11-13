# ProofGate AI testing audit report

Date: 2026-10-19
Project root: C:\Users\DELL\Desktop\proofgate-ai

## Scope and supported commands

### Backend

The backend support and command set are defined in [backend/pyproject.toml](../backend/pyproject.toml) and [README.md](../README.md).

Supported backend validation commands documented in the repo:

- `cd /d backend && .venv\Scripts\python.exe -m pytest -v`
- `cd /d backend && .venv\Scripts\python.exe -m pip check`
- `cd /d backend && .venv\Scripts\python.exe -m ruff check src tests`
- `cd /d backend && .venv\Scripts\python.exe -m ruff format --check src tests`
- `cd /d backend && .venv\Scripts\python.exe -m proofgate.benchmark`
- `cd /d backend && .venv\Scripts\python.exe -m uvicorn proofgate.api.main:app --host 127.0.0.1 --port 8000`

The backend project declares Python `>=3.12,<3.14` and dependencies: FastAPI, Uvicorn, Pydantic, pydantic-settings, pytest, ruff, and httpx in dev extras.

### Frontend

The frontend scripts are defined in [frontend/package.json](../frontend/package.json).

Available scripts:

- `npm run dev`
- `npm run build`
- `npm run preview`

There is no `lint` script and no `test` script configured in the current package manifest. The TypeScript compiler package is present in devDependencies, so type-checking was executed directly with `npx tsc --noEmit`.

## Commands executed and results

### Completed

1. Backend full suite
   Command:
   `cd c:\Users\DELL\Desktop\proofgate-ai\backend ; .\.venv\Scripts\python.exe -m pytest -q`
   Result: `94 passed, 3 skipped, 1 warning in 1.99s`

2. Backend dependency and lint/format checks
   Command:
   `cd c:\Users\DELL\Desktop\proofgate-ai\backend ; .\.venv\Scripts\python.exe -m pip check ; .\.venv\Scripts\python.exe -m ruff check src tests ; .\.venv\Scripts\python.exe -m ruff format --check src tests`
   Result: `No broken requirements found.` / `All checks passed!` / `15 files already formatted`

3. Offline policy benchmark
   Command:
   `cd c:\Users\DELL\Desktop\proofgate-ai\backend ; .\.venv\Scripts\python.exe -m proofgate.benchmark`
   Result:
   - `Cases: 18; Passed: 18; Failed: 0; Pass rate: 100.00%`
   - exit status 0

4. GitHub API integration tests
   Command:
   `cd c:\Users\DELL\Desktop\proofgate-ai\backend ; .\.venv\Scripts\python.exe -m pytest tests/test_github.py -q`
   Result: `19 passed, 1 warning in 0.79s`

5. Frontend type-check and production build
   Command:
   `cd c:\Users\DELL\Desktop\proofgate-ai\frontend ; npx tsc --noEmit ; npm run build`
   Result:
   - TypeScript check exited successfully with no diagnostics
   - Vite production build succeeded:
     - `✓ built in 379ms`
     - generated `dist/index.html`, CSS bundle, and JS bundle

### Failed

- None in the executed validation commands above.

### Skipped

- Three Windows-only symlink tests in the backend suite were skipped by pytest because symlink creation is unavailable on this platform.
- The backend test output names the skipped tests as:
  - `tests/test_analyzer.py:60`
  - `tests/test_analyzer.py:86`
  - `tests/test_analyzer.py:121`

### Blocked

- Git repository checks are blocked because the project is not a Git worktree:
  command: `git -C "c:\Users\DELL\Desktop\proofgate-ai" status --short ; git -C "c:\Users\DELL\Desktop\proofgate-ai" diff --check`
  result: `fatal: not a git repository (or any of the parent directories): .git`

### Unrun

- Frontend lint: not run because no lint script or linter dependency is configured in [frontend/package.json](../frontend/package.json).
- Frontend unit tests: not run because the project does not define a `test` script or a test runner dependency in the manifest.

## Security coverage and evidence quality

The backend documentation and implementation describe a deliberately read-only verification model. Observed coverage includes:

- no project code execution during verification or policy benchmark execution
- AST parsing only for Python source, never import or execute of user-submitted code
- repository path validation to reject absolute paths, traversal, and Windows drive roots
- symlink and reparse-point handling for repository reads
- GitHub inspection limited to the public API host and rejecting redirects outside the approved host
- hard size caps for repository files, source bytes, patch bytes, and diff line records
- no authentication or write operations in the GitHub inspection path
- policy decision remains `INSUFFICIENT_EVIDENCE` when runtime evidence is absent

This is consistent with the project’s threat model and the “analysis-only” execution mode. It does not claim runtime verification or sandbox security beyond the explicit design boundary.

## Warnings and remaining gaps

- Starlette deprecation warning observed from FastAPI TestClient on `httpx`:
  `Using 'httpx' with 'starlette.testclient' is deprecated; install 'httpx2' instead.`
- The root is not a Git repository, so Git-pinned diff and status checks are unavailable.
- The frontend has no linting configuration or test script configured in the package manifest, which limits static quality gates to TypeScript compilation and production build checks.
- Runtime execution and real sandbox validation are intentionally unimplemented and remain out of scope for this project’s current policy version.

## Final audit summary

Completed checks:
- Backend suite: pass
- Backend dependency, lint, and format checks: pass
- Offline benchmark: pass
- GitHub API integration tests: pass
- Frontend TypeScript check: pass
- Frontend production build: pass

Failed checks:
- None observed in the executed commands.

Skipped checks:
- 3 Windows symlink tests skipped in backend suite due to platform limitations.

Blocked checks:
- git status/diff checks are blocked because the project is not a Git repository.

Unrun checks:
- frontend lint
- frontend tests

The current state is healthy for the implemented static-analysis and policy-validation scope, with the main caveats being the lack of Git metadata and the intentionally unsupported runtime/sandbox execution path.

## Follow-up addendum — 2026-10-20

This addendum records the approved frontend quality work and fresh validation.
The preceding report sections preserve the 2026-10-19 audit snapshot. At the
start of this follow-up, `package.json`, `package-lock.json`, the ESLint/Vitest
configs, and the lint/test scripts were already present; the test/setup files
and this checklist existed as empty files. Those existing changes were
preserved. No application component, backend code, backend dependency, API
contract, or policy behavior was changed.

### Files changed

- `frontend/package.json` and `frontend/package-lock.json`: resolved test-tool
  versions were adjusted for the documented Node support range. The existing
  `lint` and `test` scripts were already present and were retained.
- `frontend/src/api.test.ts`: added six mocked API-client tests.
- `frontend/src/App.test.tsx`: added seven mocked dashboard behavior tests.
- `frontend/src/setupTests.ts`: configured jest-dom matchers and React Testing
  Library cleanup between tests.
- `docs/demo-readiness-checklist.md`: populated the previously empty file with
  repeatable manual steps and actual endpoints/request behavior.
- `docs/testing-audit-report.md`: appended this evidence; the historical audit
  above was not replaced.

The existing `frontend/eslint.config.js` and `frontend/vitest.config.ts` were
inspected and used without modification. `@eslint/js` was removed as an unused
direct dependency; the flat configuration uses `typescript-eslint` and the
React Hooks plugin directly.

### Dependency compatibility and changes

Observed runtime: Node `v24.18.0`, npm `11.16.0`. Final installed frontend
versions:

- React / React DOM `19.3.1`
- Vite `8.3.4`, `@vitejs/plugin-react` `6.1.2`
- TypeScript `5.9.3`
- ESLint `10.13.0`, `typescript-eslint` `8.71.2`,
  `eslint-plugin-react-hooks` `7.1.1`, `eslint-plugin-react-refresh` `0.5.7`
- Vitest `4.1.12`, jsdom `27.4.0`
- React Testing Library `16.3.3`, user-event `14.6.8`,
  jest-dom `6.9.1`

The final package ranges include `eslint: ^10.13.0`, `vitest: ^4.1.12`,
`jsdom: ^27.4.0`, and `@testing-library/jest-dom: ^6.9.1`. The approved
testing packages were already declared in the inspected starting manifest;
this follow-up adjusted resolved Vitest/jsdom/jest-dom versions and removed the
unused `@eslint/js` direct dependency. No backend packages were installed or
modified.

Compatibility evidence:

- `vitest@4.1.12` declares Node `^20.0.0 || ^22.0.0 || >=24.0.0`.
- `jsdom@27.4.0` declares Node `^20.19.0 || ^22.12.0 || >=24.0.0`.
- `eslint@10.13.0` declares Node `^20.19.0 || ^22.13.0 || >=24`.
- Vite `8.3.4` declares Node `^20.19.0 || >=22.12.0`.
- The actual Node `24.18.0` meets all of these constraints. For Node 22 users,
  the lint script requires 22.13+ (whereas Vite/jsdom permit 22.12); this is
  called out in the demo checklist. Node 20.19+ also meets the listed tools'
  constraints.

Package commands executed:

- `npm install --save-dev 'vitest@^4.0.18' 'jsdom@^27.4.0' '@testing-library/jest-dom@^6.9.1'`
  Result: installation completed, lockfile updated, npm reported 0
  vulnerabilities.
- `npm install --save-dev 'eslint@^9.39.2'; npm uninstall --save-dev '@eslint/js'`
  Result: this compatibility experiment resolved to a deprecated ESLint
  `9.39.5` and emitted peer/deprecation warnings; that unsupported version was
  not retained.
- `npm install --save-dev 'eslint@^10.13.0'`
  Result: ESLint `10.13.0` restored, lockfile updated, npm reported 0
  vulnerabilities. `@eslint/js` remains removed because the flat config does
  not import or use it.
- `npm ls --depth=0`
  Result: completed successfully with the final versions listed above.
- `node --version` / `npm --version`
  Result: `v24.18.0` / `11.16.0`.

### Frontend behavior tested

All API tests stub `fetch`; app tests mock the API module. No test calls a live
backend or GitHub service. Submitted Python and patch strings are treated as
ordinary UI/API test data and are not executed.

`frontend/src/api.test.ts` covers network failure mapping, structured HTTP 422
errors, malformed success bodies, non-success status rejection, valid response
parsing and request shape, and unreadable JSON responses.

`frontend/src/App.test.tsx` covers empty bug-description validation before the
API call, valid analysis-only request payload, decision/finding/evidence
rendering, loading state, API error and retry behavior, GitHub empty URL and
file-limit validation, backend-delegated GitHub URL rejection, and the
repository-analysis request path and safety banner.

The current form does not validate GitHub URL syntax/host locally. It rejects an
empty URL and invalid file limits client-side, then delegates public GitHub URL
acceptance to the backend. The tests and checklist reflect that existing
behavior; no validation behavior was changed.

### Fresh validation — exact commands and results

Commands below were run from the indicated working directory using
PowerShell `Set-Location`.

Frontend:

- `Set-Location 'C:\Users\DELL\Desktop\proofgate-ai\frontend'; npm run lint`
  Result: exit code 0; ESLint produced no diagnostics.
- `Set-Location 'C:\Users\DELL\Desktop\proofgate-ai\frontend'; npm test`
  Result: `Test Files 2 passed (2); Tests 13 passed (13)`.
- `Set-Location 'C:\Users\DELL\Desktop\proofgate-ai\frontend'; npx tsc --noEmit`
  Result: exit code 0; no diagnostics.
- `Set-Location 'C:\Users\DELL\Desktop\proofgate-ai\frontend'; npm run build`
  Result: exit code 0; Vite `8.3.4`, 17 modules transformed, production build
  completed (`✓ built`).

Backend:

- `Set-Location 'C:\Users\DELL\Desktop\proofgate-ai\backend'; .\.venv\Scripts\python.exe -m pytest -q`
  Result: `94 passed, 3 skipped, 1 warning in 10.68s`.
- `Set-Location 'C:\Users\DELL\Desktop\proofgate-ai\backend'; .\.venv\Scripts\python.exe -m proofgate.benchmark`
  Result: `Cases: 18; Passed: 18; Failed: 0; Pass rate: 100.00%`; exit code 0.
- `Set-Location 'C:\Users\DELL\Desktop\proofgate-ai\backend'; .\.venv\Scripts\python.exe -m pip check; .\.venv\Scripts\python.exe -m ruff check src tests; .\.venv\Scripts\python.exe -m ruff format --check src tests`
  Result: `No broken requirements found.` / `All checks passed!` /
  `15 files already formatted`.

### Failed, skipped, blocked, and not-run checks

- **Final failed checks:** none.
- **Resolved test-run failures during implementation:** an initial `npm test`
  had duplicate rendered elements because automatic React Testing Library
  cleanup was not configured; after adding cleanup, one assertion incorrectly
  passed the `within()` query object to a DOM matcher and was corrected. A
  combined parallel validation run had three Vitest cases hit the 5-second
  timeout; the complete suite was rerun without competing work and passed all
  13 tests. API-only `npx vitest run src/api.test.ts` also passed all 6 tests.
  These failures were not hidden or treated as final passes.
- **Skipped:** the same three Windows symlink-dependent backend tests were
  explicitly skipped at `tests/test_analyzer.py:60`, `:86`, and `:121`.
- **Warning:** the Starlette TestClient deprecation warning was reproduced.
  Installed versions are FastAPI `0.143.2`, Starlette `1.8.0`, HTTPX `0.28.1`;
  `httpx2` is not installed. The warning originates from the installed
  `starlette.testclient` fallback to `httpx`, imported through
  `fastapi.testclient`. No backend dependency was changed. Resolve separately
  with a compatible, tested dependency-stack change before production rather
  than suppressing the warning.
- **Blocked:** `.git` is still absent from the intended project root
  (`Test-Path -LiteralPath 'C:\Users\DELL\Desktop\proofgate-ai\.git'` returned
  `False`). Earlier `git status`/`git diff --check` attempts were blocked. No
  Git initialization or repository configuration change was made.
- **Not run:** the browser/manual checklist, an actual health-endpoint request,
  live GitHub pull-request inspection, and a formal security scan were not run.
  The backend automated suite is local; it does not establish that an external
  GitHub service or a running demo environment is available.
- **Requires approval:** no frontend changes remain pending approval. Any
  backend dependency change to address the Starlette warning remains separate
  and was intentionally not made in this task.

### Security boundary and remaining release risks

The change touched only frontend tests/setup, frontend dev dependencies, and
documentation. It did not alter backend or frontend production request
behavior, decision meanings, API schemas, GitHub operations, or path/diff
protections. The project documentation and relevant workflow/UI text state
that submitted source and submitted tests are never executed; GitHub inspection
is bounded and read-only; no merge, commit, push, or repository mutation is
provided. The UI continues to distinguish static findings from runtime proof,
and analysis-only verification remains `INSUFFICIENT_EVIDENCE` when execution
evidence is unavailable. This was a boundary-preservation review, not a formal
security test or sandbox validation.

Prioritized remaining actions:

1. **Starlette deprecation:** resolve with a compatible, tested backend
   dependency strategy before production; warning only and not a local-demo
   blocker.
2. **Git metadata absent:** supply the intended repository/worktree before
   release workflows that rely on status, diff, or change attribution; does
   not block a local demo.
3. **Windows symlink coverage skipped:** run those cases in a platform with
   symlink support before production if those path-safety cases are release
   criteria; Windows local demo remains possible.
4. **Manual demo and live GitHub path unverified in this follow-up:** complete
   the checklist in the actual demo environment before presenting external
   GitHub inspection. Do not describe that path as manually verified yet.
5. **Node 22.12 lint engine edge:** use Node 20.19+, Node 22.13+, or Node 24+
   for all frontend quality commands; the actual validated environment is
   Node 24.18.0.
