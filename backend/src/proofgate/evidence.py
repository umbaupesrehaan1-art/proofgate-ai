"""Creation and normalization helpers for bounded verification evidence."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from proofgate.models import (
    CheckResult,
    CheckStatus,
    EvidenceCategory,
    EvidenceOutcome,
    EvidenceRecord,
)

MAX_DETAIL_KEYS = 20
MAX_DETAIL_TEXT = 500
_SENSITIVE_KEY_PARTS = ("secret", "token", "password", "credential", "environment", "command")


def start_timer() -> float:
    """Return a monotonic start time suitable for elapsed_ms()."""
    return time.perf_counter()


def elapsed_ms(started_at: float) -> int:
    return max(0, round((time.perf_counter() - started_at) * 1_000))


def _bounded_value(value: Any, depth: int = 0) -> Any:
    if depth > 3:
        return "[omitted]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_DETAIL_TEXT]
    if isinstance(value, (list, tuple)):
        return [_bounded_value(item, depth + 1) for item in value[:20]]
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for key, item in list(value.items())[:MAX_DETAIL_KEYS]:
            safe_key = str(key)[:80]
            if any(part in safe_key.casefold() for part in _SENSITIVE_KEY_PARTS):
                safe[safe_key] = "[redacted]"
            else:
                safe[safe_key] = _bounded_value(item, depth + 1)
        return safe
    return str(value)[:MAX_DETAIL_TEXT]


def normalize_outcome(status: CheckStatus) -> EvidenceOutcome:
    """Map check status to evidence outcome; non-execution is never a pass."""
    if status is CheckStatus.PASSED:
        return EvidenceOutcome.PASS
    if status is CheckStatus.FAILED:
        return EvidenceOutcome.FAIL
    return EvidenceOutcome.INCONCLUSIVE


def create_evidence(
    category: EvidenceCategory,
    outcome: EvidenceOutcome,
    message: str,
    *,
    details: Mapping[str, Any] | None = None,
    duration_ms: int | None = None,
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=f"ev_{uuid4().hex}",
        category=category,
        outcome=outcome,
        message=message[:500],
        details=_bounded_value(details or {}),
        duration_ms=duration_ms,
    )


def evidence_from_check(check: CheckResult) -> EvidenceRecord:
    return create_evidence(
        check.category,
        normalize_outcome(check.status),
        check.message,
        details={"check": check.name, **check.details},
        duration_ms=check.duration_ms,
    )
