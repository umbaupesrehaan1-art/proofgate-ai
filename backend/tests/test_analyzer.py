import os
from pathlib import Path

import pytest

import proofgate.analyzer as analyzer
from proofgate.analyzer import (
    AnalyzerError,
    analyze_python_source,
    analyze_repository,
    inspect_unified_diff,
    resolve_repository_path,
)


def test_valid_python_syntax() -> None:
    result = analyze_python_source("def answer():\n    return 42\n")
    assert result.syntax_valid is True
    assert result.diagnostics == []


def test_invalid_python_syntax() -> None:
    result = analyze_python_source("def broken(:\n    pass\n")
    assert result.syntax_valid is False
    assert result.diagnostics[0].line == 1


def test_missing_source_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(AnalyzerError, match="does not exist"):
        resolve_repository_path(tmp_path, "missing.py", allow_dot=False)


def test_invalid_utf8_file_is_reported_without_crashing(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_bytes(b"\xff\xfe")
    result = analyze_repository(tmp_path, "bad.py")
    assert result.file_count == 1
    assert result.files[0].status == "error"
    assert "UTF-8" in result.files[0].diagnostics[0].message


@pytest.mark.parametrize("path", ["../outside.py", "sub/../../outside.py", "..\\outside.py"])
def test_path_traversal_is_rejected(tmp_path: Path, path: str) -> None:
    with pytest.raises(AnalyzerError, match="Absolute paths and path traversal"):
        resolve_repository_path(tmp_path, path)


@pytest.mark.parametrize("path", ["/etc/passwd", "C:\\Windows\\win.ini", "D:/repo/file.py"])
def test_absolute_and_windows_drive_paths_are_rejected(tmp_path: Path, path: str) -> None:
    with pytest.raises(AnalyzerError, match="Absolute paths and path traversal"):
        resolve_repository_path(tmp_path, path)


def test_symlink_escape_is_rejected_when_supported(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.py"
    outside.write_text("outside = True\n", encoding="utf-8")
    link = tmp_path / "escape.py"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable on this platform.")
    try:
        with pytest.raises(AnalyzerError, match="outside the repository root"):
            resolve_repository_path(tmp_path, "escape.py", allow_dot=False)
    finally:
        outside.unlink(missing_ok=True)


def test_file_replaced_with_external_symlink_before_open_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.py"
    outside.write_text("outside_secret = 'must not be read'\n", encoding="utf-8")
    candidate = tmp_path / "candidate.py"
    candidate.write_text("inside = True\n", encoding="utf-8")
    secure_open = analyzer._open_repository_file
    replacement_done = False

    def replace_then_open(root: Path, relative_parts: tuple[str, ...]):
        nonlocal replacement_done
        if not replacement_done:
            candidate.unlink()
            try:
                candidate.symlink_to(outside)
            except (OSError, NotImplementedError):
                pytest.skip("Symlink creation is unavailable on this platform.")
            replacement_done = True
        return secure_open(root, relative_parts)

    monkeypatch.setattr(analyzer, "_open_repository_file", replace_then_open)
    result = analyze_repository(tmp_path)

    assert result.files
    assert result.files[0].status == "error"
    assert result.files[0].syntax_valid is None
    assert "outside_secret" not in str(result.model_dump())
    outside.unlink(missing_ok=True)


def test_parent_directory_replaced_with_external_symlink_before_open_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside-dir"
    outside.mkdir()
    (outside / "candidate.py").write_text("outside = True\n", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    candidate = nested / "candidate.py"
    candidate.write_text("inside = True\n", encoding="utf-8")
    secure_open = analyzer._open_repository_file
    replacement_done = False

    def replace_parent_then_open(root: Path, relative_parts: tuple[str, ...]):
        nonlocal replacement_done
        if not replacement_done:
            nested.rename(tmp_path / "nested-original")
            try:
                nested.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                pytest.skip("Directory symlink creation is unavailable on this platform.")
            replacement_done = True
        return secure_open(root, relative_parts)

    monkeypatch.setattr(analyzer, "_open_repository_file", replace_parent_then_open)
    result = analyze_repository(tmp_path)

    assert result.files
    assert result.files[0].status == "error"
    assert result.files[0].syntax_valid is None
    assert "outside = True" not in str(result.model_dump())


@pytest.mark.skipif(os.name != "nt", reason="Windows handle validation is platform-specific.")
def test_windows_open_handle_outside_root_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate.py"
    candidate.write_text("inside = True\n", encoding="utf-8")
    outside = tmp_path.parent / "outside.py"
    monkeypatch.setattr(analyzer, "_windows_handle_path", lambda _fd: outside)

    with pytest.raises(AnalyzerError, match="outside the repository root"):
        analyzer._open_repository_file(tmp_path.resolve(), ("candidate.py",))


@pytest.mark.skipif(os.name != "nt", reason="Windows handle validation is platform-specific.")
def test_windows_open_reparse_point_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate.py"
    candidate.write_text("inside = True\n", encoding="utf-8")
    monkeypatch.setattr(analyzer, "_windows_handle_is_reparse_point", lambda _fd: True)

    with pytest.raises(AnalyzerError, match="Reparse-point files are not analyzed"):
        analyzer._open_repository_file(tmp_path.resolve(), ("candidate.py",))


def test_secure_file_open_rejects_traversal_components(tmp_path: Path) -> None:
    with pytest.raises(AnalyzerError, match="safe repository-relative"):
        analyzer._open_repository_file(tmp_path.resolve(), ("..", "outside.py"))


def test_file_size_limit_is_enforced(tmp_path: Path) -> None:
    (tmp_path / "large.py").write_text("value = 'long'\n", encoding="utf-8")
    result = analyze_repository(tmp_path, "large.py", max_file_bytes=5)
    assert result.files[0].status == "skipped"
    assert "size limit" in result.files[0].diagnostics[0].message


def test_repository_entry_limit_bounds_non_python_traversal(tmp_path: Path) -> None:
    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text("data", encoding="utf-8")
    (tmp_path / "z.py").write_text("value = 1\n", encoding="utf-8")

    result = analyze_repository(tmp_path, max_entries=1)

    assert result.truncated is True
    assert result.file_count == 0


def test_valid_unified_diff_reports_changed_paths() -> None:
    diff = "--- a/src/example.py\n+++ b/src/example.py\n@@ -1 +1 @@\n-return 0\n+return 1\n"
    result = inspect_unified_diff(diff)
    assert result.valid is True
    assert result.changed_paths == ["src/example.py"]
    assert [
        (line.diff_line, line.kind, line.old_line, line.new_line) for line in result.diff_lines
    ] == [
        (4, "deletion", 1, None),
        (5, "addition", None, 1),
    ]


def test_unified_diff_line_locations_cover_context_additions_and_deletions() -> None:
    diff = (
        "--- a/src/example.py\n"
        "+++ b/src/example.py\n"
        "@@ -10,2 +10,2 @@\n"
        " before = True\n"
        "-value = 1\n"
        "+value = 2\n"
    )

    result = inspect_unified_diff(diff)

    assert result.valid is True
    assert [(line.kind, line.old_line, line.new_line) for line in result.diff_lines] == [
        ("context", 10, 10),
        ("deletion", 11, None),
        ("addition", None, 11),
    ]


def test_unified_diff_reports_added_and_removed_file_line_locations() -> None:
    diff = (
        "--- /dev/null\n"
        "+++ b/new.py\n"
        "@@ -0,0 +1 @@\n"
        "+value = 1\n"
        "--- a/old.py\n"
        "+++ /dev/null\n"
        "@@ -1 +0,0 @@\n"
        "-value = 0\n"
    )

    result = inspect_unified_diff(diff)

    assert result.valid is True
    assert result.added_paths == ["new.py"]
    assert result.removed_paths == ["old.py"]
    assert [(line.kind, line.old_line, line.new_line) for line in result.diff_lines] == [
        ("addition", None, 1),
        ("deletion", 1, None),
    ]


def test_unified_diff_marks_a_truncated_hunk_incomplete() -> None:
    diff = "--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,2 @@\n-old\n+new\n"

    result = inspect_unified_diff(diff)

    assert result.valid is False
    assert result.incomplete is True
    assert result.diff_lines == []


def test_unified_diff_line_record_limit_is_explicit() -> None:
    diff = "--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,2 @@\n-a\n+b\n-c\n+d\n"

    result = inspect_unified_diff(diff, max_line_records=2)

    assert result.valid is True
    assert len(result.diff_lines) == 2
    assert result.diff_lines_truncated is True


@pytest.mark.parametrize(
    "diff",
    [
        "not a diff\n",
        "--- a/file.py\n@@ -1 +1 @@\n-x\n+y\n",
        "--- a/file.py\n+++ b/file.py\n@@ -1,2 +1 @@\n-x\n+y\n",
        "--- a/../outside.py\n+++ b/../outside.py\n@@ -1 +1 @@\n-x\n+y\n",
    ],
)
def test_malformed_unified_diff_is_rejected(diff: str) -> None:
    result = inspect_unified_diff(diff)
    assert result.valid is False
    assert result.diagnostics


def test_diff_size_limit_is_enforced() -> None:
    with pytest.raises(AnalyzerError, match="size limit"):
        inspect_unified_diff("--- a/a.py\n+++ b/a.py\n", max_bytes=4)


def test_source_analysis_does_not_execute_code(tmp_path: Path) -> None:
    marker = tmp_path / "executed.txt"
    source = f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n"
    result = analyze_python_source(source)
    assert result.syntax_valid is True
    assert not marker.exists()
