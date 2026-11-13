"""Offline benchmark runner for deterministic policy decision fixtures."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from pydantic import ValidationError

from proofgate.models import CheckResult, ExecutionMode, VerificationStatus
from proofgate.policy import evaluate_policy

DEFAULT_FIXTURES = (
    Path(__file__).resolve().parents[3] / "benchmark" / "fixtures" / "policy_cases.json"
)
_TOP_LEVEL_KEYS = {"schema_version", "base_checks", "cases"}
_REQUIRED_CASE_KEYS = {"id", "description", "execution_mode", "expected_decision"}
_OPTIONAL_CASE_KEYS = {"include_checks", "omit_checks", "check_overrides"}
_OVERRIDE_KEYS = {"category", "status", "message", "required", "details", "duration_ms"}


class BenchmarkFixtureError(ValueError):
    """A benchmark fixture file is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    description: str
    execution_mode: ExecutionMode
    expected_decision: VerificationStatus
    checks: tuple[CheckResult, ...]


@dataclass(frozen=True)
class CaseResult:
    case: BenchmarkCase
    actual_decision: VerificationStatus

    @property
    def passed(self) -> bool:
        return self.case.expected_decision is self.actual_decision


def _validated_checks(raw_checks: object, *, context: str) -> list[CheckResult]:
    if not isinstance(raw_checks, list):
        raise BenchmarkFixtureError(f"{context} must be a list.")
    try:
        return [CheckResult.model_validate(item) for item in raw_checks]
    except (ValidationError, TypeError) as exc:
        raise BenchmarkFixtureError(f"{context} contains an invalid check: {exc}") from exc


def _case_checks(
    raw_case: dict[str, object], base_checks: list[CheckResult], *, case_id: str
) -> tuple[CheckResult, ...]:
    base_by_name = {check.name: check for check in base_checks}
    if len(base_by_name) != len(base_checks):
        raise BenchmarkFixtureError("base_checks must not contain duplicate check names.")

    include = raw_case.get("include_checks")
    omit = raw_case.get("omit_checks")
    if include is not None and omit is not None:
        raise BenchmarkFixtureError(f"Case {case_id!r} cannot include and omit checks together.")

    if include is not None:
        if not isinstance(include, list) or not all(isinstance(name, str) for name in include):
            raise BenchmarkFixtureError(f"Case {case_id!r} include_checks must be a list of names.")
        if len(include) != len(set(include)) or any(name not in base_by_name for name in include):
            raise BenchmarkFixtureError(f"Case {case_id!r} includes duplicate or unknown checks.")
        selected = [base_by_name[name] for name in include]
    else:
        if omit is not None:
            if not isinstance(omit, list) or not all(isinstance(name, str) for name in omit):
                raise BenchmarkFixtureError(
                    f"Case {case_id!r} omit_checks must be a list of names."
                )
            if len(omit) != len(set(omit)) or any(name not in base_by_name for name in omit):
                raise BenchmarkFixtureError(f"Case {case_id!r} omits duplicate or unknown checks.")
        omitted = set(omit or [])
        selected = [check for check in base_checks if check.name not in omitted]

    overrides = raw_case.get("check_overrides", {})
    if not isinstance(overrides, dict):
        raise BenchmarkFixtureError(f"Case {case_id!r} check_overrides must be an object.")
    selected_by_name = {check.name: check for check in selected}
    for name, changes in overrides.items():
        if name not in selected_by_name or not isinstance(changes, dict):
            raise BenchmarkFixtureError(f"Case {case_id!r} has an invalid check override.")
        if set(changes) - _OVERRIDE_KEYS:
            raise BenchmarkFixtureError(f"Case {case_id!r} has unsupported override fields.")

        values = selected_by_name[name].model_dump(mode="python")
        for key, value in changes.items():
            if key == "details":
                if not isinstance(value, dict):
                    raise BenchmarkFixtureError(
                        f"Case {case_id!r} override details must be an object."
                    )
                values[key] = {**values[key], **value}
            else:
                values[key] = value
        try:
            selected_by_name[name] = CheckResult.model_validate(values)
        except ValidationError as exc:
            raise BenchmarkFixtureError(
                f"Case {case_id!r} has an invalid override for {name!r}: {exc}"
            ) from exc

    return tuple(selected_by_name[check.name] for check in selected)


