"""Safe, deterministic source and unified-diff inspection; no code is executed."""

from __future__ import annotations

import ast
import itertools
import os
import re
import stat
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO

from proofgate.models import (
    AnalysisFileResult,
    AnalysisSummary,
    BehavioralFinding,
    DiffLine,
    DiffSummary,
    SyntaxDiagnostic,
)

MAX_SOURCE_FILE_BYTES = 1_000_000
MAX_DIFF_BYTES = 200_000
MAX_ANALYSIS_ENTRIES = 20_000
_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
BEHAVIOR_RULE_ID = "PG-PY-ADD-SUB-001"
_ADD_REQUIREMENT_PATTERNS = (
    re.compile(
        r"\b(?:should|must|needs? to|is expected to)\s+add\s+"
        r"(?:(?:its|the|both)\s+)?(?:two\s+)?arguments\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:should|must|needs? to|is expected to)\s+return\s+"
        r"(?:the\s+)?sum\s+of\s+(?:(?:its|the|both)\s+)?(?:two\s+)?arguments\b",
        re.IGNORECASE,
    ),
)
_SUBTRACT_REQUIREMENT_PATTERNS = (
    re.compile(
        r"\b(?:should|must|needs? to|is expected to)\s+subtract\s+"
        r"(?:(?:its|the|both)\s+)?(?:two\s+)?arguments\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:should|must|needs? to|is expected to)\s+return\s+"
        r"(?:the\s+)?difference\s+of\s+(?:(?:its|the|both)\s+)?(?:two\s+)?arguments\b",
        re.IGNORECASE,
    ),
)


