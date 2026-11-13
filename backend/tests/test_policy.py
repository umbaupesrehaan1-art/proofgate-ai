from proofgate.models import (
    CheckResult,
    CheckStatus,
    EvidenceCategory,
    ExecutionMode,
    VerificationStatus,
)
from proofgate.policy import POLICY_VERSION, evaluate_policy


def complete_checks() -> list[CheckResult]:
    checks = [
        (
            "pre_patch_reproduction",
            EvidenceCategory.ISSUE_REPRODUCTION,
            {"reproduced": True, "conditions_recorded": True, "conditions_id": "case-123"},
        ),
        (
            "patch_validation",
            EvidenceCategory.PATCH_VALIDATION,
            {"valid": True, "changed_paths": ["src/main.py"]},
        ),
        (
            "post_patch_reproduction",
            EvidenceCategory.ISSUE_REPRODUCTION,
            {"reproduced": False, "conditions_id": "case-123"},
        ),
        ("regression_tests", EvidenceCategory.REGRESSION_TESTING, {"tests_run": 3}),
        ("syntax_check", EvidenceCategory.SYNTAX_CHECKING, {"syntax_valid": True}),
        (
            "static_analysis",
            EvidenceCategory.STATIC_ANALYSIS,
            {"checks_completed": ["python_ast_parse"]},
        ),
        (
            "execution_safety",
            EvidenceCategory.EXECUTION_SAFETY,
            {"untrusted_code_executed": False},
        ),
    ]
    return [
        CheckResult(
            name=name,
            category=category,
            status=CheckStatus.PASSED,
            message=f"{name} completed",
            details=details,
        )
        for name, category, details in checks
    ]


def decide(checks: list[CheckResult]):
    return evaluate_policy(checks, execution_mode=ExecutionMode.ISOLATED_SANDBOX)


def test_complete_valid_evidence_is_verified() -> None:
    result = decide(complete_checks())
    assert result.status is VerificationStatus.VERIFIED


def test_missing_pre_patch_reproduction_is_insufficient() -> None:
    checks = [item for item in complete_checks() if item.name != "pre_patch_reproduction"]
    assert decide(checks).status is VerificationStatus.INSUFFICIENT_EVIDENCE


def test_issue_remains_reproducible_after_patch() -> None:
    checks = complete_checks()
    post_check = next(item for item in checks if item.name == "post_patch_reproduction")
    post_check.details["reproduced"] = True
    result = decide(checks)
    assert result.status is VerificationStatus.INSUFFICIENT_EVIDENCE
    assert "remains reproducible" in result.reasons[0]


def test_regression_test_failure_prevents_verification() -> None:
    checks = complete_checks()
    next(item for item in checks if item.name == "regression_tests").status = CheckStatus.FAILED
    assert decide(checks).status is VerificationStatus.INSUFFICIENT_EVIDENCE


def test_syntax_failure_prevents_verification() -> None:
    checks = complete_checks()
    next(item for item in checks if item.name == "syntax_check").status = CheckStatus.FAILED
    assert decide(checks).status is VerificationStatus.INSUFFICIENT_EVIDENCE


def test_skipped_mandatory_check_prevents_verification() -> None:
    checks = complete_checks()
    next(item for item in checks if item.name == "regression_tests").status = CheckStatus.SKIPPED
    assert decide(checks).status is VerificationStatus.INSUFFICIENT_EVIDENCE


def test_inconclusive_check_prevents_verification() -> None:
    checks = complete_checks()
    next(
        item for item in checks if item.name == "static_analysis"
    ).status = CheckStatus.INCONCLUSIVE
    assert decide(checks).status is VerificationStatus.INSUFFICIENT_EVIDENCE


def test_empty_test_suite_cannot_be_counted_as_passed() -> None:
    checks = complete_checks()
    next(item for item in checks if item.name == "regression_tests").details["tests_run"] = 0
    result = decide(checks)
    assert result.status is VerificationStatus.INSUFFICIENT_EVIDENCE


def test_malformed_static_analysis_check_list_cannot_verify() -> None:
    checks = complete_checks()
    next(item for item in checks if item.name == "static_analysis").details["checks_completed"] = (
        True
    )
    assert decide(checks).status is VerificationStatus.INSUFFICIENT_EVIDENCE


def test_analysis_only_mode_is_never_verified() -> None:
    result = evaluate_policy(complete_checks(), execution_mode=ExecutionMode.ANALYSIS_ONLY)
    assert result.status is VerificationStatus.INSUFFICIENT_EVIDENCE


def test_conflicting_duplicate_evidence_is_insufficient() -> None:
    checks = complete_checks()
    pre_check = next(item for item in checks if item.name == "pre_patch_reproduction")
    checks.append(pre_check.model_copy(deep=True, update={"details": {"reproduced": False}}))
    assert decide(checks).status is VerificationStatus.INSUFFICIENT_EVIDENCE


def test_not_reproduced_has_limited_semantics() -> None:
    check = CheckResult(
        name="pre_patch_reproduction",
        category=EvidenceCategory.ISSUE_REPRODUCTION,
        status=CheckStatus.PASSED,
        message="Reproduction conditions completed.",
        details={
            "reproduced": False,
            "conditions_recorded": True,
            "conditions_id": "recorded-case",
        },
    )
    result = decide([check])
    assert result.status is VerificationStatus.NOT_REPRODUCED
    assert "does not prove" in result.reasons[0]


def test_public_status_serialization_and_policy_version_are_stable() -> None:
    assert [item.value for item in VerificationStatus] == [
        "VERIFIED",
        "NOT_REPRODUCED",
        "INSUFFICIENT_EVIDENCE",
    ]
    assert POLICY_VERSION == "1.0.1"
    assert VerificationStatus.VERIFIED.value == "VERIFIED"