def load_cases(path: Path = DEFAULT_FIXTURES) -> tuple[BenchmarkCase, ...]:
    """Load and strictly validate deterministic JSON policy cases."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BenchmarkFixtureError(f"Cannot read benchmark fixtures: {exc.strerror}.") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BenchmarkFixtureError(f"Benchmark fixtures are not valid UTF-8 JSON: {exc}") from exc

    if not isinstance(raw, dict) or set(raw) != _TOP_LEVEL_KEYS:
        raise BenchmarkFixtureError(
            "Fixture document must contain exactly schema_version, base_checks, and cases."
        )
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise BenchmarkFixtureError("Unsupported benchmark fixture schema_version.")

    base_checks = _validated_checks(raw["base_checks"], context="base_checks")
    raw_cases = raw["cases"]
    if not isinstance(raw_cases, list) or not raw_cases:
        raise BenchmarkFixtureError("cases must be a non-empty list.")

    cases: list[BenchmarkCase] = []
    seen_ids: set[str] = set()
    for index, raw_case in enumerate(raw_cases):
        if not isinstance(raw_case, dict):
            raise BenchmarkFixtureError(f"Case at index {index} must be an object.")
        keys = set(raw_case)
        if not _REQUIRED_CASE_KEYS <= keys or keys - _REQUIRED_CASE_KEYS - _OPTIONAL_CASE_KEYS:
            raise BenchmarkFixtureError(f"Case at index {index} has missing or unknown fields.")

        case_id = raw_case["id"]
        description = raw_case["description"]
        if not isinstance(case_id, str) or not case_id.strip() or len(case_id) > 100:
            raise BenchmarkFixtureError(f"Case at index {index} has an invalid id.")
        if case_id in seen_ids:
            raise BenchmarkFixtureError(f"Duplicate benchmark case id: {case_id!r}.")
        if not isinstance(description, str) or not description.strip():
            raise BenchmarkFixtureError(f"Case {case_id!r} has an invalid description.")
        seen_ids.add(case_id)

        try:
            mode = ExecutionMode(raw_case["execution_mode"])
            expected = VerificationStatus(raw_case["expected_decision"])
        except (ValueError, TypeError) as exc:
            raise BenchmarkFixtureError(
                f"Case {case_id!r} has an invalid decision or mode."
            ) from exc

        cases.append(
            BenchmarkCase(
                case_id=case_id,
                description=description,
                execution_mode=mode,
                expected_decision=expected,
                checks=_case_checks(raw_case, base_checks, case_id=case_id),
            )
        )
    return tuple(cases)


def evaluate_cases(cases: tuple[BenchmarkCase, ...]) -> tuple[CaseResult, ...]:
    """Evaluate fixture checks through the production policy implementation."""
    return tuple(
        CaseResult(
            case=case,
            actual_decision=evaluate_policy(
                list(case.checks), execution_mode=case.execution_mode
            ).status,
        )
        for case in cases
    )


def run_benchmark(
    fixtures_path: Path = DEFAULT_FIXTURES,
    *,
    output: TextIO | None = None,
) -> int:
    """Print a deterministic case report and return an appropriate process status."""
    stream = output if output is not None else sys.stdout
    try:
        results = evaluate_cases(load_cases(fixtures_path))
    except BenchmarkFixtureError as exc:
        print(f"Benchmark fixture error: {exc}", file=stream)
        return 2

    for result in results:
        label = "PASS" if result.passed else "FAIL"
        print(
            f"{label} {result.case.case_id}: expected "
            f"{result.case.expected_decision.value}, actual {result.actual_decision.value}",
            file=stream,
        )

    passed = sum(result.passed for result in results)
    failed = len(results) - passed
    pass_rate = passed / len(results) * 100
    print(
        f"Cases: {len(results)}; Passed: {passed}; Failed: {failed}; Pass rate: {pass_rate:.2f}%",
        file=stream,
    )
    return 0 if failed == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the offline ProofGate policy benchmark.")
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=DEFAULT_FIXTURES,
        help="Path to a benchmark fixture JSON file.",
    )
    args = parser.parse_args(argv)
    return run_benchmark(args.fixtures)


if __name__ == "__main__":
    raise SystemExit(main())
