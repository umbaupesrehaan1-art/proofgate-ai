"""Safe verification orchestration, intentionally separate from HTTP routing."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from proofgate.analyzer import (
    AnalyzerError,
    analyze_behavioral_requirement,
    analyze_python_source,
    analyze_repository,
    inspect_unified_diff,
    read_repository_source,
    validate_relative_path,
)
from proofgate.evidence import create_evidence, elapsed_ms, evidence_from_check, start_timer
from proofgate.models import (
    AnalysisSummary,
    BehavioralFinding,
    CheckResult,
    CheckStatus,
    EvidenceCategory,
    EvidenceOutcome,
    EvidenceRecord,
    ExecutionMode,
    VerificationRequest,
    VerificationResult,
)
from proofgate.policy import POLICY_VERSION, evaluate_policy


def _test_path_is_permitted(path: str) -> None:
    parts = validate_relative_path(path, allow_dot=False)
    if len(parts) < 2 or parts[0].casefold() != "tests":
        raise AnalyzerError(
            "invalid_test_path",
            "A reproduction test path must be inside the repository tests directory.",
        )


def _make_check(
    name: str,
    category: EvidenceCategory,
    status: CheckStatus,
    message: str,
    *,
    details: dict[str, object] | None = None,
) -> CheckResult:
    return CheckResult(
        name=name,
        category=category,
        status=status,
        message=message,
        details=details or {},
    )


def run_verification(
    request: VerificationRequest,
    *,
    repository_root: Path | None = None,
) -> VerificationResult:
    """Collect safe static evidence and explicitly skip execution-dependent checks.

    This initial runner never imports, launches, or runs submitted repository code.
    The isolated-sandbox mode is an extension point only and is not implemented.
    """
    started = start_timer()
    checks: list[CheckResult] = []
    static_result = None
    source_available = False
    source_syntax_valid: bool | None = None
    source_text: str | None = None

    if request.reproduction_test_path is not None:
        _test_path_is_permitted(request.reproduction_test_path)

    if request.source_code is not None:
        source_available = True
        source_text = request.source_code
        source_result = analyze_python_source(source_text, path="<submitted-source.py>")
        source_syntax_valid = source_result.syntax_valid
        static_result = source_result
    elif request.repository_path is not None:
        if repository_root is None:
            raise AnalyzerError(
                "root_not_configured", "A permitted repository root is not configured."
            )
        relative_path, source_text = read_repository_source(
            repository_root, request.repository_path
        )
        static_result = analyze_python_source(source_text, path=relative_path)
        source_available = True
        source_syntax_valid = static_result.syntax_valid

    behavioral_findings: list[BehavioralFinding] = []
    behavioral_evidence: list[EvidenceRecord] = []
    if source_available and source_text is not None:
        finding = analyze_behavioral_requirement(
            request.bug_description,
            source_text,
            path=static_result.path if static_result is not None else "<submitted-source.py>",
        )
        behavioral_findings.append(finding)
        behavioral_evidence.append(
            create_evidence(
                EvidenceCategory.STATIC_ANALYSIS,
                EvidenceOutcome.INCONCLUSIVE,
                finding.message,
                details=finding.model_dump(mode="json"),
            )
        )

    if source_available and source_syntax_valid is not None:
        syntax_status = CheckStatus.PASSED if source_syntax_valid else CheckStatus.FAILED
        checks.append(
            _make_check(
                "syntax_check",
                EvidenceCategory.SYNTAX_CHECKING,
                syntax_status,
                "Submitted source parses successfully."
                if source_syntax_valid
                else "Submitted source has syntax errors.",
                details={"syntax_valid": source_syntax_valid},
            )
        )
        checks.append(
            _make_check(
                "static_analysis",
                EvidenceCategory.STATIC_ANALYSIS,
                syntax_status,
                "Safe AST syntax analysis completed."
                if source_syntax_valid
                else "AST analysis found invalid syntax.",
                details={
                    "analysis": "python_ast_parse",
                    "checks_completed": ["python_ast_parse", "behavioral_add_sub_rule"],
                },
            )
        )
    else:
        checks.extend(
            [
                _make_check(
                    "syntax_check",
                    EvidenceCategory.SYNTAX_CHECKING,
                    CheckStatus.SKIPPED,
                    "Patched Python source was not available for safe syntax analysis.",
                ),
                _make_check(
                    "static_analysis",
                    EvidenceCategory.STATIC_ANALYSIS,
                    CheckStatus.SKIPPED,
                    "No readable Python source was available for static analysis.",
                ),
            ]
        )

    if request.unified_diff is None:
        checks.append(
            _make_check(
                "patch_validation",
                EvidenceCategory.PATCH_VALIDATION,
                CheckStatus.SKIPPED,
                "No unified diff was supplied for patch validation.",
            )
        )
    else:
        diff_result = inspect_unified_diff(request.unified_diff)
        checks.append(
            _make_check(
                "patch_validation",
                EvidenceCategory.PATCH_VALIDATION,
                CheckStatus.PASSED
                if diff_result.valid and diff_result.changed_paths
                else CheckStatus.FAILED,
                "Unified diff structure is valid."
                if diff_result.valid
                else "Unified diff is malformed.",
                details={
                    "valid": diff_result.valid,
                    "changed_paths": diff_result.changed_paths,
                    "added_paths": diff_result.added_paths,
                    "removed_paths": diff_result.removed_paths,
                },
            )
        )

    execution_mode_supported = request.execution_mode is ExecutionMode.ANALYSIS_ONLY
    if execution_mode_supported:
        skip_reason = "Not executed: this milestone does not run untrusted repository code."
    else:
        skip_reason = (
            "Isolated sandbox execution is not implemented; no submitted code was executed."
        )
    for name, category in (
        ("pre_patch_reproduction", EvidenceCategory.ISSUE_REPRODUCTION),
        ("post_patch_reproduction", EvidenceCategory.ISSUE_REPRODUCTION),
        ("regression_tests", EvidenceCategory.REGRESSION_TESTING),
    ):
        checks.append(_make_check(name, category, CheckStatus.SKIPPED, skip_reason))
    checks.append(
        _make_check(
            "execution_safety",
            EvidenceCategory.EXECUTION_SAFETY,
            CheckStatus.PASSED if execution_mode_supported else CheckStatus.SKIPPED,
            "No submitted code was executed by the analysis-only runner."
            if execution_mode_supported
            else skip_reason,
            details={"untrusted_code_executed": False},
        )
    )

    decision = evaluate_policy(checks, execution_mode=request.execution_mode)
    skipped = {item.name: item.message for item in checks if item.status is CheckStatus.SKIPPED}
    performed = [
        item.name for item in checks if item.status in (CheckStatus.PASSED, CheckStatus.FAILED)
    ]
    return VerificationResult(
        verification_id=f"vg_{uuid4().hex}",
        decision=decision.status,
        summary=(
            "Static analysis completed; verification evidence is insufficient to claim a fix."
            if decision.status.value == "INSUFFICIENT_EVIDENCE"
            else decision.reasons[0]
        ),
        evidence=[evidence_from_check(item) for item in checks] + behavioral_evidence,
        behavioral_findings=behavioral_findings,
        checks=checks,
        checks_performed=performed,
        checks_skipped=skipped,
        reasons=list(decision.reasons),
        duration_ms=elapsed_ms(started),
        policy_version=POLICY_VERSION,
    )


def analyze_request(
    repository_root: Path,
    repository_path: str,
    *,
    max_files: int = 100,
) -> AnalysisSummary:
    """Thin business-logic entry point used by the API analysis endpoint."""
    return analyze_repository(repository_root, repository_path, max_files=max_files)
