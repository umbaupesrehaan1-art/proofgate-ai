from __future__ import annotations

import base64
from typing import Any

import pytest
from fastapi.testclient import TestClient

import proofgate.github as github
from proofgate.api.main import create_app
from proofgate.github import GitHubIntegrationError, parse_repository_url
from proofgate.models import GitHubInspectionRequest


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/owner/repository",
        "https://example.com/owner/repository",
        "https://user@github.com/owner/repository",
        "https://github.com/owner/repository?redirect=https://example.com",
        "https://github.com/owner/repository/issues/1",
        "https://github.com/owner%2frepository/name",
        "https://github.com/owner/..",
    ],
)
def test_repository_url_rejects_untrusted_or_non_repository_urls(url: str) -> None:
    with pytest.raises(GitHubIntegrationError, match="GitHub|HTTPS"):
        parse_repository_url(url)


def test_repository_url_accepts_public_repository_url_with_git_suffix() -> None:
    assert parse_repository_url("https://github.com/proofgate/demo.git") == (
        "proofgate",
        "demo",
    )


def test_api_rejects_invalid_github_input_without_fetching() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/github/inspect",
        json={"repository_url": "https://example.com/owner/repository"},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_github_repository"


def test_api_enforces_github_file_limit() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/github/inspect",
        json={
            "repository_url": "https://github.com/owner/repository",
            "max_files": 21,
        },
    )
    assert response.status_code == 422
    assert response.json()["fields"] == ["max_files"]


def test_github_response_size_limit_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        headers = {"Content-Length": str(github.MAX_API_RESPONSE_BYTES + 1)}

        def geturl(self) -> str:
            return "https://api.github.com/repos/owner/repository"

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

    class FakeOpener:
        def open(self, *_args: Any, **_kwargs: Any) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(github.urllib.request, "build_opener", lambda *_args: FakeOpener())
    with pytest.raises(GitHubIntegrationError, match="size limit") as error:
        github._GitHubClient().get_json("/repos/owner/repository")
    assert error.value.code == "github_response_too_large"


def test_truncated_repository_listing_is_reported_as_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = b"value = 1\n"

    class FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        def get_json(self, endpoint: str, **_kwargs: Any) -> Any:
            if endpoint == "/repos/owner/repository":
                return {
                    "private": False,
                    "full_name": "owner/repository",
                    "default_branch": "main",
                }
            if endpoint.endswith("/commits/main"):
                return {"sha": "c" * 40, "commit": {"tree": {"sha": "d" * 40}}}
            if endpoint.endswith("/git/trees/" + "d" * 40 + "?recursive=1"):
                return {
                    "truncated": True,
                    "tree": [
                        {
                            "type": "blob",
                            "path": "src/module.py",
                            "size": len(source),
                            "sha": "a" * 40,
                        }
                    ],
                }
            if endpoint.endswith("/git/blobs/" + "a" * 40):
                return {
                    "encoding": "base64",
                    "content": base64.b64encode(source).decode("ascii"),
                    "size": len(source),
                }
            raise AssertionError(f"Unexpected GitHub API path: {endpoint}")

    monkeypatch.setattr(github, "_GitHubClient", FakeClient)
    result = github.inspect_github(
        GitHubInspectionRequest(repository_url="https://github.com/owner/repository")
    )

    assert result.coverage_complete is False
    assert "truncated" in result.coverage_messages[0]
    assert result.repository.revision == "c" * 40
    assert result.files[0].analysis is not None
    assert result.files[0].analysis.syntax_valid is True
    assert result.decision.value == "INSUFFICIENT_EVIDENCE"
    assert {record.category.value for record in result.evidence} == {"static_analysis"}


def test_pull_request_accepts_copied_status_and_parses_python_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = b"value = 2\n"

    class FakeClient:
        def get_json(self, endpoint: str, **_kwargs: Any) -> Any:
            if endpoint == "/repos/owner/repository":
                return {
                    "private": False,
                    "full_name": "owner/repository",
                    "default_branch": "main",
                }
            if endpoint.endswith("/pulls/4"):
                return {
                    "number": 4,
                    "title": "Copy file",
                    "state": "open",
                    "changed_files": 1,
                    "base": {"ref": "main", "sha": "d" * 40},
                    "head": {"ref": "change", "sha": "e" * 40},
                }
            if endpoint.endswith("/pulls/4/files?per_page=21"):
                return [
                    {
                        "filename": "src/module.py",
                        "status": "copied",
                        "additions": 1,
                        "deletions": 0,
                        "patch": "@@ -0,0 +1 @@\n+value = 2",
                        "sha": "b" * 40,
                        "size": len(source),
                    }
                ]
            if endpoint.endswith("/git/blobs/" + "b" * 40):
                return {
                    "encoding": "base64",
                    "content": base64.b64encode(source).decode("ascii"),
                    "size": len(source),
                }
            raise AssertionError(f"Unexpected GitHub API path: {endpoint}")

    monkeypatch.setattr(github, "_GitHubClient", FakeClient)
    result = github.inspect_github(
        GitHubInspectionRequest(
            repository_url="https://github.com/owner/repository",
            pull_request_number=4,
        )
    )

    assert result.files[0].change_status == "copied"
    assert result.files[0].analysis is not None
    assert result.files[0].analysis.syntax_valid is True
    assert result.coverage_complete is True


