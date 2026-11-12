"""Tests for log cleaning. All secret-looking values here are fake."""

import pytest
from pydantic import SecretStr

from deploy_agent.logs.clean import (
    clean_log,
    normalize_newlines,
    strip_terminal_codes,
)
from deploy_agent.logs.redaction import KnownSecret, RedactionError, Redactor

FAKE_PASSWORD = "fake-Db/Pass+word-0001"


@pytest.fixture
def redactor() -> Redactor:
    return Redactor(
        known_secrets=(KnownSecret(name="DB_PASSWORD", value=SecretStr(FAKE_PASSWORD)),)
    )


def test_color_codes_are_removed() -> None:
    assert strip_terminal_codes("\x1b[31mnpm ERR!\x1b[0m code") == "npm ERR! code"


def test_window_title_and_link_codes_are_removed() -> None:
    text = "\x1b]0;title\x07done \x1b]8;;https://x.test\x1b\\link\x1b]8;;\x1b\\"
    assert strip_terminal_codes(text) == "done link"


def test_newlines_are_normalized() -> None:
    assert normalize_newlines("a\r\nb\rc\n") == "a\nb\nc\n"


def test_clean_text_without_secrets_is_unchanged(redactor: Redactor) -> None:
    log = clean_log("Listening on port 8000\n", redactor)
    assert log.text == "Listening on port 8000\n"
    assert log.findings == ()


def test_secret_split_by_a_color_code_is_still_redacted(redactor: Redactor) -> None:
    raw = f"password={FAKE_PASSWORD[:6]}\x1b[0m{FAKE_PASSWORD[6:]}\n"
    log = clean_log(raw, redactor)
    assert FAKE_PASSWORD not in log.text
    assert "<REDACTED:DB_PASSWORD>" in log.text


def test_redaction_failure_returns_no_text(
    redactor: Redactor, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_: object, text: str) -> object:
        raise ValueError(text)

    monkeypatch.setattr(Redactor, "_run_layers", broken)
    with pytest.raises(RedactionError) as error:
        clean_log(f"token {FAKE_PASSWORD}", redactor)
    assert FAKE_PASSWORD not in str(error.value)
    assert error.value.__cause__ is None
