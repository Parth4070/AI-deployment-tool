"""Leak tests: fake secrets go through cleaning and matching and must not come out.

All secret-looking values here are fake.
"""

import base64
from pathlib import Path
from urllib.parse import quote

import pytest
from pydantic import SecretStr

from deploy_agent.logs import clean_log, match_failure
from deploy_agent.logs.redaction import KnownSecret, Redactor
from deploy_agent.models import FailureMatch

FIXTURES = Path(__file__).parent.parent / "fixtures" / "failure_logs"

KNOWN_TOKEN = "fake/Known+Token-0005"
FAKE_VALUES = (
    "fake-pg-pass-1234",
    "fakeSessionSecretValue0003",
    "fakeBearerTokenValue0004",
    KNOWN_TOKEN,
    base64.b64encode(KNOWN_TOKEN.encode()).decode(),
    quote(KNOWN_TOKEN, safe=""),
)


@pytest.fixture
def redactor() -> Redactor:
    return Redactor(
        known_secrets=(KnownSecret(name="SETTINGS_TOKEN", value=SecretStr(KNOWN_TOKEN)),)
    )


def test_fixture_really_contains_the_fake_values() -> None:
    text = (FIXTURES / "with_fake_secrets.log").read_text(encoding="utf-8")
    for value in FAKE_VALUES:
        assert value in text


def test_no_fake_secret_survives_cleaning_or_diagnosis(redactor: Redactor) -> None:
    raw = (FIXTURES / "with_fake_secrets.log").read_text(encoding="utf-8")
    log = clean_log(raw, redactor)
    result = match_failure(log, expected_port=8080)
    assert isinstance(result, FailureMatch)
    assert result.failure_id == "missing_env_var"
    outputs = (log.text, log.model_dump_json(), result.model_dump_json(), repr(result))
    for value in FAKE_VALUES:
        for output in outputs:
            assert value not in output


def test_secret_on_the_evidence_line_is_redacted_in_the_quote(redactor: Redactor) -> None:
    raw = "ModuleNotFoundError: No module named 'psycopg' url=postgres://u:fake-pass-9999@h/db\n"
    result = match_failure(clean_log(raw, redactor))
    assert isinstance(result, FailureMatch)
    assert "fake-pass-9999" not in result.diagnosis.evidence_line
    assert "<REDACTED:" in result.diagnosis.evidence_line


def test_secret_hidden_by_color_codes_does_not_survive(redactor: Redactor) -> None:
    raw = (
        f"token \x1b[1m{KNOWN_TOKEN[:5]}\x1b[22m{KNOWN_TOKEN[5:]}\nError: Cannot find module 'x'\n"
    )
    log = clean_log(raw, redactor)
    assert KNOWN_TOKEN not in log.text
    assert KNOWN_TOKEN not in match_failure(log).model_dump_json()
