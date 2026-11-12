"""Matcher tests against recorded-style failure logs in tests/fixtures/failure_logs/."""

from pathlib import Path

import pytest

from deploy_agent.logs import clean_log, match_failure
from deploy_agent.logs.clean import CleanLog
from deploy_agent.logs.matcher import MAX_EVIDENCE_LENGTH, evidence_text
from deploy_agent.logs.redaction import Redactor
from deploy_agent.models import Confidence, FailureMatch, NoMatch, SafetyTier

FIXTURES = Path(__file__).parent.parent / "fixtures" / "failure_logs"


def load(name: str) -> CleanLog:
    return clean_log((FIXTURES / name).read_text(encoding="utf-8"), Redactor())


def raw(text: str) -> CleanLog:
    return clean_log(text, Redactor())


def matched(result: FailureMatch | NoMatch) -> FailureMatch:
    assert isinstance(result, FailureMatch), result
    return result


@pytest.mark.parametrize(
    ("fixture", "failure_id", "line_number", "in_cause"),
    [
        ("python_module_not_found.log", "python_missing_module", 5, "'flask'"),
        ("node_cannot_find_module.log", "node_missing_module", 5, "'express'"),
        ("node_esm_package_not_found.log", "node_missing_module", 5, "'@prisma/client'"),
        ("node_eaddrinuse.log", "port_in_use", 6, "already using"),
        ("uvicorn_address_in_use.log", "port_in_use", 4, "already using"),
        ("npm_ebadengine.log", "node_engine_mismatch", 2, "Node version"),
        ("yarn_engine_incompatible.log", "node_engine_mismatch", 4, "Node version"),
        ("pip_requires_python.log", "python_version_mismatch", 2, "Python version"),
        ("python_environ_keyerror.log", "missing_env_var", 6, "DATABASE_URL"),
        ("prisma_env_not_found.log", "missing_env_var", 6, "DATABASE_URL"),
    ],
)
def test_fixture_matches_expected_failure(
    fixture: str, failure_id: str, line_number: int, in_cause: str
) -> None:
    result = matched(match_failure(load(fixture)))
    assert result.failure_id == failure_id
    assert result.line_number == line_number
    assert in_cause in result.diagnosis.cause
    lines = (FIXTURES / fixture).read_text(encoding="utf-8").splitlines()
    assert result.diagnosis.evidence_line == lines[line_number - 1].strip()
    assert result.diagnosis.alternative_causes
    assert result.diagnosis.next_step_tier is SafetyTier.NEEDS_APPROVAL


@pytest.mark.parametrize(
    "fixture", ["unknown_failure.log", "node_missing_local_file.log", "uvicorn_wrong_port.log"]
)
def test_fixture_without_known_failure_is_no_match(fixture: str) -> None:
    assert isinstance(match_failure(load(fixture)), NoMatch)


def test_npm_10_wording_matches() -> None:
    result = matched(match_failure(raw("npm error code EBADENGINE\n")))
    assert result.failure_id == "node_engine_mismatch"


def test_keyerror_without_os_environ_is_not_a_missing_env_var() -> None:
    log = raw("Traceback (most recent call last):\n  File 'x.py'\nKeyError: 'DATABASE_URL'\n")
    assert isinstance(match_failure(log), NoMatch)


def test_keyerror_with_old_python_os_path_matches() -> None:
    log = raw(
        '  File "/usr/lib/python3.8/os.py", line 675, in __getitem__\n'
        "    raise KeyError(key) from None\n"
        "KeyError: 'SECRET_KEY'\n"
    )
    result = matched(match_failure(log))
    assert result.failure_id == "missing_env_var"
    assert "SECRET_KEY" in result.diagnosis.cause


def test_keyerror_context_too_far_above_does_not_count() -> None:
    log = raw("os.environ\n" + "filler\n" * 11 + "KeyError: 'API_URL'\n")
    assert isinstance(match_failure(log), NoMatch)


def test_earliest_failure_wins() -> None:
    log = raw("ModuleNotFoundError: No module named 'flask'\nError: listen EADDRINUSE :::3000\n")
    assert matched(match_failure(log)).failure_id == "python_missing_module"


def test_absolute_path_module_is_not_a_missing_package() -> None:
    assert isinstance(match_failure(raw("Error: Cannot find module '/app/x.js'\n")), NoMatch)


def test_confidence_comes_from_the_catalog() -> None:
    assert matched(match_failure(load("node_eaddrinuse.log"))).diagnosis.confidence is (
        Confidence.HIGH
    )


# Wrong-port cross-check.


def test_port_mismatch_when_uvicorn_port_differs() -> None:
    result = matched(match_failure(load("uvicorn_wrong_port.log"), expected_port=8080))
    assert result.failure_id == "port_mismatch"
    assert result.line_number == 4
    assert "port 8000" in result.diagnosis.cause
    assert "port 8080" in result.diagnosis.cause
    assert result.diagnosis.next_step_tier is SafetyTier.NEEDS_APPROVAL


def test_no_port_mismatch_when_port_is_right() -> None:
    assert isinstance(match_failure(load("uvicorn_wrong_port.log"), expected_port=8000), NoMatch)


def test_ipv6_uvicorn_address_is_read() -> None:
    log = raw("INFO:     Uvicorn running on http://[::]:9000 (Press CTRL+C to quit)\n")
    assert matched(match_failure(log, expected_port=8000)).failure_id == "port_mismatch"


def test_real_error_beats_port_mismatch() -> None:
    log = raw(
        "INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)\n"
        "ModuleNotFoundError: No module named 'jinja2'\n"
    )
    assert matched(match_failure(log, expected_port=8080)).failure_id == "python_missing_module"


@pytest.mark.parametrize("port", [0, 70000, -1])
def test_bad_expected_port_is_rejected(port: int) -> None:
    with pytest.raises(ValueError, match="expected_port"):
        match_failure(raw("x"), expected_port=port)


# Evidence line safety.


def test_evidence_drops_control_and_direction_characters() -> None:
    assert evidence_text("a\x07b‮c\x1bd  ") == "abcd"


def test_evidence_is_capped() -> None:
    text = evidence_text("x" * 2000)
    assert len(text) == MAX_EVIDENCE_LENGTH
    assert text.endswith("...")
