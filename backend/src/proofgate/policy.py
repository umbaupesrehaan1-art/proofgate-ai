"""Conservative, deterministic decision rules for verification evidence."""

from __future__ import annotations

from dataclasses import dataclass

from proofgate.models import CheckResult, CheckStatus, ExecutionMode, VerificationStatus

POLICY_VERSION = "1.0.1"

MANDATORY_CHECKS = (
    "pre_patch_reproduction",
    "patch_validation",
    "post_patch_reproduction",
    "regression_tests",
    "syntax_check",
    "static_analysis",
    "execution_safety",
)
EXPECTED_CATEGORIES = {
    "pre_patch_reproduction": "issue_reproduction",
    "patch_validation": "patch_validation",
    "post_patch_reproduction": "issue_reproduction",
    "regression_tests": "regression_testing",
    "syntax_check": "syntax_checking",
    "static_analysis": "static_analysis",
    "execution_safety": "execution_safety",
}


@dataclass(frozen=True)
class PolicyDecision:
    status: VerificationStatus
    reasons: tuple[str, ...]


def evaluate_policy(
    checks: list[CheckResult],
    *,
    execution_mode: ExecutionMode,
) -> PolicyDecision:
    """Apply policy v1.0.1; syntax/diff inspection alone can never verify a fix.

    VERIFIED requires explicit completed evidence for all mandatory checks,
    reproduction before the patch, non-reproduction after it, passing regression,
    syntax, static, and safety checks. Missing, skipped, inconclusive, or
    contradictory evidence is conservative. NOT_REPRODUCED only reports that the
    supplied reproduction conditions did not reproduce the issue; it is not proof
    that the bug is absent.
    """
    if execution_mode is ExecutionMode.ANALYSIS_ONLY:
        return PolicyDecision(
            VerificationStatus.INSUFFICIENT_EVIDENCE,
            ("Analysis-only mode does not execute reproduction or regression checks.",),
        )

    by_name: dict[str, list[CheckResult]] = {}
    for check in checks:
        by_name.setdefault(check.name, []).append(check)

    for name, entries in by_name.items():
        if len(entries) > 1:
            first = entries[0]
            if any(
                item.model_dump(mode="json") != first.model_dump(mode="json")
                for item in entries[1:]
            ):
                return PolicyDecision(
                    VerificationStatus.INSUFFICIENT_EVIDENCE,
                    (f"Conflicting results were recorded for the {name} check.",),
                )
            return PolicyDecision(
                VerificationStatus.INSUFFICIENT_EVIDENCE,
                (f"Duplicate results were recorded for the {name} check.",),
            )

    pre_check = by_name.get("pre_patch_reproduction", [None])[0]
    if (
        pre_check is not None
        and pre_check.required
        and pre_check.category.value == EXPECTED_CATEGORIES["pre_patch_reproduction"]
        and pre_check.status is CheckStatus.PASSED
        and pre_check.details.get("reproduced") is False
        and pre_check.details.get("conditions_recorded") is True
        and isinstance(pre_check.details.get("conditions_id"), str)
        and bool(pre_check.details.get("conditions_id"))
    ):
        return PolicyDecision(
            VerificationStatus.NOT_REPRODUCED,
            (
                "The reported issue was not reproduced under the recorded pre-patch conditions; "
                "this does not prove the bug is absent.",
            ),
        )

    missing_or_incomplete: list[str] = []
    for name in MANDATORY_CHECKS:
        check = by_name.get(name, [None])[0]
        if check is None:
            missing_or_incomplete.append(f"{name} was not provided")
        elif not check.required:
            missing_or_incomplete.append(f"{name} was not marked mandatory")
        elif check.category.value != EXPECTED_CATEGORIES[name]:
            missing_or_incomplete.append(f"{name} has an invalid evidence category")
        elif check.status is not CheckStatus.PASSED:
            missing_or_incomplete.append(f"{name} was {check.status.value}")
    if missing_or_incomplete:
        return PolicyDecision(
            VerificationStatus.INSUFFICIENT_EVIDENCE,
            tuple(missing_or_incomplete),
        )

    pre_reproduced = pre_check.details.get("reproduced") is True
    post_check = by_name["post_patch_reproduction"][0]
    post_reproduced = post_check.details.get("reproduced")
    if pre_check.details.get("conditions_recorded") is not True:
        return PolicyDecision(
            VerificationStatus.INSUFFICIENT_EVIDENCE,
            ("Pre-patch reproduction conditions were not explicitly recorded.",),
        )
    pre_conditions_id = pre_check.details.get("conditions_id")
    post_conditions_id = post_check.details.get("conditions_id")
    if (
        not isinstance(pre_conditions_id, str)
        or not pre_conditions_id
        or pre_conditions_id != post_conditions_id
    ):
        return PolicyDecision(
            VerificationStatus.INSUFFICIENT_EVIDENCE,
            ("Pre- and post-patch reproduction conditions are not demonstrably equivalent.",),
        )
    patch_details = by_name["patch_validation"][0].details
    changed_paths = patch_details.get("changed_paths")
    if (
        patch_details.get("valid") is not True
        or not isinstance(changed_paths, list)
        or not changed_paths
        or not all(isinstance(path, str) and path for path in changed_paths)
    ):
        return PolicyDecision(
            VerificationStatus.INSUFFICIENT_EVIDENCE,
            ("Patch evidence does not establish a validated source change.",),
        )
    regression_details = by_name["regression_tests"][0].details
    if type(regression_details.get("tests_run")) is not int or regression_details["tests_run"] < 1:
        return PolicyDecision(
            VerificationStatus.INSUFFICIENT_EVIDENCE,
            ("No regression tests were established as having run.",),
        )
    if by_name["syntax_check"][0].details.get("syntax_valid") is not True:
        return PolicyDecision(
            VerificationStatus.INSUFFICIENT_EVIDENCE,
            ("Syntax evidence does not establish that the patched source parses.",),
        )
    completed_checks = by_name["static_analysis"][0].details.get("checks_completed")
    if (
        not isinstance(completed_checks, list)
        or not completed_checks
        or any(not isinstance(item, str) or not item.strip() for item in completed_checks)
    ):
        return PolicyDecision(
            VerificationStatus.INSUFFICIENT_EVIDENCE,
            ("Static-analysis evidence does not identify completed checks.",),
        )
    if by_name["execution_safety"][0].details.get("untrusted_code_executed") is not False:
        return PolicyDecision(
            VerificationStatus.INSUFFICIENT_EVIDENCE,
            ("Execution-safety evidence is missing or contradictory.",),
        )
    if not pre_reproduced:
        return PolicyDecision(
            VerificationStatus.INSUFFICIENT_EVIDENCE,
            ("Pre-patch reproduction did not establish that the reported issue was present.",),
        )
    if post_reproduced is True:
        return PolicyDecision(
            VerificationStatus.INSUFFICIENT_EVIDENCE,
            ("The reported issue remains reproducible after the patch.",),
        )
    if post_reproduced is not False:
        return PolicyDecision(
            VerificationStatus.INSUFFICIENT_EVIDENCE,
            ("Post-patch reproduction evidence is missing or ambiguous.",),
        )

    return PolicyDecision(
        VerificationStatus.VERIFIED,
        ("All mandatory checks passed and the issue reproduced before but not after the patch.",),
    )
