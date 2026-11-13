# Verification policy

Policy version: **1.0.1**

The policy is deterministic and independent of the HTTP layer. Every public decision is one of `VERIFIED`, `NOT_REPRODUCED`, or `INSUFFICIENT_EVIDENCE`.

## VERIFIED

`VERIFIED` is permitted only when all required checks have completed with passing check status:

1. The reported issue reproduced before the patch under recorded conditions.
2. The patch was structurally validated and changed files were identified.
3. The same issue did not reproduce after the patch.
4. Required regression tests passed.
5. Syntax checks passed for the patched source.
6. Relevant static checks passed.
7. Mandatory execution-safety checks passed.

Missing checks, skipped checks, inconclusive results, or contradictions prevent `VERIFIED`. Failed regression, syntax, static, or safety checks also prevent it. Static-analysis evidence must identify completed checks as a non-empty list of non-empty names. A successful AST parse or valid diff is not by itself sufficient evidence. Empty test suites cannot pass because execution evidence must explicitly establish that required regression tests ran and passed.

## NOT_REPRODUCED

`NOT_REPRODUCED` means only that the reported issue could not be reproduced under explicitly recorded pre-patch test conditions. It does not prove the bug does not exist. The API must not use this status when reproduction was skipped, unavailable, or inconclusive.

## INSUFFICIENT_EVIDENCE

This is the conservative result when required evidence is missing, a check was skipped or inconclusive, a required check failed, evidence conflicts, the issue persists after patching, or operation is analysis-only. It is also the expected result for the current initial backend because no untrusted code or tests are executed.

## Current implementation

The runner performs bounded static Python syntax analysis, the narrow add/subtract pattern check described below, and diff inspection only. It explicitly skips pre-patch reproduction, post-patch reproduction, and regression tests. Analysis-only operation cannot claim that a patch fixes a bug. The policy version is included in each verification response and tested to remain stable.

Version 1.0.1 corrects acceptance of malformed static-analysis metadata: a truthy scalar such as `true` could previously satisfy the completed-checks requirement. Only a non-empty list of non-empty strings now satisfies it. This milestone keeps the decision policy and decision statuses unchanged while adding a typed behavioral-findings field to the API response.

### Narrow add/subtract behavioral pattern

The verification response includes a typed `behavioral_findings` collection in
addition to its existing checks and evidence. Rule `PG-PY-ADD-SUB-001` recognizes
only explicit requirements for a named function to add or subtract its two
arguments, and only when the function has exactly two required positional
parameters and one direct binary return using those names. A disagreement is
reported as `POTENTIAL_BEHAVIOR_MISMATCH`; matching operators, unsupported or
ambiguous requirements, unsupported expressions, and invalid syntax have
separate finding types.

These findings carry `inconclusive` static-analysis evidence and do not modify
the decision policy, required-check statuses, or policy version. In particular,
they cannot permit `VERIFIED` or `NOT_REPRODUCED`. They do not prove the function
is incorrect or correct, and no submitted source or tests are executed. The rule
is deterministic pattern matching, not general natural-language requirement
analysis.

## Execution and trust boundaries

The trusted **control plane** consists of the API, runner, evidence construction, policy, and (in a future milestone) a separately reviewed launcher. These components validate requests, select files and commands, configure execution, observe process/container lifecycle, validate reports, and decide what evidence to record. Control-plane operations must not be confused with running client-supplied code.

**Untrusted code execution** means invoking submitted source, reproduction fixtures, regression tests, project hooks, or test setup code. It is not performed by the current API in either execution mode. In a future implementation it may occur only inside a deliberately configured, isolated worker; requesting `isolated_sandbox` alone does not establish that such a worker exists or that isolation was effective.

Isolation configuration is evidence about what the trusted launcher asked the runtime to enforce (for example, identity, namespaces, mounts, capabilities, network policy, resource controls, and image identity). It is not a worker-supplied Boolean and is not proof that the runtime or host resisted escape. Phase-completion evidence must include independently observed launcher/process lifecycle facts. A phase report's claims about test outcomes are untrusted until its schema, phase/job binding, artifact identities, counts, and consistency have been checked against those observations.