def test_pull_request_diff_and_python_source_are_inspected_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = b"value = 2\n"

    class FakeClient:
        def get_json(self, endpoint: str, **_kwargs: Any) -> Any:
            if endpoint == "/repos/owner/repository":
                return {
                    "private": False,
                    "full_name": "owner/repository",
                    "default_branch": "main",
                }
            if endpoint.endswith("/pulls/4"):
                return {
                    "number": 4,
                    "title": "Update value",
                    "state": "open",
                    "changed_files": 1,
                    "base": {"ref": "main", "sha": "d" * 40},
                    "head": {"ref": "change", "sha": "e" * 40},
                }
            if endpoint.endswith("/pulls/4/files?per_page=21"):
                return [
                    {
                        "filename": "src/module.py",
                        "status": "modified",
                        "additions": 1,
                        "deletions": 1,
                        "patch": "@@ -1 +1 @@\n-value = 1\n+value = 2",
                        "sha": "b" * 40,
                    }
                ]
            if endpoint.endswith("/git/blobs/" + "b" * 40):
                return {
                    "encoding": "base64",
                    "content": base64.b64encode(source).decode("ascii"),
                    "size": len(source),
                }
            raise AssertionError(f"Unexpected GitHub API path: {endpoint}")

    monkeypatch.setattr(github, "_GitHubClient", FakeClient)
    response = TestClient(create_app()).post(
        "/api/v1/github/inspect",
        json={
            "repository_url": "https://github.com/owner/repository",
            "pull_request_number": 4,
        },
    )
    assert response.status_code == 200
    result = response.json()

    assert result["coverage_complete"] is True
    assert result["pull_request"]["number"] == 4
    assert result["pull_request"]["head_sha"] == "e" * 40
    assert result["files"][0]["diff_valid"] is True
    assert result["files"][0]["patch_status"] == "available"
    assert result["files"][0]["file_type"] == "python"
    assert [
        (line["diff_line"], line["kind"], line["old_line"], line["new_line"])
        for line in result["files"][0]["diff_lines"]
    ] == [(2, "deletion", 1, None), (3, "addition", None, 1)]
    assert result["files"][0]["analysis"]["syntax_valid"] is True
    assert result["decision"] == "INSUFFICIENT_EVIDENCE"
    assert result["policy_version"] == "1.0.1"
    assert {record["category"] for record in result["evidence"]} == {
        "static_analysis",
        "patch_validation",
    }
    static_evidence = next(
        record for record in result["evidence"] if record["category"] == "static_analysis"
    )
    assert static_evidence["details"]["path"] == "src/module.py"
    assert static_evidence["details"]["finding_category"] == "python_syntax"
    assert static_evidence["details"]["diagnostics"] == []