class AnalyzerError(ValueError):
    """A safe, user-correctable analyzer input or filesystem error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def validate_relative_path(relative_path: str, *, allow_dot: bool = True) -> tuple[str, ...]:
    """Validate a client-supplied path without relying on host path semantics."""
    if not relative_path or "\x00" in relative_path:
        raise AnalyzerError("invalid_path", "A non-empty repository-relative path is required.")
    if len(relative_path) > 500:
        raise AnalyzerError(
            "invalid_path", "Repository-relative paths are limited to 500 characters."
        )

    normalized = relative_path.replace("\\", "/")
    windows_path = PureWindowsPath(relative_path)
    posix_path = PurePosixPath(normalized)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or normalized.startswith("//")
        or any(part == ".." for part in normalized.split("/"))
    ):
        raise AnalyzerError("invalid_path", "Absolute paths and path traversal are not allowed.")

    parts = tuple(part for part in normalized.split("/") if part not in ("", "."))
    if not parts and not allow_dot:
        raise AnalyzerError("invalid_path", "A file path is required.")
    return parts


def resolve_repository_path(root: Path, relative_path: str, *, allow_dot: bool = True) -> Path:
    """Resolve a relative path and ensure its final target stays inside root."""
    parts = validate_relative_path(relative_path, allow_dot=allow_dot)
    try:
        resolved_root = root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise AnalyzerError(
            "invalid_root", "The configured repository root is unavailable."
        ) from exc
    if not resolved_root.is_dir():
        raise AnalyzerError("invalid_root", "The configured repository root is not a directory.")

    candidate = resolved_root.joinpath(*parts)
    try:
        resolved_candidate = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise AnalyzerError("not_found", "The requested repository path does not exist.") from exc
    except (OSError, RuntimeError) as exc:
        raise AnalyzerError(
            "unreadable_path", "The requested repository path cannot be accessed."
        ) from exc

    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise AnalyzerError(
            "path_escape", "The requested path resolves outside the repository root."
        ) from exc
    return resolved_candidate


def analyze_python_source(source: str, *, path: str = "<source>") -> AnalysisFileResult:
    """Parse supplied Python text without importing or executing it."""
    try:
        ast.parse(source, filename=path)
    except SyntaxError as exc:
        diagnostic = SyntaxDiagnostic(
            line=exc.lineno,
            column=exc.offset,
            message=(exc.msg or "Invalid Python syntax")[:300],
        )
        return AnalysisFileResult(
            path=path,
            syntax_valid=False,
            diagnostics=[diagnostic],
            status="analyzed",
        )
    return AnalysisFileResult(path=path, syntax_valid=True, status="analyzed")


def analyze_behavioral_requirement(
    requirement: str,
    source: str,
    *,
    path: str = "<source>",
) -> BehavioralFinding:
    """Check one explicit add/subtract requirement against a simple function AST."""
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return BehavioralFinding(
            finding_type="INVALID_SYNTAX",
            rule_id=BEHAVIOR_RULE_ID,
            message=(
                "Behavioral analysis is inconclusive because the Python source has invalid syntax."
            ),
        )

    operations = []
    if any(pattern.search(requirement) for pattern in _ADD_REQUIREMENT_PATTERNS):
        operations.append("addition")
    if any(pattern.search(requirement) for pattern in _SUBTRACT_REQUIREMENT_PATTERNS):
        operations.append("subtraction")
    if len(operations) != 1:
        message = (
            "The reported requirement is ambiguous for the supported add/subtract rule."
            if operations
            else "The reported requirement is outside the supported add/subtract rule."
        )
        return BehavioralFinding(
            finding_type="UNSUPPORTED_REQUIREMENT",
            rule_id=BEHAVIOR_RULE_ID,
            message=message,
        )

    expected_operator = operations[0]
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and (
            re.search(rf"\b{re.escape(node.name)}\s*\(", requirement)
            or re.search(rf"\bfunction\s+{re.escape(node.name)}\b", requirement, re.I)
            or re.search(rf"\b{re.escape(node.name)}\s+function\b", requirement, re.I)
        )
    ]
    if len(functions) != 1:
        return BehavioralFinding(
            finding_type="UNSUPPORTED_REQUIREMENT",
            rule_id=BEHAVIOR_RULE_ID,
            expected_operator=expected_operator,
            message=(
                "The supported requirement must identify exactly one matching function "
                "by name; no code-level behavior was inferred."
            ),
        )

    function = functions[0]
    arguments = [*function.args.posonlyargs, *function.args.args]
    if (
        len(arguments) != 2
        or function.args.defaults
        or function.args.kwonlyargs
        or function.args.kw_defaults
        or function.args.vararg is not None
        or function.args.kwarg is not None
        or len(function.body) != 1
        or not isinstance(function.body[0], ast.Return)
        or not isinstance(function.body[0].value, ast.BinOp)
    ):
        return BehavioralFinding(
            finding_type="UNSUPPORTED_EXPRESSION",
            rule_id=BEHAVIOR_RULE_ID,
            function_name=function.name,
            expected_operator=expected_operator,
            source_line=function.lineno,
            message=(
                "The named function is outside the supported form: exactly two required "
                "positional arguments and one direct binary return expression."
            ),
        )

    expression = function.body[0].value
    if isinstance(expression.op, ast.Add):
        detected_operator = "addition"
    elif isinstance(expression.op, ast.Sub):
        detected_operator = "subtraction"
    else:
        return BehavioralFinding(
            finding_type="UNSUPPORTED_EXPRESSION",
            rule_id=BEHAVIOR_RULE_ID,
            function_name=function.name,
            expected_operator=expected_operator,
            source_line=expression.lineno,
            message="The return operator is outside the supported addition/subtraction rule.",
        )

    parameter_names = [argument.arg for argument in arguments]
    operand_names = (
        expression.left.id if isinstance(expression.left, ast.Name) else None,
        expression.right.id if isinstance(expression.right, ast.Name) else None,
    )
    supported_operands = (
        set(operand_names) == set(parameter_names)
        and None not in operand_names
        and (detected_operator == "addition" or operand_names == tuple(parameter_names))
    )
    if not supported_operands:
        return BehavioralFinding(
            finding_type="UNSUPPORTED_EXPRESSION",
            rule_id=BEHAVIOR_RULE_ID,
            function_name=function.name,
            detected_operator=detected_operator,
            expected_operator=expected_operator,
            source_line=expression.lineno,
            message=(
                "The return expression does not use exactly the two named arguments "
                "in the supported order."
            ),
        )

    mismatch = detected_operator != expected_operator
    return BehavioralFinding(
        finding_type="POTENTIAL_BEHAVIOR_MISMATCH" if mismatch else "NO_MISMATCH_DETECTED",
        rule_id=BEHAVIOR_RULE_ID,
        function_name=function.name,
        detected_operator=detected_operator,
        expected_operator=expected_operator,
        source_line=expression.lineno,
        message=(
            "This narrow static rule found an operator mismatch; runtime behavior is not verified."
            if mismatch
            else (
                "No mismatch was detected by this narrow add/subtract rule; "
                "other behavior is unverified."
            )
        ),
    )


def _windows_handle_path(file_descriptor: int) -> Path:
    """Return the final path of an already-open Windows file handle."""
    import ctypes
    import ctypes.wintypes
    import msvcrt

    get_final_path = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
    get_final_path.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.wintypes.LPWSTR,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.DWORD,
    ]
    get_final_path.restype = ctypes.wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(32_768)
    handle = msvcrt.get_osfhandle(file_descriptor)
    length = get_final_path(handle, buffer, len(buffer), 0)
    if length == 0 or length >= len(buffer):
        raise OSError(ctypes.get_last_error(), "Could not validate the opened file path.")

    final_path = buffer.value
    if final_path.startswith("\\\\?\\UNC\\"):
        final_path = "\\\\" + final_path[8:]
    elif final_path.startswith("\\\\?\\"):
        final_path = final_path[4:]
    return Path(final_path)


def _windows_handle_is_reparse_point(file_descriptor: int) -> bool:
    """Inspect reparse metadata on the opened handle, not on a path that can change."""
    import ctypes
    import ctypes.wintypes
    import msvcrt

    class FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [
            ("file_attributes", ctypes.wintypes.DWORD),
            ("reparse_tag", ctypes.wintypes.DWORD),
        ]

    get_file_info = ctypes.WinDLL("kernel32", use_last_error=True).GetFileInformationByHandleEx
    get_file_info.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
    ]
    get_file_info.restype = ctypes.wintypes.BOOL
    info = FileAttributeTagInfo()
    handle = msvcrt.get_osfhandle(file_descriptor)
    if not get_file_info(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError(ctypes.get_last_error(), "Could not validate the opened file attributes.")
    return bool(info.file_attributes & 0x400)


def _path_is_within_root(candidate: Path, root: Path) -> bool:
    try:
        candidate_norm = os.path.normcase(os.path.abspath(candidate))
        root_norm = os.path.normcase(os.path.abspath(root))
        return os.path.commonpath((candidate_norm, root_norm)) == root_norm
    except (OSError, ValueError):
        return False


def _open_repository_file(root: Path, relative_parts: tuple[str, ...]) -> BinaryIO:
    """Open a repository file and validate the opened target before reading it.

    POSIX uses directory descriptors and O_NOFOLLOW for every path component.
    Windows validates the final path associated with the opened handle before
    reading, since Python does not expose equivalent directory-relative opens.
    """
    if not relative_parts:
        raise AnalyzerError("invalid_path", "A repository file path is required.")
    if any(
        not part or part in (".", "..") or "\x00" in part or "/" in part or "\\" in part
        for part in relative_parts
    ):
        raise AnalyzerError("invalid_path", "A safe repository-relative file path is required.")

    if os.name == "nt":
        import ctypes
        import ctypes.wintypes
        import msvcrt

        create_file = ctypes.WinDLL("kernel32", use_last_error=True).CreateFileW
        create_file.argtypes = [
            ctypes.wintypes.LPCWSTR,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.HANDLE,
        ]
        create_file.restype = ctypes.wintypes.HANDLE
        invalid_handle = ctypes.wintypes.HANDLE(-1).value
        handle = create_file(
            str(root.joinpath(*relative_parts)),
            0x80000000,
            0x00000001 | 0x00000002 | 0x00000004,
            None,
            3,
            0x00000080 | 0x00200000 | 0x08000000,
            None,
        )
        if handle == invalid_handle:
            error = ctypes.get_last_error()
            raise OSError(error, "Could not open repository file safely.")
        try:
            file_descriptor = msvcrt.open_osfhandle(
                handle, os.O_RDONLY | getattr(os, "O_BINARY", 0)
            )
        except OSError:
            close_handle = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
            close_handle.argtypes = [ctypes.wintypes.HANDLE]
            close_handle.restype = ctypes.wintypes.BOOL
            close_handle(handle)
            raise
        try:
            source_file = os.fdopen(file_descriptor, "rb")
        except BaseException:
            os.close(file_descriptor)
            raise
        try:
            if _windows_handle_is_reparse_point(source_file.fileno()):
                raise AnalyzerError("symlink_not_allowed", "Reparse-point files are not analyzed.")
            final_path = _windows_handle_path(source_file.fileno())
            if not _path_is_within_root(final_path, root):
                raise AnalyzerError(
                    "path_escape", "The opened file resolves outside the repository root."
                )
            if not stat.S_ISREG(os.fstat(source_file.fileno()).st_mode):
                raise AnalyzerError("invalid_file", "Only regular files can be analyzed.")
            return source_file
        except BaseException:
            source_file.close()
            raise

    required_flags = ("O_NOFOLLOW", "O_DIRECTORY")
    if any(not hasattr(os, flag) for flag in required_flags) or os.open not in os.supports_dir_fd:
        raise AnalyzerError(
            "secure_open_unavailable",
            "Race-resistant repository file access is unavailable on this platform.",
        )

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
    open_directory_fd = os.open("/", directory_flags)
    current_directory_fd = open_directory_fd
    try:
        for part in root.parts[1:]:
            next_directory_fd = os.open(part, directory_flags, dir_fd=current_directory_fd)
            if current_directory_fd != open_directory_fd:
                os.close(current_directory_fd)
            current_directory_fd = next_directory_fd

        for part in relative_parts[:-1]:
            next_directory_fd = os.open(part, directory_flags, dir_fd=current_directory_fd)
            if current_directory_fd != open_directory_fd:
                os.close(current_directory_fd)
            current_directory_fd = next_directory_fd

        file_descriptor = os.open(relative_parts[-1], file_flags, dir_fd=current_directory_fd)
        try:
            is_regular_file = stat.S_ISREG(os.fstat(file_descriptor).st_mode)
            if not is_regular_file:
                raise AnalyzerError("invalid_file", "Only regular files can be analyzed.")
            return os.fdopen(file_descriptor, "rb")
        except BaseException:
            os.close(file_descriptor)
            raise
    finally:
        if current_directory_fd != open_directory_fd:
            os.close(current_directory_fd)
        os.close(open_directory_fd)


def read_repository_source(root: Path, relative_path: str) -> tuple[str, str]:
    """Safely read one bounded Python file for verification without executing it."""
    target = resolve_repository_path(root, relative_path, allow_dot=False)
    if not target.is_file() or target.suffix.lower() != ".py":
        raise AnalyzerError(
            "invalid_source", "Verification source path must identify a Python file."
        )

    resolved_root = root.resolve(strict=True)
    relative_parts = target.relative_to(resolved_root).parts
    safe_relative_path = Path(*relative_parts).as_posix()
    try:
        with _open_repository_file(resolved_root, relative_parts) as source_file:
            metadata_before = os.fstat(source_file.fileno())
            if metadata_before.st_size > MAX_SOURCE_FILE_BYTES:
                raise AnalyzerError(
                    "source_too_large", "Verification source exceeds the size limit."
                )
            raw_source = source_file.read(MAX_SOURCE_FILE_BYTES + 1)
            metadata_after = os.fstat(source_file.fileno())
    except AnalyzerError:
        raise
    except OSError as exc:
        raise AnalyzerError(
            "unreadable_path", "The requested repository file cannot be accessed."
        ) from exc

    if len(raw_source) > MAX_SOURCE_FILE_BYTES:
        raise AnalyzerError("source_too_large", "Verification source exceeds the size limit.")
    if (
        metadata_before.st_size != metadata_after.st_size
        or metadata_before.st_mtime_ns != metadata_after.st_mtime_ns
        or metadata_before.st_ctime_ns != metadata_after.st_ctime_ns
    ):
        raise AnalyzerError(
            "source_changed", "The repository file changed during analysis; result discarded."
        )
    try:
        source = raw_source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AnalyzerError("invalid_source", "Verification source must be valid UTF-8.") from exc
    return safe_relative_path, source


def analyze_repository(
    root: Path,
    relative_path: str = ".",
    *,
    max_files: int = 100,
    max_file_bytes: int = MAX_SOURCE_FILE_BYTES,
    max_entries: int = MAX_ANALYSIS_ENTRIES,
) -> AnalysisSummary:
    """Read and AST-parse bounded Python source files under a permitted root."""
    if not 1 <= max_files <= 500:
        raise AnalyzerError("invalid_limit", "max_files must be between 1 and 500.")
    if not 1 <= max_entries <= MAX_ANALYSIS_ENTRIES:
        raise AnalyzerError(
            "invalid_limit", f"max_entries must be between 1 and {MAX_ANALYSIS_ENTRIES}."
        )
    target = resolve_repository_path(root, relative_path)
    root_resolved = root.resolve(strict=True)
    traversal_truncated = False
    if target.is_file():
        candidates = [target]
    elif target.is_dir():
        candidates = []
        pending_directories = [target]
        entries_visited = 0
        while pending_directories:
            directory = pending_directories.pop()
            remaining_entries = max_entries - entries_visited
            try:
                with os.scandir(directory) as scan:
                    directory_entries = list(itertools.islice(scan, remaining_entries + 1))
            except OSError as exc:
                raise AnalyzerError(
                    "unreadable_path", "A repository directory could not be read."
                ) from exc
            directory_entries.sort(key=lambda entry: entry.name.casefold())
            if len(directory_entries) > remaining_entries:
                directory_entries = directory_entries[:remaining_entries]
                traversal_truncated = True

            for entry in directory_entries:
                entries_visited += 1
                try:
                    if entry.is_symlink() or entry.is_junction():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending_directories.append(Path(entry.path))
                    elif (
                        entry.is_file(follow_symlinks=False)
                        and Path(entry.name).suffix.lower() == ".py"
                    ):
                        candidates.append(Path(entry.path))
                        if len(candidates) > max_files:
                            traversal_truncated = True
                            break
                except OSError as exc:
                    raise AnalyzerError(
                        "unreadable_path", "A repository entry could not be inspected."
                    ) from exc
            if traversal_truncated or len(candidates) > max_files:
                break
        candidates.sort(key=lambda item: item.as_posix().casefold())
    else:
        raise AnalyzerError("invalid_path", "The requested path is not a file or directory.")

    files: list[AnalysisFileResult] = []
    truncated = traversal_truncated or len(candidates) > max_files
    for file_path in candidates[:max_files]:
        try:
            relative_parts = file_path.relative_to(root_resolved).parts
            relative = Path(*relative_parts).as_posix()
        except ValueError:
            files.append(
                AnalysisFileResult(
                    path=file_path.name,
                    syntax_valid=None,
                    diagnostics=[SyntaxDiagnostic(message="Path is outside the repository root.")],
                    status="error",
                )
            )
            continue

        if file_path.suffix.lower() != ".py":
            files.append(
                AnalysisFileResult(
                    path=relative,
                    syntax_valid=None,
                    diagnostics=[
                        SyntaxDiagnostic(message="Only Python source files are permitted.")
                    ],
                    status="skipped",
                )
            )
            continue
        try:
            with _open_repository_file(root_resolved, relative_parts) as source_file:
                file_metadata = os.fstat(source_file.fileno())
                size = file_metadata.st_size
                if size > max_file_bytes:
                    files.append(
                        AnalysisFileResult(
                            path=relative,
                            syntax_valid=None,
                            size_bytes=size,
                            diagnostics=[
                                SyntaxDiagnostic(message="File exceeds the configured size limit.")
                            ],
                            status="skipped",
                        )
                    )
                    continue
                raw_source = source_file.read(max_file_bytes + 1)
                metadata_after_read = os.fstat(source_file.fileno())
            if len(raw_source) > max_file_bytes:
                files.append(
                    AnalysisFileResult(
                        path=relative,
                        syntax_valid=None,
                        size_bytes=size,
                        diagnostics=[
                            SyntaxDiagnostic(message="File exceeds the configured size limit.")
                        ],
                        status="skipped",
                    )
                )
                continue
            if (
                file_metadata.st_size != metadata_after_read.st_size
                or file_metadata.st_mtime_ns != metadata_after_read.st_mtime_ns
                or file_metadata.st_ctime_ns != metadata_after_read.st_ctime_ns
            ):
                files.append(
                    AnalysisFileResult(
                        path=relative,
                        syntax_valid=None,
                        diagnostics=[
                            SyntaxDiagnostic(
                                message="File changed during analysis; result discarded."
                            )
                        ],
                        status="error",
                    )
                )
                continue
            source = raw_source.decode("utf-8")
        except UnicodeDecodeError:
            files.append(
                AnalysisFileResult(
                    path=relative,
                    syntax_valid=None,
                    diagnostics=[SyntaxDiagnostic(message="File is not valid UTF-8.")],
                    status="error",
                )
            )
            continue
        except AnalyzerError as exc:
            files.append(
                AnalysisFileResult(
                    path=relative,
                    syntax_valid=None,
                    diagnostics=[SyntaxDiagnostic(message=exc.message)],
                    status="error",
                )
            )
            continue
        except OSError:
            files.append(
                AnalysisFileResult(
                    path=relative,
                    syntax_valid=None,
                    diagnostics=[SyntaxDiagnostic(message="File could not be read.")],
                    status="error",
                )
            )
            continue

        result = analyze_python_source(source, path=relative).model_copy(
            update={"size_bytes": size}
        )
        files.append(result)

    return AnalysisSummary(
        root_path=relative_path.replace("\\", "/"),
        file_count=len(files),
        python_file_count=sum(item.status == "analyzed" for item in files),
        syntax_error_count=sum(item.syntax_valid is False for item in files),
        analyzed_paths=[item.path for item in files if item.status == "analyzed"],
        files=files,
        truncated=truncated,
    )


def _diff_path(header_path: str) -> str | None:
    path = header_path.strip()
    if path == "/dev/null":
        return None
    if path.startswith(("a/", "b/")):
        path = path[2:]
    validate_relative_path(path, allow_dot=False)
    return path.replace("\\", "/")


def inspect_unified_diff(
    diff_text: str,
    *,
    max_bytes: int = MAX_DIFF_BYTES,
    max_line_records: int = 2_500,
) -> DiffSummary:
    """Validate diff headers/hunk counts and return changed paths."""
    if len(diff_text.encode("utf-8")) > max_bytes:
        raise AnalyzerError("diff_too_large", "Unified diff exceeds the configured size limit.")
    if max_line_records < 0:
        raise ValueError("max_line_records must not be negative.")
    lines = diff_text.splitlines()
    added: set[str] = set()
    removed: set[str] = set()
    changed: set[str] = set()
    diagnostics: list[str] = []
    diff_lines: list[DiffLine] = []
    old_path: str | None = None
    new_path: str | None = None
    files_seen = 0
    in_hunk = False
    old_remaining = new_remaining = 0
    old_line = new_line = 0
    added_line_count = deleted_line_count = 0
    diff_lines_truncated = False
    try:
        line_index = 0
        while line_index < len(lines):
            line = lines[line_index]
            line_number = line_index + 1
            if in_hunk:
                if line.startswith("\\ No newline at end of file"):
                    line_index += 1
                    continue
                if line.startswith(" ") and old_remaining and new_remaining:
                    kind = "context"
                    old_position, new_position = old_line, new_line
                    old_remaining -= 1
                    new_remaining -= 1
                    old_line += 1
                    new_line += 1
                elif line.startswith("-") and old_remaining:
                    kind = "deletion"
                    old_position, new_position = old_line, None
                    old_remaining -= 1
                    old_line += 1
                    deleted_line_count += 1
                elif line.startswith("+") and new_remaining:
                    kind = "addition"
                    old_position, new_position = None, new_line
                    new_remaining -= 1
                    new_line += 1
                    added_line_count += 1
                else:
                    raise ValueError(f"unexpected or excess hunk content at line {line_number}")
                if len(diff_lines) < max_line_records:
                    diff_lines.append(
                        DiffLine(
                            diff_line=line_number,
                            kind=kind,
                            old_line=old_position,
                            new_line=new_position,
                        )
                    )
                else:
                    diff_lines_truncated = True
                if old_remaining == 0 and new_remaining == 0:
                    in_hunk = False
                line_index += 1
                continue

            if line.startswith("--- "):
                old_path = _diff_path(line[4:])
                if line_index + 1 >= len(lines) or not lines[line_index + 1].startswith("+++ "):
                    raise ValueError(f"missing +++ file header after line {line_number}")
                new_path = _diff_path(lines[line_index + 1][4:])
                files_seen += 1
                if old_path is not None:
                    changed.add(old_path)
                if new_path is not None:
                    changed.add(new_path)
                if old_path is None and new_path is not None:
                    added.add(new_path)
                elif new_path is None and old_path is not None:
                    removed.add(old_path)
                line_index += 2
                continue
            if line.startswith("+++ "):
                raise ValueError(f"unexpected +++ file header at line {line_number}")
            if line.startswith("@@ "):
                if old_path is None and new_path is None:
                    raise ValueError(f"hunk has no file headers at line {line_number}")
                match = _HUNK_HEADER.match(line)
                if match is None:
                    raise ValueError(f"malformed hunk header at line {line_number}")
                old_remaining = int(match.group(2) or "1")
                new_remaining = int(match.group(4) or "1")
                old_line = int(match.group(1))
                new_line = int(match.group(3))
                in_hunk = old_remaining > 0 or new_remaining > 0
                line_index += 1
                continue
            if line.startswith(
                ("diff --git ", "index ", "new file mode ", "deleted file mode ", "rename ")
            ):
                line_index += 1
                continue
            if not line:
                line_index += 1
                continue
            if files_seen == 0:
                raise ValueError(f"unexpected diff content at line {line_number}")
            if line.startswith(("Binary files ", "GIT binary patch", "similarity index ")):
                line_index += 1
                continue
            raise ValueError(f"unexpected diff content at line {line_number}")

        if in_hunk:
            diagnostics.append("diff ended before all hunk lines were present")
            return DiffSummary(valid=False, diagnostics=diagnostics, incomplete=True)
        if files_seen == 0:
            raise ValueError("diff contains no unified file headers")
    except (ValueError, AnalyzerError) as exc:
        message = exc.message if isinstance(exc, AnalyzerError) else str(exc)
        diagnostics.append(message[:300])
        return DiffSummary(valid=False, diagnostics=diagnostics)

    return DiffSummary(
        valid=True,
        added_paths=sorted(added)[:100],
        removed_paths=sorted(removed)[:100],
        changed_paths=sorted(changed)[:100],
        diff_lines=diff_lines,
        diff_lines_truncated=diff_lines_truncated,
        added_line_count=added_line_count,
        deleted_line_count=deleted_line_count,
    )
