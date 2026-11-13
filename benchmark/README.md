# Offline policy decision benchmark

## Purpose

This deterministic benchmark checks that ProofGate's existing decision policy maps
structured evidence to the expected public decision. It calls
`proofgate.policy.evaluate_policy` directly and does not start the HTTP server, make
network requests, import benchmark fixture code, or execute submitted source or tests.
All benchmark evidence is synthetic and is strictly for policy testing.

## Fixtures

`fixtures/policy_cases.json` contains a versioned JSON document with shared
`base_checks` and named `cases`. Each case selects or omits checks, optionally
overrides check fields, and declares an `execution_mode` and `expected_decision`.
The loader validates the fixture schema and each check with the existing
`CheckResult` model before calling the production policy.

Expected decisions use only `VERIFIED`, `NOT_REPRODUCED`, and
`INSUFFICIENT_EVIDENCE`. The expected values are reviewed benchmark assertions;
they are not generated from the implementation under test. Timeout, skipped, setup,
collection, environment, and malformed/incomplete worker-report situations are
represented using the existing inconclusive/skipped check statuses. The current
models do not describe worker report validity or failure categories as a dedicated
contract, so these fixtures test the policy's handling of the available check
statuses rather than validating a real worker protocol.

## Run on Windows

From a Windows CMD prompt at the repository root, run exactly:

```cmd
cd /d backend && .venv\Scripts\python.exe -m proofgate.benchmark
```

Each case prints `PASS` or `FAIL` with its expected and actual decision. The final
line reports total cases, passed cases, failed cases, and pass rate. A nonzero
process exit status indicates at least one mismatch or a fixture-loading error.

## Interpreting results

A 100% pass rate means the current policy implementation agrees with the declared
expected decisions for this synthetic fixture set. A lower rate identifies a
policy/expectation mismatch that should be reviewed by case ID. This is a
decision-logic regression benchmark, not an empirical accuracy estimate: these
cases do not establish the real-world correctness of arbitrary code fixes, do not
execute tests, and do not validate a sandbox or worker.

For real-world evaluation involving repository tests, wait for a separately
isolated execution worker and a reviewed, reproducible test corpus. Host execution
of untrusted benchmark repositories remains out of scope.