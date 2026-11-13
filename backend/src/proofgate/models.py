"""Typed domain models shared by analysis, policy, and the HTTP API."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class VerificationStatus(StrEnum):
    """Stable public decisions returned by the verification API."""

    VERIFIED = "VERIFIED"
    NOT_REPRODUCED = "NOT_REPRODUCED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class EvidenceCategory(StrEnum):
    ISSUE_REPRODUCTION = "issue_reproduction"
    PATCH_VALIDATION = "patch_validation"
    SYNTAX_CHECKING = "syntax_checking"
    STATIC_ANALYSIS = "static_analysis"
    REGRESSION_TESTING = "regression_testing"
    EXECUTION_SAFETY = "execution_safety"


class EvidenceOutcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


class CheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    INCONCLUSIVE = "inconclusive"


class ExecutionMode(StrEnum):
    ANALYSIS_ONLY = "analysis_only"
    ISOLATED_SANDBOX = "isolated_sandbox"


class PublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EvidenceRecord(PublicModel):
    evidence_id: str = Field(pattern=r"^ev_[0-9a-f]{32}$")
    category: EvidenceCategory
    outcome: EvidenceOutcome
    message: str = Field(min_length=1, max_length=500)
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    duration_ms: int | None = Field(default=None, ge=0, le=86_400_000)

    @field_validator("timestamp")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(UTC)


class CheckResult(PublicModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    category: EvidenceCategory
    status: CheckStatus
    message: str = Field(min_length=1, max_length=500)
    required: bool = True
    details: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int | None = Field(default=None, ge=0, le=86_400_000)


class SyntaxDiagnostic(PublicModel):
    line: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1)
    message: str = Field(min_length=1, max_length=300)


class AnalysisFileResult(PublicModel):
    path: str = Field(min_length=1, max_length=500)
    syntax_valid: bool | None = None
    diagnostics: list[SyntaxDiagnostic] = Field(default_factory=list)
    size_bytes: int | None = Field(default=None, ge=0)
    status: str = Field(pattern=r"^(analyzed|skipped|error)$")


class BehavioralFinding(PublicModel):
    finding_type: Literal[
        "POTENTIAL_BEHAVIOR_MISMATCH",
        "NO_MISMATCH_DETECTED",
        "UNSUPPORTED_REQUIREMENT",
        "UNSUPPORTED_EXPRESSION",
        "INVALID_SYNTAX",
    ]
    rule_id: str = Field(min_length=1, max_length=80)
    function_name: str | None = Field(default=None, max_length=200)
    detected_operator: Literal["addition", "subtraction"] | None = None
    expected_operator: Literal["addition", "subtraction"] | None = None
    source_line: int | None = Field(default=None, ge=1)
    message: str = Field(min_length=1, max_length=500)


class AnalysisSummary(PublicModel):
    root_path: str = Field(default=".", max_length=500)
    file_count: int = Field(ge=0)
    python_file_count: int = Field(ge=0)
    syntax_error_count: int = Field(ge=0)
    analyzed_paths: list[str] = Field(default_factory=list, max_length=500)
    files: list[AnalysisFileResult] = Field(default_factory=list, max_length=500)
    truncated: bool = False


class DiffLine(PublicModel):
    diff_line: int = Field(ge=1)
    kind: Literal["context", "addition", "deletion"]
    old_line: int | None = Field(default=None, ge=1)
    new_line: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_matching_line_numbers(self) -> DiffLine:
        if self.kind == "context" and (self.old_line is None or self.new_line is None):
            raise ValueError("context diff lines require both source line numbers")
        if self.kind == "addition" and (self.old_line is not None or self.new_line is None):
            raise ValueError("added diff lines require only a new source line number")
        if self.kind == "deletion" and (self.old_line is None or self.new_line is not None):
            raise ValueError("deleted diff lines require only an old source line number")
        return self


class DiffSummary(PublicModel):
    valid: bool
    added_paths: list[str] = Field(default_factory=list, max_length=100)
    removed_paths: list[str] = Field(default_factory=list, max_length=100)
    changed_paths: list[str] = Field(default_factory=list, max_length=100)
    diagnostics: list[str] = Field(default_factory=list, max_length=20)
    diff_lines: list[DiffLine] = Field(default_factory=list, max_length=2_500)
    diff_lines_truncated: bool = False
    added_line_count: int = Field(default=0, ge=0)
    deleted_line_count: int = Field(default=0, ge=0)
    incomplete: bool = False


class AnalysisRequest(PublicModel):
    repository_path: str = Field(default=".", min_length=1, max_length=500)
    max_files: int = Field(default=100, ge=1, le=500)


class GitHubInspectionRequest(PublicModel):
    repository_url: str = Field(min_length=1, max_length=500)
    pull_request_number: int | None = Field(default=None, ge=1, strict=True)
    max_files: int = Field(default=20, ge=1, le=20, strict=True)


class GitHubRepositoryInfo(PublicModel):
    full_name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=500)
    default_branch: str = Field(min_length=1, max_length=200)
    revision: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{40}$")


class GitHubPullRequestInfo(PublicModel):
    number: int = Field(ge=1)
    title: str = Field(max_length=500)
    state: str = Field(min_length=1, max_length=40)
    url: str = Field(min_length=1, max_length=500)
    base_branch: str = Field(min_length=1, max_length=200)
    head_branch: str = Field(min_length=1, max_length=200)
    base_sha: str = Field(pattern=r"^[0-9a-fA-F]{40}$")
    head_sha: str = Field(pattern=r"^[0-9a-fA-F]{40}$")
    changed_file_count: int = Field(ge=0)


class GitHubFileAnalysis(PublicModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    path: str = Field(min_length=1, max_length=500)
    change_status: str = Field(min_length=1, max_length=40)
    additions: int = Field(ge=0)
    deletions: int = Field(ge=0)
    patch: str | None = Field(default=None, max_length=20_000)
    diff_valid: bool | None = None
    patch_status: Literal[
        "not_applicable", "available", "missing", "oversized", "incomplete", "invalid"
    ] = "not_applicable"
    file_type: Literal["python", "unsupported", "unknown"] = "unknown"
    diff_lines: list[DiffLine] = Field(default_factory=list, max_length=2_500)
    diff_lines_truncated: bool = False
    diff_diagnostics: list[str] = Field(default_factory=list, max_length=20)
    analysis: AnalysisFileResult | None = None
    status: str = Field(pattern=r"^(analyzed|skipped|error)$")
    message: str = Field(min_length=1, max_length=500)


class GitHubInspectionResult(PublicModel):
    repository: GitHubRepositoryInfo
    pull_request: GitHubPullRequestInfo | None = None
    files: list[GitHubFileAnalysis] = Field(default_factory=list, max_length=20)
    evidence: list[EvidenceRecord] = Field(default_factory=list, max_length=100)
    coverage_complete: bool
    coverage_messages: list[str] = Field(default_factory=list, max_length=50)
    decision: VerificationStatus
    decision_reasons: list[str] = Field(default_factory=list, max_length=20)
    policy_version: str = Field(min_length=1, max_length=40)


class VerificationRequest(PublicModel):
    bug_description: str = Field(min_length=5, max_length=1_000)
    repository_path: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
        description="Repository-relative Python file path; provide instead of source_code.",
    )
    source_code: str | None = Field(
        default=None,
        max_length=100_000,
        description="Controlled Python source text; provide instead of repository_path.",
    )
    unified_diff: str | None = Field(default=None, max_length=200_000)
    reproduction_test_path: str | None = Field(default=None, min_length=1, max_length=500)
    execution_mode: ExecutionMode = ExecutionMode.ANALYSIS_ONLY

    @field_validator("repository_path", "reproduction_test_path")
    @classmethod
    def reject_obvious_unsafe_paths(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.replace("\\", "/")
        if (
            "\x00" in value
            or normalized.startswith("/")
            or normalized.startswith("//")
            or (len(normalized) >= 2 and normalized[1] == ":")
            or any(part == ".." for part in normalized.split("/"))
        ):
            raise ValueError("path must be a safe repository-relative path")
        return value

    @model_validator(mode="after")
    def require_analyzable_input(self) -> VerificationRequest:
        if self.repository_path is None and self.source_code is None:
            raise ValueError("provide repository_path or source_code")
        if self.source_code is not None and self.repository_path is not None:
            raise ValueError("provide only one of repository_path or source_code")
        return self


class VerificationResult(PublicModel):
    verification_id: str = Field(pattern=r"^vg_[0-9a-f]{32}$")
    decision: VerificationStatus
    summary: str = Field(min_length=1, max_length=1_000)
    evidence: list[EvidenceRecord] = Field(default_factory=list, max_length=100)
    behavioral_findings: list[BehavioralFinding] = Field(default_factory=list, max_length=20)
    checks: list[CheckResult] = Field(default_factory=list, max_length=100)
    checks_performed: list[str] = Field(default_factory=list, max_length=100)
    checks_skipped: dict[str, str] = Field(default_factory=dict, max_length=100)
    reasons: list[str] = Field(default_factory=list, max_length=50)
    duration_ms: int = Field(ge=0, le=86_400_000)
    policy_version: str = Field(min_length=1, max_length=40)


class ErrorResponse(PublicModel):
    error: str
    message: str
    request_id: str | None = None
