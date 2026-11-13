import json
from io import StringIO
from pathlib import Path

import pytest

from proofgate.benchmark import (
    BenchmarkFixtureError,
    load_cases,
    run_benchmark,
)
from proofgate.models import VerificationStatus


def test_default_benchmark_fixtures_are_valid_and_deterministic() -> None:
    cases = load_cases()

    assert len(cases) == 18
    assert cases[0].case_id == "complete_consistent_evidence"
    assert cases[0].expected_decision is VerificationStatus.VERIFIED
    assert cases[1].execution_mode.value == "analysis_only"
    assert cases[-1].case_id == "potential_behavior_mismatch_without_runtime_evidence"
    assert cases[-1].expected_decision is VerificationStatus.INSUFFICIENT_EVIDENCE


def test_benchmark_reports_all_cases_and_is_reproducible() -> None:
    first_output = StringIO()
    second_output = StringIO()

    assert run_benchmark(output=first_output) == 0
    assert run_benchmark(output=second_output) == 0
    first_lines = first_output.getvalue().splitlines()
    second_lines = second_output.getvalue().splitlines()

    assert first_lines == second_lines
    assert first_lines[-1] == "Cases: 18; Passed: 18; Failed: 0; Pass rate: 100.00%"
    assert all(line.startswith("PASS ") for line in first_lines[:-1])


def test_case_mismatch_is_reported_and_returns_nonzero(
    tmp_path: Path,
) -> None:
    fixture_path = tmp_path / "case.json"
    fixture_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "base_checks": [],
                "cases": [
                    {
                        "id": "expected-mismatch",
                        "description": "An intentionally incorrect expectation.",
                        "execution_mode": "analysis_only",
                        "expected_decision": "VERIFIED",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    output = StringIO()

    assert run_benchmark(fixture_path, output=output) == 1
    lines = output.getvalue().splitlines()
    assert lines[0] == ("FAIL expected-mismatch: expected VERIFIED, actual INSUFFICIENT_EVIDENCE")
    assert lines[-1] == "Cases: 1; Passed: 0; Failed: 1; Pass rate: 0.00%"


def test_missing_fixture_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(BenchmarkFixtureError, match="Cannot read benchmark fixtures"):
        load_cases(tmp_path / "missing.json")


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("not json", "not valid UTF-8 JSON"),
        (
            json.dumps(
                {
                    "schema_version": 1,
                    "base_checks": [{}],
                    "cases": [
                        {
                            "id": "bad-check",
                            "description": "Malformed check model.",
                            "execution_mode": "analysis_only",
                            "expected_decision": "INSUFFICIENT_EVIDENCE",
                        }
                    ],
                }
            ),
            "invalid check",
        ),
        (
            json.dumps(
                {
                    "schema_version": 1,
                    "base_checks": [],
                    "cases": [
                        {
                            "id": "unknown-decision",
                            "description": "Invalid expected decision.",
                            "execution_mode": "analysis_only",
                            "expected_decision": "UNKNOWN",
                        }
                    ],
                }
            ),
            "invalid decision or mode",
        ),
    ],
)
def test_malformed_fixtures_are_rejected(tmp_path: Path, contents: str, message: str) -> None:
    fixture_path = tmp_path / "malformed.json"
    fixture_path.write_text(contents, encoding="utf-8")

    with pytest.raises(BenchmarkFixtureError, match=message):
        load_cases(fixture_path)
