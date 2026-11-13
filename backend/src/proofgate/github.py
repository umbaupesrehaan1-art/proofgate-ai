"""Bounded, read-only retrieval and static inspection of public GitHub content."""

from __future__ import annotations

import base64
import binascii
import http.client
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from proofgate.analyzer import (
    AnalyzerError,
    analyze_python_source,
    inspect_unified_diff,
    validate_relative_path,
)
from proofgate.evidence import create_evidence
from proofgate.models import (
    AnalysisFileResult,
    DiffLine,
    EvidenceCategory,
    EvidenceOutcome,
    ExecutionMode,
    GitHubFileAnalysis,
    GitHubInspectionRequest,
    GitHubInspectionResult,
    GitHubPullRequestInfo,
    GitHubRepositoryInfo,
)
from proofgate.policy import POLICY_VERSION, evaluate_policy

GITHUB_API = "https://api.github.com"
MAX_API_RESPONSE_BYTES = 1_000_000
MAX_SOURCE_FILE_BYTES = 100_000
MAX_TOTAL_SOURCE_BYTES = 1_000_000
MAX_PATCH_BYTES = 20_000
MAX_TOTAL_DIFF_LINE_RECORDS = 2_500
MAX_INSPECTION_SECONDS = 20
REQUEST_TIMEOUT_SECONDS = 5
_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
_GIT_SHA = re.compile(r"^[0-9a-fA-F]{40}$")