def test_pull_request_reports_missing_truncated_and_unsupported_diffs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = b"value = 2\n"
    pr_data = {
        "number": 4,
        "title": "Review coverage",
        "state": "open",
        "changed_files": 5,
        "base": {"ref": "main", "sha": "d" * 40},
        "head": {"ref": "change", "sha": "e" * 40},
    }

    class FakeClient:
        def get_json(self, endpoint: str, **_kwargs: Any) -> Any:
            if endpoint == "/repos/owner/repository":
                return {
                    "private": False,
                    "full_name": "owner/repository",
                    "default_branch": "main",
                }
            if endpoint.endswith("/pulls/4"):
                return pr_data
            if endpoint.endswith("/pulls/4/files?per_page=21"):
                return [
                    {
                        "filename": "src/module.py",
                        "status": "modified",
                        "additions": 1,
                        "deletions": 1,
                        "size": len(source),
                        "patch": "@@ -1,2 +1,2 @@\n-value = 1\n+value = 2",
                        "sha": "b" * 40,
                    },
                    {
                        "filename": "README.md",
                        "status": "modified",
                        "additions": 1,
                        "deletions": 1,
                        "size": 10,
                        "patch": "@@ -1 +1 @@\n-old text\n+new text",
                        "sha": "c" * 40,
                    },
                    {
                        "filename": "assets/diagram.png",
                        "status": "added",
                        "additions": 0,
                        "deletions": 0,
                        "size": 100,
                    },
                    {
                        "filename": "docs/generated.txt",
                        "status": "modified",
                        "additions": 1,
                        "deletions": 1,
                        "size": 1,
                        "patch": "x" * (github.MAX_PATCH_BYTES + 1),
                    },
                    {
                        "filename": "legacy/removed.py",
                        "status": "removed",
                        "additions": 0,
                        "deletions": 1,
                        "size": 0,
                        "patch": "@@ -1 +0,0 @@\n-value = 0",
                    },
                ]
            if endpoint.endswith("/git/blobs/" + "b" * 40):
                return {
                    "encoding": "base64",
                    "content": base64.b64encode(source).decode("ascii"),
                    "size": len(source),
                }
            raise AssertionError(f"Unexpected GitHub API path: {endpoint}")

    monkeypatch.setattr(github, "_GitHubClient", FakeClient)
    result = github.inspect_github(
        GitHubInspectionRequest(
            repository_url="https://github.com/owner/repository",
            pull_request_number=4,
        )
    )
    by_path = {item.path: item for item in result.files}

    assert by_path["src/module.py"].patch_status == "incomplete"
    assert by_path["src/module.py"].diff_valid is False
    assert by_path["src/module.py"].diff_lines == []
    assert by_path["README.md"].file_type == "unsupported"
    assert by_path["README.md"].patch_status == "available"
    assert by_path["README.md"].status == "skipped"
    assert by_path["assets/diagram.png"].file_type == "unsupported"
    assert by_path["assets/diagram.png"].patch_status == "missing"
    assert by_path["docs/generated.txt"].file_type == "unsupported"
    assert by_path["docs/generated.txt"].patch_status == "oversized"
    assert "does not identify which" in " ".join(result.coverage_messages)
    assert by_path["legacy/removed.py"].change_status == "removed"
    assert by_path["legacy/removed.py"].patch_status == "available"
    assert by_path["legacy/removed.py"].status == "skipped"
    assert result.coverage_complete is False
    assert result.decision.value == "INSUFFICIENT_EVIDENCE"
    assert result.policy_version == "1.0.1"


def test_invalid_pull_request_patch_is_a_failed_patch_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pr_data = {
        "number": 4,
        "title": "Malformed diff",
        "state": "open",
        "changed_files": 1,
        "base": {"ref": "main", "sha": "d" * 40},
        "head": {"ref": "change", "sha": "e" * 40},
    }

    class FakeClient:
        def get_json(self, endpoint: str, **_kwargs: Any) -> Any:
            if endpoint == "/repos/owner/repository":
                return {
                    "private": False,
                    "full_name": "owner/repository",
                    "default_branch": "main",
                }
            if endpoint.endswith("/pulls/4"):
                return pr_data
            if endpoint.endswith("/pulls/4/files?per_page=21"):
                return [
                    {
                        "filename": "src/module.py",
                        "status": "modified",
                        "additions": 1,
                        "deletions": 1,
                        "size": 0,
                        "patch": "not a patch",
                    }
                ]
            raise AssertionError(f"Unexpected GitHub API path: {endpoint}")

    monkeypatch.setattr(github, "_GitHubClient", FakeClient)
    result = github.inspect_github(
        GitHubInspectionRequest(
            repository_url="https://github.com/owner/repository",
            pull_request_number=4,
        )
    )

    assert result.files[0].patch_status == "invalid"
    assert result.files[0].diff_diagnostics
    patch_evidence = next(
        record for record in result.evidence if record.category.value == "patch_validation"
    )
    assert patch_evidence.outcome.value == "fail"
    assert patch_evidence.details["diagnostics"]
    assert result.decision.value == "INSUFFICIENT_EVIDENCE"


