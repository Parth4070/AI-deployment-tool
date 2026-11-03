"""Builds results, and keeps evidence to safe pieces.

Evidence must be made only from things that were already checked against a strict format:
file paths from the snapshot, line numbers, env var NAMES, port numbers, version strings
and fixed labels written in this codebase. Never put raw file text, command text or a
value into evidence: it could hold a secret or a prompt-injection attempt.
"""

from collections.abc import Iterable

from deploy_agent.models.common import Severity
from deploy_agent.models.preflight import PreflightResult

MAX_LISTED = 10


def passed(check_name: str, note: str | None = None) -> PreflightResult:
    return PreflightResult(
        check_name=check_name, passed=True, severity=Severity.INFO, evidence=note
    )


def skipped(check_name: str, reason: str) -> PreflightResult:
    """A check that does not apply. Shown as passed, with the reason."""
    return passed(check_name, f"Skipped: {reason}")


def failed(check_name: str, severity: Severity, evidence: str, fix: str) -> PreflightResult:
    return PreflightResult(
        check_name=check_name,
        passed=False,
        severity=severity,
        evidence=evidence,
        suggested_fix=fix,
    )


def listing(items: Iterable[object], limit: int = MAX_LISTED) -> str:
    """Join items with commas, cutting long lists short: 'A, B, C (+4 more)'."""
    shown = [str(item) for item in items]
    extra = len(shown) - limit
    text = ", ".join(shown[:limit])
    return f"{text} (+{extra} more)" if extra > 0 else text