The current policy's `execution_safety` requirement that `untrusted_code_executed` is exactly `false` is retained. It describes the current no-execution safety behavior and must not be interpreted as evidence that an execution worker was isolated. Do not replace it with a worker-provided `isolated=true` field or otherwise enable worker-backed `VERIFIED` decisions without a new, separately reviewed policy and evidence contract. The present request and response models have no typed worker-report or isolation-attestation contract; this milestone adds no such contract.

## Proposed future worker-report contract (design only)

The following is a proposed versioned internal protocol, not an implemented schema. Use a strict envelope with unknown fields rejected and explicit bounds on serialized bytes, strings, arrays, counts, and error details:

```json
{
  "protocol_version": 1,
  "job_id": "server-generated unique identifier",
  "phase": "pre_patch_reproduction | post_patch_reproduction | regression_tests",
  "policy_version": "1.0.1",
  "artifacts": {
    "source_sha256": "64 lowercase hexadecimal characters",
    "test_manifest_sha256": "64 lowercase hexadecimal characters",
    "environment_digest": "immutable worker image/environment digest"
  },
  "completion": {
    "state": "completed | timed_out | resource_limited | crashed | cancelled",
    "exit_code": 0,
    "duration_ms": 120
  },
  "tests": {
    "collected": 3,
    "passed": 2,
    "failed": 1,
    "skipped": 0,
    "errors": 0,
    "outcomes": [
      {"test_id": "manifest-relative stable test id", "outcome": "passed | failed | skipped | error"}
    ]
  },
  "reproduction_observation": {
    "issue_reproduced": true,
    "basis_test_ids": ["manifest-relative stable test id"]
  },
  "limits": {
    "cpu_ms": 500,
    "memory_bytes": 1000000,
    "processes": 1,
    "output_bytes": 1200,
    "limit_exceeded": false
  }
}
```

The launcher, not the worker, generates the job ID and expected phase/artifact digests. It validates the report against those expected values, the pinned policy version, allowed state/outcome enums, exact test manifest, numeric bounds, and cross-field invariants (for example, outcome totals match counts; completed phases have an observed exit status; non-completed states cannot claim a successful complete test run). Reproduction phases require a non-null `reproduction_observation`; regression phases require it to be null. Its basis test IDs must be present in the reported outcomes. The report's `issue_reproduced` value remains a worker claim and must be interpreted only under a separately reviewed, server-defined fixture contract, never as proof by itself. Each required phase gets one report. Missing, duplicate, malformed, wrong-job, wrong-phase, wrong-artifact, or contradictory reports are rejected and produce `INSUFFICIENT_EVIDENCE`; never select a favorable duplicate or infer a missing phase as passed.

Keep two records distinct:

1. **Worker report:** untrusted claims about collected tests, outcomes, and worker-side limit observations.
2. **Launcher/runtime observation:** independently captured container/job identity, configured isolation settings, start/stop/timeout/kill state, exit status, resource events available from the runtime, and the exact read-only staged artifact digests.

The launcher can corroborate lifecycle, identity, inputs, and runtime configuration, but cannot make hostile test code's assertions truthful. A normal container shares the host kernel and is not an absolute security boundary; configuration evidence does not guarantee freedom from runtime/kernel vulnerabilities or escape.

### Future decision handling

- `VERIFIED` remains disabled until trusted launcher evidence, a validated complete report for every required phase, comparable pre/post reproduction conditions, a valid pre-patch reproduction, a post-patch non-reproduction, passing required regression tests, and the other mandatory checks are all established under a reviewed policy. Any timeout, resource-limit event, abnormal exit, required skip/error, missing/duplicate report, mismatch, or contradiction blocks it.
- `NOT_REPRODUCED` is allowed only when the trusted launcher confirms that the complete pre-patch phase ran against the expected pre-patch source and test artifacts under the recorded conditions, and a valid complete report indicates the issue did not reproduce. It describes only those conditions. Timeout, setup/collection/environment error, worker crash, invalid report, or missing evidence is not non-reproduction.
- `INSUFFICIENT_EVIDENCE` is required when worker isolation was not configured/independently observed, a phase is incomplete or unsafe, any report is absent/duplicated/invalid/contradictory, a required test was skipped or errored, or result-to-job/artifact binding fails.

This design does not alter policy behavior or enable execution. Before implementation, define the typed internal models and launcher interface, review a concrete runtime threat model and deployment configuration, and revise the policy so execution-safety evidence means verified launcher configuration rather than the current no-execution assertion. Preserve analysis-only behavior and reject client-supplied synthetic results.