def test_patch_with_valid_hunks_but_inconsistent_file_counts_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pr_data = {
        "number": 4,
        "title": "Incomplete patch",
        "state": "open",
        "changed_files": 1,
        "base": {"ref": "main", "sha": "d" * 40},
        "head": {"ref": "change", "sha": "e" * 40},
    }

    class FakeClient:
        def get_json(self, endpoint: str, **_kwargs: Any) -> Any:
            if endpoint == "/repos/owner/repository":
                return {
                    "private": False,
                    "full_name": "owner/repository",
                    "default_branch": "main",
                }
            if endpoint.endswith("/pulls/4"):
                return pr_data
            if endpoint.endswith("/pulls/4/files?per_page=21"):
                return [
                    {
                        "filename": "src/module.py",
                        "status": "modified",
                        "additions": 2,
                        "deletions": 1,
                        "size": 0,
                        "patch": "@@ -1 +1 @@\n-old\n+new",
                    }
                ]
            raise AssertionError(f"Unexpected GitHub API path: {endpoint}")

    monkeypatch.setattr(github, "_GitHubClient", FakeClient)
    result = github.inspect_github(
        GitHubInspectionRequest(
            repository_url="https://github.com/owner/repository",
            pull_request_number=4,
        )
    )

    assert result.files[0].diff_valid is True
    assert result.files[0].patch_status == "incomplete"
    assert "line counts do not match" in result.files[0].diff_diagnostics[0]
    assert result.coverage_complete is False
    patch_evidence = next(
        record for record in result.evidence if record.category.value == "patch_validation"
    )
    assert patch_evidence.outcome.value == "inconclusive"
    assert result.decision.value == "INSUFFICIENT_EVIDENCE"


def test_syntax_finding_keeps_file_and_exact_source_line_in_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = b"def broken(:\n"
    pr_data = {
        "number": 4,
        "title": "Syntax regression",
        "state": "open",
        "changed_files": 1,
        "base": {"ref": "main", "sha": "d" * 40},
        "head": {"ref": "change", "sha": "e" * 40},
    }

    class FakeClient:
        def get_json(self, endpoint: str, **_kwargs: Any) -> Any:
            if endpoint == "/repos/owner/repository":
                return {
                    "private": False,
                    "full_name": "owner/repository",
                    "default_branch": "main",
                }
            if endpoint.endswith("/pulls/4"):
                return pr_data
            if endpoint.endswith("/pulls/4/files?per_page=21"):
                return [
                    {
                        "filename": "src/broken.py",
                        "status": "modified",
                        "additions": 1,
                        "deletions": 1,
                        "size": len(source),
                        "patch": "@@ -1 +1 @@\n-def broken():\n+def broken(:",
                        "sha": "b" * 40,
                    }
                ]
            if endpoint.endswith("/git/blobs/" + "b" * 40):
                return {
                    "encoding": "base64",
                    "content": base64.b64encode(source).decode("ascii"),
                    "size": len(source),
                }
            raise AssertionError(f"Unexpected GitHub API path: {endpoint}")

    monkeypatch.setattr(github, "_GitHubClient", FakeClient)
    result = github.inspect_github(
        GitHubInspectionRequest(
            repository_url="https://github.com/owner/repository",
            pull_request_number=4,
        )
    )
    analysis = result.files[0].analysis
    assert analysis is not None
    assert analysis.path == "src/broken.py"
    assert analysis.diagnostics[0].line == 1

    evidence = next(
        record for record in result.evidence if record.category.value == "static_analysis"
    )
    assert evidence.details["path"] == "src/broken.py"
    assert evidence.details["diagnostics"][0]["line"] == 1
    assert evidence.details["diagnostics"][0]["column"] is not None
    assert result.decision.value == "INSUFFICIENT_EVIDENCE"


def test_diff_line_record_limit_marks_github_coverage_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pr_data = {
        "number": 4,
        "title": "Large patch",
        "state": "open",
        "changed_files": 1,
        "base": {"ref": "main", "sha": "d" * 40},
        "head": {"ref": "change", "sha": "e" * 40},
    }
    patch = "@@ -0,0 +1,2501 @@\n" + "+value\n" * 2_501

    class FakeClient:
        def get_json(self, endpoint: str, **_kwargs: Any) -> Any:
            if endpoint == "/repos/owner/repository":
                return {
                    "private": False,
                    "full_name": "owner/repository",
                    "default_branch": "main",
                }
            if endpoint.endswith("/pulls/4"):
                return pr_data
            if endpoint.endswith("/pulls/4/files?per_page=21"):
                return [
                    {
                        "filename": "docs/change.txt",
                        "status": "added",
                        "additions": 2_501,
                        "deletions": 0,
                        "size": len(patch.encode("utf-8")),
                        "patch": patch,
                    }
                ]
            raise AssertionError(f"Unexpected GitHub API path: {endpoint}")

    monkeypatch.setattr(github, "_GitHubClient", FakeClient)
    result = github.inspect_github(
        GitHubInspectionRequest(
            repository_url="https://github.com/owner/repository",
            pull_request_number=4,
        )
    )

    file_result = result.files[0]
    assert file_result.patch_status == "available"
    assert len(file_result.diff_lines) == 2_500
    assert file_result.diff_lines_truncated is True
    assert file_result.diff_lines[0].new_line == 1
    assert file_result.diff_lines[-1].new_line == 2_500
    assert result.coverage_complete is False
    assert any("structured diff locations were capped" in item for item in result.coverage_messages)
