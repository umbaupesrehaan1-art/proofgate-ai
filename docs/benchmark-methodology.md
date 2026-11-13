# Benchmark methodology

The offline policy benchmark uses deterministic synthetic evidence fixtures to
check that decision outcomes remain stable. It is not a measure of behavioral
rule accuracy, runtime correctness, or real-world defect detection.

The fixture set includes a case where a `POTENTIAL_BEHAVIOR_MISMATCH` static
finding is present without runtime evidence. It must remain
`INSUFFICIENT_EVIDENCE`; a static pattern result must not promote a policy
decision.

## Evaluation set

Build a versioned set of reproducible bug-fix cases. Each case should contain a pinned vulnerable revision, a patch, explicit pre-patch reproduction conditions, an expected post-patch result, and required regression checks. Keep expected outcomes and case provenance reviewable.

## Measurements

Report at least:

- **True positive / correct verification:** a genuinely fixed issue is verified only when all required checks support it.
- **False positive:** an incorrect or incomplete patch is marked `VERIFIED`.
- **False negative:** a correct patch is not verified despite sufficient valid evidence.
- **NOT_REPRODUCED accuracy:** reproduction failures are reported only with recorded, reproducible conditions and are not interpreted as proof of absence.
- **Evidence completeness:** fraction of required checks actually run and correctly represented.
- **Reproducibility:** repeated runs against the same pinned case yield consistent evidence and outcomes.

Report denominators, confidence intervals where appropriate, skipped cases, infrastructure failures, and policy/tool versions. Do not count skipped or inconclusive checks as passes. Re-run cases in a clean, controlled environment and independently review false positives before changing the policy.

## Future execution requirement

Benchmarking code that requires running repository tests must wait for a separately isolated worker. Host execution of untrusted benchmark repositories is out of scope for this milestone.