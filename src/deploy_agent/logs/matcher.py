"""Matches a cleaned log against the failure catalog, and returns a diagnosis or no match.

Rules in code, no AI. Log text is untrusted: it is only ever quoted as evidence, or reduced
to a name that passed a strict format check. It never changes which steps are suggested
or their tier. The tier always comes from the policy engine.
"""

import re

from deploy_agent.logs.catalog import (
    CATALOG,
    CONTEXT_LINES,
    PORT_MISMATCH_ALTERNATIVES,
    PORT_MISMATCH_CAUSE,
    PORT_MISMATCH_ID,
    PORT_MISMATCH_KIND,
    PORT_MISMATCH_NEXT_STEP,
    UVICORN_LISTENING,
    FailureEntry,
    LinePattern,
)
from deploy_agent.logs.clean import CleanLog
from deploy_agent.models.common import Confidence
from deploy_agent.models.diagnosis import Diagnosis, FailureMatch, NoMatch
from deploy_agent.models.policy import ProposedAction
from deploy_agent.policy import evaluate

MAX_EVIDENCE_LENGTH = 500

# Control characters, and Unicode marks that can flip text direction on screen.
_UNSAFE_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f‎‏‪-‮⁦-⁩]")


def evidence_text(line: str) -> str:
    """A log line made safe to show: no control characters, trimmed, length capped."""
    text = _UNSAFE_CHARS.sub("", line).strip()
    if len(text) > MAX_EVIDENCE_LENGTH:
        text = text[: MAX_EVIDENCE_LENGTH - 3] + "..."
    return text


def _context_found(pattern: LinePattern, lines: list[str], index: int) -> bool:
    if pattern.context is None:
        return True
    context = pattern.context
    return any(context.search(before) for before in lines[max(0, index - CONTEXT_LINES) : index])


def _safe_name(entry: FailureEntry, match: re.Match[str]) -> str | None:
    """The captured name if it passes the entry's format, "" if there is none, else None."""
    if "name" not in match.re.groupindex:
        return ""
    name = match["name"]
    if entry.name_format is None or not entry.name_format.fullmatch(name):
        return None
    return name


def _diagnosis(
    *,
    cause: str,
    evidence: str,
    confidence: Confidence,
    alternatives: tuple[str, ...],
    next_step: str,
    kind: str,
) -> Diagnosis:
    decision = evaluate(ProposedAction(kind=kind, description=next_step))
    return Diagnosis(
        cause=cause,
        evidence_line=evidence,
        confidence=confidence,
        alternative_causes=alternatives,
        suggested_next_step=next_step,
        next_step_tier=decision.tier,
    )


def _entry_match(entry: FailureEntry, lines: list[str], index: int) -> FailureMatch | None:
    line = lines[index]
    for pattern in entry.patterns:
        match = pattern.regex.search(line)
        if match is None or not _context_found(pattern, lines, index):
            continue
        name = _safe_name(entry, match)
        if name is None:
            continue
        evidence = evidence_text(line)
        if not evidence:
            continue
        diagnosis = _diagnosis(
            cause=entry.cause.format(name=name),
            evidence=evidence,
            confidence=entry.confidence,
            alternatives=tuple(text.format(name=name) for text in entry.alternative_causes),
            next_step=entry.next_step.format(name=name),
            kind=entry.next_step_kind,
        )
        return FailureMatch(failure_id=entry.failure_id, line_number=index + 1, diagnosis=diagnosis)
    return None


def _port_mismatch(lines: list[str], expected_port: int) -> FailureMatch | None:
    """The first uvicorn startup line whose port differs from the expected port."""
    for index, line in enumerate(lines):
        match = UVICORN_LISTENING.search(line)
        if match is None:
            continue
        actual = int(match["port"])
        if actual == expected_port or not 1 <= actual <= 65535:
            continue
        values = {"actual": actual, "expected": expected_port}
        diagnosis = _diagnosis(
            cause=PORT_MISMATCH_CAUSE.format(**values),
            evidence=evidence_text(line),
            confidence=Confidence.HIGH,
            alternatives=tuple(text.format(**values) for text in PORT_MISMATCH_ALTERNATIVES),
            next_step=PORT_MISMATCH_NEXT_STEP.format(**values),
            kind=PORT_MISMATCH_KIND,
        )
        return FailureMatch(failure_id=PORT_MISMATCH_ID, line_number=index + 1, diagnosis=diagnosis)
    return None


def match_failure(log: CleanLog, expected_port: int | None = None) -> FailureMatch | NoMatch:
    """Find the first known failure in a cleaned log.

    Catalog errors come first, earliest line wins: the first error is usually the cause
    and later ones its side effects. The port cross-check runs only when no error matched
    and ``expected_port`` is given, because a wrong port is not an error line.
    """
    if expected_port is not None and not 1 <= expected_port <= 65535:
        raise ValueError("expected_port must be between 1 and 65535")
    lines = log.text.split("\n")
    for index in range(len(lines)):
        for entry in CATALOG:
            found = _entry_match(entry, lines, index)
            if found is not None:
                return found
    if expected_port is not None:
        mismatch = _port_mismatch(lines, expected_port)
        if mismatch is not None:
            return mismatch
    return NoMatch()