class GitHubIntegrationError(ValueError):
    """A safe client-visible error while retrieving public GitHub data."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def parse_repository_url(repository_url: str) -> tuple[str, str]:
    """Accept only a canonical public github.com repository URL."""
    try:
        parsed = urllib.parse.urlsplit(repository_url)
        port = parsed.port
    except ValueError as exc:
        raise GitHubIntegrationError(
            "invalid_github_repository", "Enter a valid public GitHub repository URL.", 422
        ) from exc

    repository_path = parsed.path[1:] if parsed.path.startswith("/") else ""
    if repository_path.endswith("/"):
        repository_path = repository_path[:-1]
    parts = repository_path.split("/")
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.hostname.casefold() != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or "%" in parsed.path
        or parsed.path.startswith("//")
        or "//" in parsed.path
        or len(parts) != 2
    ):
        raise GitHubIntegrationError(
            "invalid_github_repository",
            "Use an HTTPS URL in the form https://github.com/owner/repository.",
            422,
        )

    owner, repository = parts
    if repository.endswith(".git"):
        repository = repository[:-4]
    if (
        not _OWNER.fullmatch(owner)
        or not _REPOSITORY.fullmatch(repository)
        or repository in (".", "..")
    ):
        raise GitHubIntegrationError(
            "invalid_github_repository",
            "The GitHub owner or repository name is not valid.",
            422,
        )
    return owner, repository


class _GitHubClient:
    def __init__(self) -> None:
        self.deadline = time.monotonic() + MAX_INSPECTION_SECONDS
        self.opener = urllib.request.build_opener(_NoRedirect())

    def get_json(self, endpoint: str, *, max_bytes: int = MAX_API_RESPONSE_BYTES) -> Any:
        if not endpoint.startswith("/") or endpoint.startswith("//"):
            raise ValueError("GitHub API endpoint must be a fixed relative path.")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise GitHubIntegrationError(
                "github_timeout", "GitHub retrieval exceeded the time limit.", 504
            )
        request = urllib.request.Request(
            f"{GITHUB_API}{endpoint}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "ProofGate-AI-read-only-inspector",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method="GET",
        )
        try:
            with self.opener.open(
                request, timeout=min(REQUEST_TIMEOUT_SECONDS, remaining)
            ) as response:
                if urllib.parse.urlsplit(response.geturl()).netloc.casefold() != "api.github.com":
                    raise GitHubIntegrationError(
                        "github_redirect_rejected",
                        "GitHub redirected the request outside the approved API host.",
                        502,
                    )
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        declared_length = int(content_length)
                    except ValueError as exc:
                        raise GitHubIntegrationError(
                            "github_invalid_response",
                            "GitHub returned an invalid response length.",
                            502,
                        ) from exc
                    if declared_length > max_bytes:
                        raise GitHubIntegrationError(
                            "github_response_too_large",
                            "A GitHub response exceeded the configured size limit.",
                            502,
                        )
                body = response.read(max_bytes + 1)
        except urllib.error.HTTPError as exc:
            rate_limit_remaining = (
                exc.headers.get("X-RateLimit-Remaining") if exc.headers is not None else None
            )
            if exc.code in (403, 429) and rate_limit_remaining == "0":
                raise GitHubIntegrationError(
                    "github_rate_limited",
                    "GitHub's unauthenticated API rate limit was reached.",
                    429,
                ) from exc
            if exc.code == 404:
                raise GitHubIntegrationError(
                    "github_not_found",
                    "The repository or pull request was not found or is not publicly accessible.",
                    404,
                ) from exc
            if exc.code in (403, 429):
                raise GitHubIntegrationError(
                    "github_rate_limited", "GitHub rejected the public API request.", 429
                ) from exc
            if 300 <= exc.code < 400:
                raise GitHubIntegrationError(
                    "github_redirect_rejected", "GitHub API redirects are not followed.", 502
                ) from exc
            raise GitHubIntegrationError(
                "github_unavailable", f"GitHub returned HTTP {exc.code}.", 502
            ) from exc
        except http.client.HTTPException as exc:
            raise GitHubIntegrationError(
                "github_incomplete_response", "GitHub returned an incomplete API response.", 502
            ) from exc
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            raise GitHubIntegrationError(
                "github_unavailable", "GitHub could not be reached within the time limit.", 502
            ) from exc

        if len(body) > max_bytes:
            raise GitHubIntegrationError(
                "github_response_too_large",
                "A GitHub response exceeded the configured size limit.",
                502,
            )
        try:
            return json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise GitHubIntegrationError(
                "github_invalid_response", "GitHub returned malformed JSON.", 502
            ) from exc


def _required_string(data: dict[str, Any], key: str, max_length: int = 500) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise GitHubIntegrationError(
            "github_invalid_response", "GitHub returned malformed repository metadata.", 502
        )
    try:
        if any(ord(char) < 32 for char in value):
            raise UnicodeError
        value.encode("utf-8")
    except UnicodeError as exc:
        raise GitHubIntegrationError(
            "github_invalid_response", "GitHub returned invalid text metadata.", 502
        ) from exc
    return value


def _required_sha(value: Any) -> str:
    if not isinstance(value, str) or not _GIT_SHA.fullmatch(value):
        raise GitHubIntegrationError(
            "github_invalid_response", "GitHub returned an invalid commit identifier.", 502
        )
    return value


def _repository_metadata(
    client: _GitHubClient, owner: str, repository: str
) -> GitHubRepositoryInfo:
    data = client.get_json(f"/repos/{owner}/{repository}")
    if not isinstance(data, dict) or data.get("private") is True:
        raise GitHubIntegrationError(
            "github_not_found",
            "The repository was not found or is not publicly accessible.",
            404,
        )
    full_name = _required_string(data, "full_name", 200)
    default_branch = _required_string(data, "default_branch", 200)
    if full_name.casefold() != f"{owner}/{repository}".casefold():
        raise GitHubIntegrationError(
            "github_invalid_response", "GitHub returned mismatched repository metadata.", 502
        )
    return GitHubRepositoryInfo(
        full_name=full_name,
        url=f"https://github.com/{owner}/{repository}",
        default_branch=default_branch,
    )


def _decode_blob(client: _GitHubClient, owner: str, repository: str, sha: str) -> str:
    if not _GIT_SHA.fullmatch(sha):
        raise GitHubIntegrationError(
            "github_invalid_response", "GitHub returned an invalid file object identifier.", 502
        )
    response = client.get_json(
        f"/repos/{owner}/{repository}/git/blobs/{sha}",
        max_bytes=MAX_SOURCE_FILE_BYTES * 2,
    )
    if (
        not isinstance(response, dict)
        or response.get("encoding") != "base64"
        or not isinstance(response.get("content"), str)
        or type(response.get("size")) is not int
    ):
        raise GitHubIntegrationError(
            "github_invalid_response", "GitHub returned an unsupported file response.", 502
        )
    encoded = response["content"]
    try:
        content = base64.b64decode("".join(encoded.split()), validate=True)
        source = content.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise GitHubIntegrationError(
            "github_invalid_response", "A GitHub Python file was not valid UTF-8 text.", 502
        ) from exc
    if len(content) > MAX_SOURCE_FILE_BYTES:
        raise GitHubIntegrationError(
            "github_file_too_large", "A Python file exceeded the configured size limit.", 413
        )
    if len(content) != response["size"]:
        raise GitHubIntegrationError(
            "github_invalid_response", "GitHub returned inconsistent file content.", 502
        )
    return source


def _file_path(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 500
        or "\\" in value
        or any(ord(char) < 32 for char in value)
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise AnalyzerError("invalid_path", "GitHub returned an invalid file path.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise AnalyzerError("invalid_path", "GitHub returned an invalid file path.") from exc
    validate_relative_path(value, allow_dot=False)
    return value


def _analyze_blob(
    client: _GitHubClient,
    owner: str,
    repository: str,
    path: str,
    sha: Any,
    *,
    expected_size: int | None,
    source_bytes_so_far: int,
) -> tuple[AnalysisFileResult, int]:
    if not isinstance(sha, str) or not _GIT_SHA.fullmatch(sha):
        raise GitHubIntegrationError(
            "github_invalid_response", "GitHub returned an invalid file object identifier.", 502
        )
    if expected_size is not None and source_bytes_so_far + expected_size > MAX_TOTAL_SOURCE_BYTES:
        raise GitHubIntegrationError(
            "github_total_size_limit", "The total retrieved source exceeded the size limit.", 413
        )
    source = _decode_blob(client, owner, repository, sha)
    source_size = len(source.encode("utf-8"))
    if expected_size is not None and source_size != expected_size:
        raise GitHubIntegrationError(
            "github_invalid_response", "GitHub returned inconsistent file size metadata.", 502
        )
    if source_bytes_so_far + source_size > MAX_TOTAL_SOURCE_BYTES:
        raise GitHubIntegrationError(
            "github_total_size_limit", "The total retrieved source exceeded the size limit.", 413
        )
    return analyze_python_source(source, path=path), source_size


def _analysis_file(
    path: str,
    *,
    change_status: str,
    additions: int = 0,
    deletions: int = 0,
    patch: str | None = None,
    diff_valid: bool | None = None,
    patch_status: str = "not_applicable",
    diff_lines: list[DiffLine] | None = None,
    diff_lines_truncated: bool = False,
    diff_diagnostics: list[str] | None = None,
    analysis: AnalysisFileResult | None = None,
    status: str,
    message: str,
) -> GitHubFileAnalysis:
    return GitHubFileAnalysis(
        path=path,
        change_status=change_status,
        additions=additions,
        deletions=deletions,
        patch=patch,
        diff_valid=diff_valid,
        patch_status=patch_status,
        file_type=(
            "unknown"
            if path == "<invalid GitHub path>"
            else "python"
            if path.casefold().endswith(".py")
            else "unsupported"
        ),
        diff_lines=diff_lines or [],
        diff_lines_truncated=diff_lines_truncated,
        diff_diagnostics=diff_diagnostics or [],
        analysis=analysis,
        status=status,
        message=message,
    )


def inspect_github(request: GitHubInspectionRequest) -> GitHubInspectionResult:
    """Fetch public GitHub metadata and bounded Python source/diff data for static analysis."""
    owner, repository = parse_repository_url(request.repository_url)
    client = _GitHubClient()
    repository_info = _repository_metadata(client, owner, repository)
    coverage_messages: list[str] = []
    files: list[GitHubFileAnalysis] = []
    source_bytes = 0
    pull_info: GitHubPullRequestInfo | None = None

    if request.pull_request_number is None:
        branch = urllib.parse.quote(repository_info.default_branch, safe="")
        commit_data = client.get_json(f"/repos/{owner}/{repository}/commits/{branch}")
        if not isinstance(commit_data, dict) or not isinstance(commit_data.get("commit"), dict):
            raise GitHubIntegrationError(
                "github_invalid_response", "GitHub returned malformed branch commit data.", 502
            )
        repository_info.revision = _required_sha(commit_data.get("sha"))
        commit_tree = commit_data["commit"].get("tree")
        if not isinstance(commit_tree, dict):
            raise GitHubIntegrationError(
                "github_invalid_response", "GitHub returned incomplete branch tree data.", 502
            )
        tree_sha = _required_sha(commit_tree.get("sha"))
        tree = client.get_json(f"/repos/{owner}/{repository}/git/trees/{tree_sha}?recursive=1")
        if not isinstance(tree, dict) or not isinstance(tree.get("tree"), list):
            raise GitHubIntegrationError(
                "github_invalid_response", "GitHub returned malformed repository file data.", 502
            )
        entries = [
            entry
            for entry in tree["tree"]
            if isinstance(entry, dict)
            and entry.get("type") == "blob"
            and isinstance(entry.get("path"), str)
            and entry["path"].casefold().endswith(".py")
        ]
        entries.sort(key=lambda entry: entry["path"].casefold())
        if any(
            not isinstance(entry, dict)
            or not isinstance(entry.get("path"), str)
            or entry.get("type") not in ("blob", "tree", "commit")
            for entry in tree["tree"]
        ):
            coverage_messages.append("GitHub returned malformed repository file entries.")
        if not isinstance(tree.get("truncated"), bool):
            coverage_messages.append("GitHub returned an invalid file-list completeness flag.")
        elif tree["truncated"]:
            coverage_messages.append("GitHub truncated the repository file listing.")
        if len(entries) > request.max_files:
            coverage_messages.append(
                f"Only the first {request.max_files} of {len(entries)} Python files were inspected."
            )
        seen_paths: set[str] = set()
        for entry in entries[: request.max_files]:
            try:
                path = _file_path(entry["path"])
                if path in seen_paths:
                    coverage_messages.append("GitHub returned duplicate repository file paths.")
                    continue
                seen_paths.add(path)
                file_size = entry.get("size")
                if type(file_size) is not int or file_size < 0:
                    files.append(
                        _analysis_file(
                            path,
                            change_status="unchanged",
                            status="error",
                            message="GitHub returned malformed file size metadata.",
                        )
                    )
                    coverage_messages.append(f"{path}: file size metadata was malformed.")
                    continue
                if file_size > MAX_SOURCE_FILE_BYTES:
                    files.append(
                        _analysis_file(
                            path,
                            change_status="unchanged",
                            status="skipped",
                            message="Python file exceeded the configured size limit.",
                        )
                    )
                    coverage_messages.append(f"{path}: file size limit exceeded.")
                    continue
                analysis, used = _analyze_blob(
                    client,
                    owner,
                    repository,
                    path,
                    entry.get("sha"),
                    expected_size=file_size,
                    source_bytes_so_far=source_bytes,
                )
                source_bytes += used
                files.append(
                    _analysis_file(
                        path,
                        change_status="unchanged",
                        analysis=analysis,
                        status="analyzed",
                        message="Python source was parsed without execution.",
                    )
                )
            except (AnalyzerError, GitHubIntegrationError) as exc:
                files.append(
                    _analysis_file(
                        "<invalid GitHub path>",
                        change_status="unchanged",
                        status="error",
                        message=exc.message,
                    )
                )
                coverage_messages.append(f"A Python file could not be completely inspected: {exc}.")
    else:
        pr_data = client.get_json(
            f"/repos/{owner}/{repository}/pulls/{request.pull_request_number}"
        )
        if not isinstance(pr_data, dict):
            raise GitHubIntegrationError(
                "github_invalid_response", "GitHub returned malformed pull request metadata.", 502
            )
        base = pr_data.get("base")
        head = pr_data.get("head")
        if not isinstance(base, dict) or not isinstance(head, dict):
            raise GitHubIntegrationError(
                "github_invalid_response", "GitHub returned incomplete pull request metadata.", 502
            )
        changed_count = pr_data.get("changed_files")
        number = pr_data.get("number")
        if (
            type(changed_count) is not int
            or changed_count < 0
            or type(number) is not int
            or number != request.pull_request_number
        ):
            raise GitHubIntegrationError(
                "github_invalid_response",
                "GitHub returned inconsistent pull request metadata.",
                502,
            )
        pull_info = GitHubPullRequestInfo(
            number=number,
            title=_required_string(pr_data, "title", 500),
            state=_required_string(pr_data, "state", 40),
            url=f"https://github.com/{owner}/{repository}/pull/{number}",
            base_branch=_required_string(base, "ref", 200),
            head_branch=_required_string(head, "ref", 200),
            base_sha=_required_sha(base.get("sha")),
            head_sha=_required_sha(head.get("sha")),
            changed_file_count=changed_count,
        )
        if changed_count > request.max_files:
            coverage_messages.append(
                f"Only {request.max_files} of {changed_count} changed files can be "
                "inspected per request."
            )
        changed = client.get_json(
            f"/repos/{owner}/{repository}/pulls/{number}/files?per_page={request.max_files + 1}"
        )
        if not isinstance(changed, list):
            raise GitHubIntegrationError(
                "github_invalid_response", "GitHub returned malformed pull request file data.", 502
            )
        if len(changed) > request.max_files:
            coverage_messages.append(
                "GitHub returned more files than the requested inspection limit."
            )
        elif len(changed) < min(changed_count, request.max_files):
            coverage_messages.append(
                "GitHub returned fewer changed files than repository metadata reports."
            )
        patch_bytes = 0
        diff_line_records_used = 0
        seen_paths = set()
        for entry in changed[: request.max_files]:
            if not isinstance(entry, dict):
                coverage_messages.append("A changed-file record was malformed.")
                continue
            raw_path = entry.get("filename")
            try:
                path = _file_path(raw_path)
            except AnalyzerError:
                coverage_messages.append("A changed file had an unsafe or invalid path.")
                continue
            if path in seen_paths:
                coverage_messages.append("GitHub returned duplicate changed-file paths.")
                continue
            seen_paths.add(path)
            change_status = entry.get("status")
            valid_change_statuses = {
                "added",
                "removed",
                "modified",
                "renamed",
                "copied",
                "changed",
                "deleted",
            }
            if (
                not isinstance(change_status, str)
                or len(change_status) > 40
                or change_status not in valid_change_statuses
            ):
                coverage_messages.append(f"{path}: change status was malformed.")
                continue
            try:
                change_status.encode("utf-8")
            except UnicodeEncodeError:
                coverage_messages.append(f"{path}: change status was malformed.")
                continue
            additions = entry.get("additions")
            deletions = entry.get("deletions")
            if (
                type(additions) is not int
                or additions < 0
                or type(deletions) is not int
                or deletions < 0
            ):
                coverage_messages.append(f"{path}: change counts were malformed.")
                continue
            patch = entry.get("patch")
            diff_valid: bool | None = None
            safe_patch: str | None = None
            patch_status = "missing"
            diff_lines: list[DiffLine] = []
            diff_lines_truncated = False
            diff_summary = None
            diff_diagnostics: list[str] = []
            try:
                patch_size = len(patch.encode("utf-8")) if isinstance(patch, str) else -1
            except UnicodeEncodeError:
                patch_size = -1
            if patch is None:
                coverage_messages.append(
                    f"{path}: GitHub omitted the patch; it may be binary or unavailable, "
                    "and the API does not identify which."
                )
            elif not isinstance(patch, str) or patch_size < 0:
                patch_status = "invalid"
                coverage_messages.append(f"{path}: GitHub returned a malformed patch.")
            elif patch_size > MAX_PATCH_BYTES:
                patch_status = "oversized"
                coverage_messages.append(f"{path}: diff exceeded the per-file size limit.")
            else:
                patch_bytes += patch_size
                if patch_bytes <= MAX_API_RESPONSE_BYTES:
                    safe_patch = patch
                    unified = f"--- a/{path}\n+++ b/{path}\n{patch}\n"
                    diff_summary = inspect_unified_diff(
                        unified,
                        max_line_records=max(
                            0, MAX_TOTAL_DIFF_LINE_RECORDS - diff_line_records_used
                        ),
                    )
                    diff_diagnostics = diff_summary.diagnostics
                    diff_valid = diff_summary.valid
                    if diff_valid is True:
                        diff_lines = [
                            line.model_copy(update={"diff_line": line.diff_line - 2})
                            for line in diff_summary.diff_lines
                        ]
                        diff_line_records_used += len(diff_lines)
                        diff_lines_truncated = diff_summary.diff_lines_truncated
                        if (
                            diff_summary.added_line_count != additions
                            or diff_summary.deleted_line_count != deletions
                        ):
                            patch_status = "incomplete"
                            mismatch = (
                                "Available hunk line counts do not match GitHub's changed-file "
                                "metadata."
                            )
                            diff_diagnostics = [*diff_diagnostics, mismatch]
                            coverage_messages.append(f"{path}: {mismatch}")
                        else:
                            patch_status = "available"
                        if diff_lines_truncated:
                            coverage_messages.append(
                                f"{path}: structured diff locations were capped; the displayed "
                                "patch remains available."
                            )
                    elif diff_summary.incomplete:
                        patch_status = "incomplete"
                        coverage_messages.append(f"{path}: diff patch ended before its hunk.")
                    else:
                        patch_status = "invalid"
                        coverage_messages.append(f"{path}: diff patch structure is invalid.")
                else:
                    patch_status = "oversized"
                    coverage_messages.append("The total pull request diff exceeded the size limit.")
            if not path.casefold().endswith(".py"):
                files.append(
                    _analysis_file(
                        path,
                        change_status=change_status,
                        additions=additions,
                        deletions=deletions,
                        patch=safe_patch,
                        diff_valid=diff_valid,
                        patch_status=patch_status,
                        diff_lines=diff_lines,
                        diff_lines_truncated=diff_lines_truncated,
                        diff_diagnostics=diff_diagnostics,
                        status="skipped",
                        message=(
                            "Only Python source files are parsed; file metadata is still shown."
                        ),
                    )
                )
                continue

            if change_status in {"removed", "deleted"}:
                files.append(
                    _analysis_file(
                        path,
                        change_status=change_status,
                        additions=additions,
                        deletions=deletions,
                        patch=safe_patch,
                        diff_valid=diff_valid,
                        patch_status=patch_status,
                        diff_lines=diff_lines,
                        diff_lines_truncated=diff_lines_truncated,
                        diff_diagnostics=diff_diagnostics,
                        status="skipped",
                        message="Removed files have no post-change source to parse.",
                    )
                )
                continue
            file_size = entry.get("size")
            if "size" in entry and (type(file_size) is not int or file_size < 0):
                files.append(
                    _analysis_file(
                        path,
                        change_status=change_status,
                        additions=additions,
                        deletions=deletions,
                        patch=safe_patch,
                        diff_valid=diff_valid,
                        patch_status=patch_status,
                        diff_lines=diff_lines,
                        diff_lines_truncated=diff_lines_truncated,
                        diff_diagnostics=diff_diagnostics,
                        status="error",
                        message="GitHub returned malformed file size metadata.",
                    )
                )
                coverage_messages.append(f"{path}: file size metadata was malformed.")
                continue
            if isinstance(file_size, int) and file_size > MAX_SOURCE_FILE_BYTES:
                files.append(
                    _analysis_file(
                        path,
                        change_status=change_status,
                        additions=additions,
                        deletions=deletions,
                        patch=safe_patch,
                        diff_valid=diff_valid,
                        patch_status=patch_status,
                        diff_lines=diff_lines,
                        diff_lines_truncated=diff_lines_truncated,
                        diff_diagnostics=diff_diagnostics,
                        status="skipped",
                        message="Python file exceeded the configured size limit.",
                    )
                )
                coverage_messages.append(f"{path}: file size limit exceeded.")
                continue
            try:
                analysis, used = _analyze_blob(
                    client,
                    owner,
                    repository,
                    path,
                    entry.get("sha"),
                    expected_size=file_size if isinstance(file_size, int) else None,
                    source_bytes_so_far=source_bytes,
                )
                source_bytes += used
                files.append(
                    _analysis_file(
                        path,
                        change_status=change_status,
                        additions=additions,
                        deletions=deletions,
                        patch=safe_patch,
                        diff_valid=diff_valid,
                        patch_status=patch_status,
                        diff_lines=diff_lines,
                        diff_lines_truncated=diff_lines_truncated,
                        diff_diagnostics=diff_diagnostics,
                        analysis=analysis,
                        status="analyzed",
                        message="Pull-request source was parsed without execution.",
                    )
                )
            except (AnalyzerError, GitHubIntegrationError) as exc:
                files.append(
                    _analysis_file(
                        path,
                        change_status=change_status,
                        additions=additions,
                        deletions=deletions,
                        patch=safe_patch,
                        diff_valid=diff_valid,
                        patch_status=patch_status,
                        diff_lines=diff_lines,
                        diff_lines_truncated=diff_lines_truncated,
                        diff_diagnostics=diff_diagnostics,
                        status="error",
                        message=exc.message,
                    )
                )
                coverage_messages.append(f"{path}: source was not completely inspected.")

        try:
            latest_pr_data = client.get_json(
                f"/repos/{owner}/{repository}/pulls/{request.pull_request_number}"
            )
        except GitHubIntegrationError:
            coverage_messages.append(
                "The pull-request snapshot could not be rechecked after file retrieval."
            )
        else:
            latest_base = latest_pr_data.get("base") if isinstance(latest_pr_data, dict) else None
            latest_head = latest_pr_data.get("head") if isinstance(latest_pr_data, dict) else None
            if (
                not isinstance(latest_base, dict)
                or not isinstance(latest_head, dict)
                or latest_base.get("sha") != pull_info.base_sha
                or latest_head.get("sha") != pull_info.head_sha
                or latest_pr_data.get("changed_files") != pull_info.changed_file_count
            ):
                coverage_messages.append(
                    "The pull request changed while its files were being inspected."
                )

    policy_result = evaluate_policy([], execution_mode=ExecutionMode.ANALYSIS_ONLY)
    evidence = []
    for item in files:
        analysis_outcome = (
            EvidenceOutcome.PASS
            if item.analysis is not None and item.analysis.syntax_valid is True
            else EvidenceOutcome.FAIL
            if item.analysis is not None and item.analysis.syntax_valid is False
            else EvidenceOutcome.INCONCLUSIVE
        )
        evidence.append(
            create_evidence(
                EvidenceCategory.STATIC_ANALYSIS,
                analysis_outcome,
                "Static syntax analysis completed successfully."
                if analysis_outcome is EvidenceOutcome.PASS
                else "Static syntax analysis found invalid Python syntax."
                if analysis_outcome is EvidenceOutcome.FAIL
                else item.message,
                details={
                    "path": item.path,
                    "file_type": item.file_type,
                    "finding_category": "python_syntax" if item.analysis else "file_coverage",
                    "syntax_valid": item.analysis.syntax_valid if item.analysis else None,
                    "status": item.status,
                    "detail": item.message,
                    "diagnostics": (
                        [
                            diagnostic.model_dump(mode="json")
                            for diagnostic in item.analysis.diagnostics
                        ]
                        if item.analysis
                        else []
                    ),
                },
            )
        )
        if pull_info is not None:
            diff_outcome = (
                EvidenceOutcome.PASS
                if item.diff_valid is True and item.patch_status == "available"
                else EvidenceOutcome.FAIL
                if item.patch_status == "invalid"
                else EvidenceOutcome.INCONCLUSIVE
            )
            evidence.append(
                create_evidence(
                    EvidenceCategory.PATCH_VALIDATION,
                    diff_outcome,
                    "Pull-request diff structure is valid."
                    if item.diff_valid is True and item.patch_status == "available"
                    else "Pull-request diff structure is invalid."
                    if item.patch_status == "invalid"
                    else "Pull-request patch is incomplete or its line counts are inconsistent."
                    if item.patch_status == "incomplete"
                    else "Pull-request diff was unavailable or not completely inspected.",
                    details={
                        "path": item.path,
                        "diff_valid": item.diff_valid,
                        "patch_status": item.patch_status,
                        "diagnostics": item.diff_diagnostics,
                        "diff_line_count": len(item.diff_lines),
                        "diff_lines_truncated": item.diff_lines_truncated,
                    },
                )
            )
    return GitHubInspectionResult(
        repository=repository_info,
        pull_request=pull_info,
        files=files,
        evidence=evidence,
        coverage_complete=not coverage_messages,
        coverage_messages=coverage_messages,
        decision=policy_result.status,
        decision_reasons=list(policy_result.reasons),
        policy_version=POLICY_VERSION,
    )
