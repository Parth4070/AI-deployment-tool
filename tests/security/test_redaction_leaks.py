"""Leak tests: fake secrets go through the whole redactor and must not come out.

All secret-looking values in this file are fake.
"""

import base64
import json
import time
import traceback
from urllib.parse import quote

import pytest
from pydantic import SecretStr

from deploy_agent.logs.redaction import (
    Finding,
    KnownSecret,
    RedactionError,
    RedactionLayer,
    Redactor,
    SecretTooShortError,
)

DB_PASSWORD = "fake-Db/Pass+word-0001"
API_TOKEN = "fakeApiTokenValue0002"
DB_SECRET = KnownSecret(name="DB_PASSWORD", value=SecretStr(DB_PASSWORD))
API_SECRET = KnownSecret(name="API_TOKEN", value=SecretStr(API_TOKEN))

AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"
RANDOM_TOKEN = "fQ7xK2mPz9LwR4tYv8NbC3sD"


@pytest.fixture
def redactor() -> Redactor:
    return Redactor(known_secrets=(DB_SECRET, API_SECRET))


def test_nothing_sensitive_means_identical_text_and_no_findings(redactor: Redactor) -> None:
    text = "Build finished in 12.3s\nListening on port 8000"
    result = redactor.redact(text)
    assert result.text == text
    assert result.findings == ()


def test_findings_report_layer_label_and_count(redactor: Redactor) -> None:
    text = f"{DB_PASSWORD} {DB_PASSWORD} postgres://u:other-fake@h/d {AWS_KEY} x {RANDOM_TOKEN}"
    assert set(redactor.redact(text).findings) == {
        Finding(layer=RedactionLayer.KNOWN_VALUE, label="DB_PASSWORD", count=2),
        Finding(layer=RedactionLayer.CONNECTION_STRING, label="CONNECTION_PASSWORD", count=1),
        Finding(layer=RedactionLayer.PATTERN, label="AWS_ACCESS_KEY", count=1),
        Finding(layer=RedactionLayer.ENTROPY, label="HIGH_ENTROPY", count=1),
    }


def test_known_secret_gets_its_own_name_rather_than_a_generic_one(redactor: Redactor) -> None:
    text = f"postgres://u:{DB_PASSWORD}@h/d password={API_TOKEN} {API_TOKEN}"
    assert redactor.redact(text).text == (
        "postgres://u:<REDACTED:DB_PASSWORD>@h/d password=<REDACTED:API_TOKEN> <REDACTED:API_TOKEN>"
    )


@pytest.mark.parametrize(
    "text",
    [
        json.dumps({"db": {"password": "other-fake-json", "host": "db"}}, indent=2),
        '{"config": "{\\"password\\": \\"other-fake-json\\"}"}',
        "database:\n  host: db\n  password: other-fake-json\n",
        '- env:\n    API_KEY: "other-fake-json"\n',
    ],
    ids=["json", "json-in-json", "yaml", "yaml-quoted"],
)
def test_unknown_secret_in_structured_text(redactor: Redactor, text: str) -> None:
    assert "other-fake-json" not in redactor.redact(text).text


@pytest.mark.parametrize(
    "template",
    [
        "psycopg2.OperationalError: FATAL: password authentication failed for {}",
        "Traceback (most recent call last):\n  ValueError: bad credential {}",
        "error: failed to push to 'https://bot:{}@git.example.com/repo.git'",
        "npm ERR! 401 Unauthorized - PUT https://registry.example.com/ - token {}",
        "Exception: request failed with headers {{'x-api': '{}'}}",
    ],
    ids=["psycopg", "traceback", "git-push", "npm", "python-dict-repr"],
)
def test_known_secret_inside_an_error_message(redactor: Redactor, template: str) -> None:
    cleaned = redactor.redact(template.format(DB_PASSWORD)).text
    assert DB_PASSWORD not in cleaned
    assert "<REDACTED:DB_PASSWORD>" in cleaned


@pytest.mark.parametrize(
    "text",
    [
        quote(DB_PASSWORD, safe=""),
        base64.b64encode(DB_PASSWORD.encode()).decode(),
        base64.b64encode(f"svc:{DB_PASSWORD}".encode()).decode(),
        json.dumps({"p": DB_PASSWORD}),
        f"{DB_PASSWORD[:8]}\n{DB_PASSWORD[8:]}",
        f"2026-01-01 INFO {DB_PASSWORD[:8]}\n2026-01-01 INFO {DB_PASSWORD[8:]}",
    ],
    ids=["url", "base64", "base64-with-username", "json", "split", "split-with-prefix"],
)
def test_no_trace_of_a_known_secret_in_any_form(redactor: Redactor, text: str) -> None:
    result = redactor.redact(text)
    assert result.text.count("<REDACTED:DB_PASSWORD>") == 1
    assert "Pass+word" not in result.text
    assert "fake-Db" not in result.text


def test_secret_wrapped_in_a_forged_placeholder_is_still_removed() -> None:
    cleaned = Redactor().redact(f"<REDACTED:{AWS_KEY}>").text
    assert AWS_KEY not in cleaned


def test_forged_placeholder_cannot_pass_as_real_output() -> None:
    assert "<REDACTED:" not in Redactor().redact("<REDACTED:ALL_CLEAN>").text


def test_output_models_and_redactor_carry_no_secret_text(redactor: Redactor) -> None:
    result = redactor.redact(f"token {API_TOKEN} and {AWS_KEY}")
    for rendered in (repr(result), str(result), result.model_dump_json(), repr(redactor)):
        assert API_TOKEN not in rendered
        assert AWS_KEY not in rendered


def test_internal_failure_raises_without_any_text(
    redactor: Redactor, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(text: str) -> None:
        raise RuntimeError(f"boom while reading {text}")

    monkeypatch.setattr("deploy_agent.logs.redaction.redactor.redact_patterns", explode)

    with pytest.raises(RedactionError) as caught:
        redactor.redact(f"secret {RANDOM_TOKEN}")

    report = "".join(traceback.format_exception(caught.value))
    assert RANDOM_TOKEN not in report


def test_too_short_known_secret_stops_setup() -> None:
    with pytest.raises(SecretTooShortError):
        Redactor(known_secrets=(KnownSecret(name="PIN", value=SecretStr("123")),))


@pytest.mark.parametrize(
    "text",
    [
        "a" * 1_000_000,
        "password=" * 100_000,
        "x://" * 100_000,
        ("word-" * 200_000),
        "a.b_c-" * 150_000,
        "fake-Db\n" * 100_000,
        "fake-Db/Pass+word-000" * 40_000,
    ],
    ids=[
        "one-long-token",
        "repeated-key",
        "repeated-scheme",
        "dashes",
        "name-characters",
        "partial-secret-then-line-break",
        "almost-the-secret-repeated",
    ],
)
def test_hostile_input_finishes_quickly(redactor: Redactor, text: str) -> None:
    started = time.monotonic()
    redactor.redact(text)
    assert time.monotonic() - started < 5
