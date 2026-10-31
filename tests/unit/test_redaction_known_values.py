"""Tests for Layer 3: exact-match scrubbing of secret values the program holds.

All secret-looking values in this file are fake.
"""

import base64
import json
from urllib.parse import quote, quote_plus

import pytest
from pydantic import SecretStr, ValidationError

from deploy_agent.logs.redaction.known_values import (
    SecretTooShortError,
    compile_known_secrets,
    redact_known_values,
)
from deploy_agent.logs.redaction.models import KnownSecret

FAKE = "fake-Hunter2/value+0001"
SECRET = KnownSecret(name="DATABASE_URL", value=SecretStr(FAKE))
TAG = "<REDACTED:DATABASE_URL>"


def scrub(text: str, *secrets: KnownSecret) -> str:
    cleaned, _ = redact_known_values(text, compile_known_secrets(secrets or (SECRET,)))
    return cleaned


def test_plain_value_is_replaced_with_its_named_placeholder() -> None:
    assert scrub(f"connecting with {FAKE} now") == f"connecting with {TAG} now"


def test_every_occurrence_is_counted() -> None:
    _, counts = redact_known_values(f"{FAKE} {FAKE}", compile_known_secrets((SECRET,)))
    assert counts == {"DATABASE_URL": 2}


@pytest.mark.parametrize(
    "encoded",
    [
        quote(FAKE, safe=""),
        "fake-Hunter2%2fvalue%2b0001",
        quote(FAKE),
        quote_plus(FAKE),
        base64.b64encode(FAKE.encode()).decode(),
        base64.b64encode(FAKE.encode()).decode().rstrip("="),
        base64.urlsafe_b64encode(FAKE.encode()).decode(),
        base64.urlsafe_b64encode(FAKE.encode()).decode().rstrip("="),
    ],
    ids=[
        "url",
        "url-lowercase-hex",
        "url-slash-kept",
        "url-plus",
        "base64",
        "base64-unpadded",
        "base64-urlsafe",
        "base64-urlsafe-unpadded",
    ],
)
def test_encoded_forms_are_replaced(encoded: str) -> None:
    assert scrub(f"before {encoded} after") == f"before {TAG} after"


def test_json_escaped_quote_inside_a_value_is_replaced() -> None:
    value = 'fake"quote\\slash'
    secret = KnownSecret(name="API_PASSWORD", value=SecretStr(value))
    escaped = json.dumps(value)[1:-1]
    assert scrub(f'{{"p": "{escaped}"}}', secret) == '{"p": "<REDACTED:API_PASSWORD>"}'


def test_value_split_across_two_lines_is_replaced() -> None:
    assert scrub(f"token {FAKE[:9]}\n{FAKE[9:]} end") == f"token {TAG} end"


def test_value_split_with_a_log_prefix_on_the_second_line_is_replaced() -> None:
    text = f"12:00:01 INFO key {FAKE[:9]}\r\n12:00:02 INFO {FAKE[9:]} end"
    assert scrub(text) == f"12:00:01 INFO key {TAG} end"


def test_base64_value_wrapped_across_lines_is_replaced() -> None:
    encoded = base64.b64encode(FAKE.encode()).decode()
    assert FAKE not in scrub(f"{encoded[:12]}\n{encoded[12:]}")
    assert scrub(f"{encoded[:12]}\n{encoded[12:]}") == TAG


def test_value_hidden_inside_a_larger_base64_blob_is_replaced() -> None:
    blob = base64.b64encode(f"admin:{FAKE}".encode()).decode()
    assert scrub(f"Authorization: Basic {blob}") == f"Authorization: Basic {TAG}"


def test_longest_value_wins_when_one_secret_contains_another() -> None:
    short = KnownSecret(name="SHORT_ONE", value=SecretStr("fake-abcd"))
    long = KnownSecret(name="LONG_ONE", value=SecretStr("fake-abcd-efgh"))
    assert scrub("x fake-abcd-efgh y", short, long) == "x <REDACTED:LONG_ONE> y"


def test_longest_value_names_a_blob_that_holds_both_secrets() -> None:
    short = KnownSecret(name="SHORT_ONE", value=SecretStr("fake-abcd"))
    long = KnownSecret(name="LONG_ONE", value=SecretStr("fake-abcd-efgh"))
    blob = base64.b64encode(b"svc:fake-abcd-efgh").decode()
    assert scrub(f"x {blob} y", short, long) == "x <REDACTED:LONG_ONE> y"


def test_regex_characters_in_a_value_are_matched_literally() -> None:
    secret = KnownSecret(name="REGEX_ISH", value=SecretStr("a.c(d)*e"))
    assert scrub("abcXdYe a.c(d)*e", secret) == "abcXdYe <REDACTED:REGEX_ISH>"


def test_text_without_a_secret_is_unchanged() -> None:
    assert scrub("nothing to see here") == "nothing to see here"


def test_empty_value_is_ignored_because_there_is_nothing_to_leak() -> None:
    empty = KnownSecret(name="UNSET_VAR", value=SecretStr(""))
    assert scrub("plain text", empty) == "plain text"


def test_too_short_value_is_rejected_by_name_without_showing_the_value() -> None:
    short = KnownSecret(name="SHORT_VAR", value=SecretStr("xq7"))
    with pytest.raises(SecretTooShortError) as caught:
        compile_known_secrets((short,))
    assert "SHORT_VAR" in str(caught.value)
    assert "xq7" not in str(caught.value)


def test_compiled_secrets_repr_does_not_show_the_value() -> None:
    assert FAKE not in repr(compile_known_secrets((SECRET,)))


def test_known_secret_repr_hides_the_value() -> None:
    assert FAKE not in repr(SECRET)


@pytest.mark.parametrize("name", ["lower_case", "HAS SPACE", "BAD>NAME", ""])
def test_placeholder_breaking_names_are_rejected(name: str) -> None:
    with pytest.raises(ValidationError):
        KnownSecret(name=name, value=SecretStr(FAKE))
