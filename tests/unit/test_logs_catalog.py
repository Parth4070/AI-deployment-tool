"""Checks that every catalog entry is well formed and safe."""

import string

import pytest

from deploy_agent.logs.catalog import (
    CATALOG,
    PORT_MISMATCH_ALTERNATIVES,
    PORT_MISMATCH_CAUSE,
    PORT_MISMATCH_ID,
    PORT_MISMATCH_KIND,
    PORT_MISMATCH_NEXT_STEP,
    FailureEntry,
)
from deploy_agent.models.common import SafetyTier
from deploy_agent.models.policy import ProposedAction
from deploy_agent.policy import evaluate
from deploy_agent.policy.rules import ACTION_CATALOG


def _fields(text: str) -> set[str]:
    return {field for _, field, _, _ in string.Formatter().parse(text) if field is not None}


def _texts(entry: FailureEntry) -> tuple[str, ...]:
    return (entry.cause, entry.next_step, *entry.alternative_causes)


def test_ids_are_unique() -> None:
    ids = [entry.failure_id for entry in CATALOG] + [PORT_MISMATCH_ID]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("entry", CATALOG, ids=lambda entry: entry.failure_id)
def test_entry_is_complete(entry: FailureEntry) -> None:
    assert entry.patterns
    assert entry.alternative_causes
    assert entry.cause not in entry.alternative_causes


@pytest.mark.parametrize("entry", CATALOG, ids=lambda entry: entry.failure_id)
def test_next_step_kind_is_known_and_never_forbidden(entry: FailureEntry) -> None:
    assert entry.next_step_kind in ACTION_CATALOG
    decision = evaluate(ProposedAction(kind=entry.next_step_kind, description=entry.next_step))
    assert decision.tier is not SafetyTier.FORBIDDEN


def test_port_mismatch_next_step_is_known_and_never_forbidden() -> None:
    assert PORT_MISMATCH_KIND in ACTION_CATALOG
    text = PORT_MISMATCH_NEXT_STEP.format(actual=8000, expected=8080)
    assert evaluate(ProposedAction(kind=PORT_MISMATCH_KIND, description=text)).tier in {
        SafetyTier.AUTO,
        SafetyTier.NEEDS_APPROVAL,
    }


@pytest.mark.parametrize("entry", CATALOG, ids=lambda entry: entry.failure_id)
def test_only_the_name_can_be_filled_in(entry: FailureEntry) -> None:
    fields = set().union(*(_fields(text) for text in _texts(entry)))
    assert fields <= {"name"}


@pytest.mark.parametrize("entry", CATALOG, ids=lambda entry: entry.failure_id)
def test_a_captured_name_always_has_a_strict_format(entry: FailureEntry) -> None:
    captures_name = any("name" in pattern.regex.groupindex for pattern in entry.patterns)
    uses_name = any("name" in _fields(text) for text in _texts(entry))
    if captures_name or uses_name:
        assert entry.name_format is not None
    if uses_name:
        assert all("name" in pattern.regex.groupindex for pattern in entry.patterns)


def test_port_mismatch_texts_use_only_the_two_ports() -> None:
    texts = (PORT_MISMATCH_CAUSE, PORT_MISMATCH_NEXT_STEP, *PORT_MISMATCH_ALTERNATIVES)
    assert set().union(*(_fields(text) for text in texts)) <= {"actual", "expected"}
