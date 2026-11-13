# Backend architecture

## Components

- `proofgate.models` defines the Pydantic request, response, evidence, check, and status contracts.
- `proofgate.analyzer` performs bounded, read-only repository path validation, UTF-8 reads, Python AST parsing, one narrowly scoped behavioral-pattern check, and unified-diff structure inspection. It never imports or executes analyzed code.
- `proofgate.evidence` creates bounded evidence records with UTC timestamps, unique IDs, normalized outcomes, and elapsed durations.
- `proofgate.policy` is the deterministic decision layer. Policy version `1.0.1` requires complete mandatory evidence before `VERIFIED`.
- `proofgate.runner` orchestrates safe analysis, evidence collection, skipped-check reporting, and policy evaluation without depending on HTTP.
- `proofgate.api.main` exposes the FastAPI endpoints and maps safe domain errors to bounded public responses.

## Data flow

`POST /api/v1/analyze` validates its request, obtains the server-configured repository root, resolves the requested relative path, and returns a structured summary of bounded Python file reads and AST syntax results.

`POST /api/v1/verify` validates source/diff inputs, runs the safe analyzer and its explicit add/subtract AST rule, records completed and skipped checks, creates evidence records, and invokes the policy. The behavioral finding is returned separately and as inconclusive static evidence; it does not change check status or policy inputs. Reproduction-before, reproduction-after, and regression checks are always skipped. The API never treats skipped checks as passed.

The behavioral rule requires recognized explicit add/subtract wording, an explicitly named top-level function, exactly two required positional parameters, and one direct binary return using those parameters. Unsupported and ambiguous cases are represented as inconclusive findings rather than inferred. A potential mismatch is not a verified bug or proof of runtime behavior.

The runner accepts a repository root as an explicit dependency. `PROOFGATE_REPOSITORY_ROOT` configures the API's single permitted root; clients cannot choose an absolute root. Repository path outputs are relative and public errors do not include host paths or exception traces.

## Extension boundary

Execution is intentionally absent. A future sandbox worker should be a separate, explicitly isolated component with narrow input/output contracts. The worker must not inherit service credentials, filesystem access, or network permissions. Until that boundary exists and is independently assessed, execution-dependent evidence remains skipped.

The API runner is trusted control-plane code: it validates requests, analyzes source as data, applies the policy, and constructs public results. It does not execute submitted code. A future isolated worker would execute untrusted source and tests only in a separately configured execution boundary. The runner must accept phase evidence only when a trusted launcher confirms the job, phase, and exact staged artifact identities, and independently observes worker lifecycle completion. A worker's own Boolean assertion that isolation was enabled is not proof of isolation.

See [verification-policy.md](verification-policy.md) for the proposed versioned worker-report contract and decision handling. The worker is not implemented or enabled in policy version 1.0.1.