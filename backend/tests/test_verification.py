from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import proofgate.api.main as api_main
from proofgate.api.main import create_app


def client_for(root: Path | None = None) -> TestClient:
    return TestClient(create_app(root))


def test_service_root_endpoint() -> None:
    response = client_for().get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "ProofGate AI"
    assert response.json()["version"] == "0.1.0"


def test_health_endpoint_is_minimal() -> None:
    response = client_for().get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_version_endpoint_lists_routes() -> None:
    response = client_for().get("/api/v1")
    assert response.status_code == 200
    assert set(response.json()["endpoints"]) == {"analyze", "verify", "github_inspect"}


def test_valid_analysis_request_is_read_only_and_relative(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text("answer = 42\n", encoding="utf-8")
    response = client_for(tmp_path).post(
        "/api/v1/analyze",
        json={"repository_path": ".", "max_files": 10},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["python_file_count"] == 1
    assert result["files"][0]["path"] == "sample.py"
    assert str(tmp_path) not in response.text


def test_malformed_verification_request_returns_safe_validation_error() -> None:
    response = client_for().post("/api/v1/verify", json={"bug_description": "tiny"})
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"
    assert response.json()["fields"]
    assert all(response.json()["fields"])
    assert "input" not in response.text


def test_verify_exact_request_reports_model_level_conflict_clearly() -> None:
    response = client_for().post(
        "/api/v1/verify",
        json={
            "bug_description": (
                "A function should return zero for an empty list, "
                "but this behavior has not been verified."
            ),
            "repository_path": ".",
            "source_code": "def calculate_total(items):\n    return sum(items)\n",
            "unified_diff": None,
            "reproduction_test_path": None,
            "execution_mode": "analysis_only",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"
    assert response.json()["fields"] == ["request"]
    assert response.json()["message"] == "Request validation failed."
    assert "C:" not in response.text


def test_verify_rejects_source_and_repository_path_together() -> None:
    response = client_for().post(
        "/api/v1/verify",
        json={
            "bug_description": "A concise report about a code behavior.",
            "repository_path": ".",
            "source_code": "value = 1\n",
        },
    )

    assert response.status_code == 422
    assert response.json()["fields"] == ["request"]
    assert "Request validation failed." == response.json()["message"]


def test_verify_repository_path_must_identify_python_file_not_directory(
    tmp_path: Path,
) -> None:
    (tmp_path / "module.py").write_text("value = 1\n", encoding="utf-8")
    response = client_for(tmp_path).post(
        "/api/v1/verify",
        json={
            "bug_description": "A concise report about a code behavior.",
            "repository_path": ".",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_path"
    assert str(tmp_path) not in response.text


def test_unexpected_verification_failure_returns_sanitized_error(
    monkeypatch,
) -> None:
    def raise_internal_error(*_args, **_kwargs):
        raise RuntimeError("internal path C:\\private\\secret.py")

    monkeypatch.setattr(api_main, "run_verification", raise_internal_error)
    response = TestClient(create_app(), raise_server_exceptions=False).post(
        "/api/v1/verify",
        json={
            "bug_description": "A concise report about a code behavior.",
            "source_code": "value = 1\n",
        },
    )

    assert response.status_code == 500
    assert response.json()["error"] == "internal_error"
    assert response.json()["message"] == "The request could not be completed."
    assert "private" not in response.text
    assert "secret.py" not in response.text


def test_invalid_repository_path_returns_client_error_without_host_path(tmp_path: Path) -> None:
    response = client_for(tmp_path).post(
        "/api/v1/analyze",
        json={"repository_path": "../secret.py"},
    )
    assert response.status_code == 400
    assert str(tmp_path) not in response.text
    assert "secret.py" not in response.text


def test_analysis_only_verification_reports_insufficient_evidence() -> None:
    response = client_for().post(
        "/api/v1/verify",
        json={
            "bug_description": "A boundary input is rejected unexpectedly",
            "source_code": "def check(value):\n    return value >= 0\n",
            "unified_diff": (
                "--- a/check.py\n+++ b/check.py\n@@ -1 +1 @@\n"
                "-return value > 0\n+return value >= 0\n"
            ),
            "execution_mode": "analysis_only",
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["decision"] == "INSUFFICIENT_EVIDENCE"
    assert result["policy_version"] == "1.0.1"
    assert {"pre_patch_reproduction", "post_patch_reproduction", "regression_tests"} <= set(
        result["checks_skipped"]
    )


def test_behavioral_rule_reports_potential_addition_subtraction_mismatch(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "must-not-be-created.txt"
    source = (
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed')\n"
        "def add(a, b):\n"
        "    return a - b\n"
    )
    response = client_for().post(
        "/api/v1/verify",
        json={
            "bug_description": "The add(a, b) function should add its two arguments.",
            "source_code": source,
        },
    )

    assert response.status_code == 200
    result = response.json()
    finding = result["behavioral_findings"][0]
    assert result["decision"] == "INSUFFICIENT_EVIDENCE"
    assert finding == {
        "finding_type": "POTENTIAL_BEHAVIOR_MISMATCH",
        "rule_id": "PG-PY-ADD-SUB-001",
        "function_name": "add",
        "detected_operator": "subtraction",
        "expected_operator": "addition",
        "source_line": 4,
        "message": (
            "This narrow static rule found an operator mismatch; runtime behavior is not verified."
        ),
    }
    evidence = next(
        item
        for item in result["evidence"]
        if item["details"].get("finding_type") == "POTENTIAL_BEHAVIOR_MISMATCH"
    )
    assert evidence["outcome"] == "inconclusive"
    assert evidence["details"]["function_name"] == "add"
    assert evidence["details"]["detected_operator"] == "subtraction"
    assert evidence["details"]["expected_operator"] == "addition"
    assert evidence["details"]["rule_id"] == "PG-PY-ADD-SUB-001"
    assert not marker.exists()


def test_behavioral_rule_accepts_matching_addition() -> None:
    response = client_for().post(
        "/api/v1/verify",
        json={
            "bug_description": "The add(a, b) function should add its two arguments.",
            "source_code": "def add(a, b):\n    return a + b\n",
        },
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "INSUFFICIENT_EVIDENCE"
    assert response.json()["behavioral_findings"][0]["finding_type"] == "NO_MISMATCH_DETECTED"


def test_behavioral_rule_reports_ambiguous_requirement_as_unsupported() -> None:
    response = client_for().post(
        "/api/v1/verify",
        json={
            "bug_description": (
                "The add(a, b) function should add its two arguments and "
                "should subtract its two arguments."
            ),
            "source_code": "def add(a, b):\n    return a - b\n",
        },
    )

    assert response.status_code == 200
    finding = response.json()["behavioral_findings"][0]
    assert finding["finding_type"] == "UNSUPPORTED_REQUIREMENT"
    assert finding["function_name"] is None
    assert response.json()["decision"] == "INSUFFICIENT_EVIDENCE"


def test_behavioral_rule_marks_unsupported_return_expression() -> None:
    response = client_for().post(
        "/api/v1/verify",
        json={
            "bug_description": "The add(a, b) function should add its two arguments.",
            "source_code": "def add(a, b):\n    return a * b\n",
        },
    )

    assert response.status_code == 200
    assert response.json()["behavioral_findings"][0]["finding_type"] == "UNSUPPORTED_EXPRESSION"
    assert response.json()["decision"] == "INSUFFICIENT_EVIDENCE"


def test_behavioral_rule_reports_invalid_syntax() -> None:
    response = client_for().post(
        "/api/v1/verify",
        json={
            "bug_description": "The add(a, b) function should add its two arguments.",
            "source_code": "def add(a, b):\n    return a -\n",
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["checks"][0]["status"] == "failed"
    assert result["behavioral_findings"][0]["finding_type"] == "INVALID_SYNTAX"
    assert result["decision"] == "INSUFFICIENT_EVIDENCE"


def test_behavioral_rule_does_not_match_a_differently_named_function() -> None:
    response = client_for().post(
        "/api/v1/verify",
        json={
            "bug_description": "The add(a, b) function should add its two arguments.",
            "source_code": "def sum_values(a, b):\n    return a - b\n",
        },
    )

    assert response.status_code == 200
    finding = response.json()["behavioral_findings"][0]
    assert finding["finding_type"] == "UNSUPPORTED_REQUIREMENT"
    assert finding["function_name"] is None
    assert finding["detected_operator"] is None
    assert response.json()["decision"] == "INSUFFICIENT_EVIDENCE"


def test_behavioral_rule_detects_inverse_mismatch_when_subtraction_is_explicit() -> None:
    response = client_for().post(
        "/api/v1/verify",
        json={
            "bug_description": "The subtract(a, b) function should subtract its two arguments.",
            "source_code": "def subtract(a, b):\n    return a + b\n",
        },
    )

    assert response.status_code == 200
    finding = response.json()["behavioral_findings"][0]
    assert finding["finding_type"] == "POTENTIAL_BEHAVIOR_MISMATCH"
    assert finding["detected_operator"] == "addition"
    assert finding["expected_operator"] == "subtraction"
    assert response.json()["decision"] == "INSUFFICIENT_EVIDENCE"


def test_behavioral_rule_uses_safely_read_repository_source(tmp_path: Path) -> None:
    (tmp_path / "add.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    response = TestClient(create_app(tmp_path)).post(
        "/api/v1/verify",
        json={
            "bug_description": "The add(a, b) function should add its two arguments.",
            "repository_path": "add.py",
        },
    )

    assert response.status_code == 200
    finding = response.json()["behavioral_findings"][0]
    assert finding["finding_type"] == "POTENTIAL_BEHAVIOR_MISMATCH"
    assert response.json()["decision"] == "INSUFFICIENT_EVIDENCE"


def test_api_rejects_synthetic_policy_checks_as_verification_input() -> None:
    response = client_for().post(
        "/api/v1/verify",
        json={
            "bug_description": "A reported behavior needs investigation",
            "source_code": "value = 1\n",
            "execution_mode": "isolated_sandbox",
            "checks": [
                {
                    "name": "pre_patch_reproduction",
                    "category": "issue_reproduction",
                    "status": "passed",
                    "message": "Synthetic benchmark evidence",
                }
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["fields"] == ["checks"]


def test_untrusted_source_and_reproduction_test_are_never_executed(tmp_path: Path) -> None:
    marker = tmp_path / "host-executed.txt"
    source = f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
    response = client_for().post(
        "/api/v1/verify",
        json={
            "bug_description": "A reported behavior needs investigation",
            "source_code": source,
            "reproduction_test_path": "tests/test_untrusted.py",
        },
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "INSUFFICIENT_EVIDENCE"
    assert not marker.exists()
    assert str(tmp_path) not in response.text


def test_invalid_test_path_is_rejected() -> None:
    response = client_for().post(
        "/api/v1/verify",
        json={
            "bug_description": "A reported behavior needs investigation",
            "source_code": "value = 1\n",
            "reproduction_test_path": "outside/test_bad.py",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_test_path"


def test_analysis_requires_a_configured_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROOFGATE_REPOSITORY_ROOT", raising=False)
    response = client_for().post("/api/v1/analyze", json={"repository_path": "."})
    assert response.status_code == 503
    assert response.json()["error"] == "root_not_configured"


def test_analysis_loads_server_configured_root_from_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_directory = tmp_path / "src" / "proofgate"
    source_directory.mkdir(parents=True)
    (source_directory / "sample.py").write_text("answer = 42\n", encoding="utf-8")
    monkeypatch.setenv("PROOFGATE_REPOSITORY_ROOT", str(tmp_path))

    response = TestClient(create_app()).post(
        "/api/v1/analyze",
        json={"repository_path": "src/proofgate", "max_files": 5},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["file_count"] == 1
    assert result["python_file_count"] == 1
    assert result["files"][0]["path"] == "src/proofgate/sample.py"
    assert result["files"][0]["syntax_valid"] is True
    assert str(tmp_path) not in response.text


def test_analysis_reports_missing_path_inside_configured_root(tmp_path: Path) -> None:
    response = client_for(tmp_path).post(
        "/api/v1/analyze",
        json={"repository_path": "missing/path", "max_files": 5},
    )

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


def test_analysis_rejects_path_escaping_configured_root(tmp_path: Path) -> None:
    response = client_for(tmp_path).post(
        "/api/v1/analyze",
        json={"repository_path": "..", "max_files": 5},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_path"


def test_analysis_reports_invalid_server_configured_root(
    tmp_path: Path,
) -> None:
    missing_root = tmp_path / "missing-root"
    response = client_for(missing_root).post(
        "/api/v1/analyze",
        json={"repository_path": ".", "max_files": 5},
    )

    assert response.status_code == 503
    assert response.json()["error"] == "invalid_root"


def test_verification_response_schema_is_consistent() -> None:
    response = client_for().post(
        "/api/v1/verify",
        json={
            "bug_description": "The submitted example has a boundary condition",
            "source_code": "def check(n):\n    return n >= 0\n",
        },
    )
    body = response.json()
    assert response.status_code == 200
    assert (
        set(
            [
                "verification_id",
                "decision",
                "summary",
                "evidence",
                "behavioral_findings",
                "checks",
                "checks_performed",
                "checks_skipped",
                "reasons",
                "duration_ms",
                "policy_version",
            ]
        )
        <= body.keys()
    )
    assert all("evidence_id" in item and "timestamp" in item for item in body["evidence"])


def test_request_body_limit_is_enforced() -> None:
    response = client_for().post(
        "/api/v1/verify",
        content=b"x" * (512_001),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["error"] == "request_too_large"
