"""Honest record of what the redactor does NOT catch.

Every test states the behavior we would want, and is marked as an expected failure
because the redactor does not do it. ``strict=True`` turns a fixed gap into a failure,
which is the prompt to remove the case from this file.

Why these matter: anything here could reach the AI gateway if it were in the input. The
gateway's allowlist (hard rule 2) is the protection for these cases, not this redactor.

All secret-looking values in this file are fake.
"""

import base64
from urllib.parse import quote

import pytest
from pydantic import SecretStr

from deploy_agent.logs.redaction import KnownSecret, Redactor

FAKE = "fake-Known/value+0001"
KNOWN = KnownSecret(name="KNOWN_SECRET", value=SecretStr(FAKE))
LONG_FAKE = "fQ7xK2mP" * 80
LONG_KNOWN = KnownSecret(name="LONG_SECRET", value=SecretStr(LONG_FAKE))


@pytest.mark.xfail(strict=True, reason="Unknown secrets are only matched on one line")
@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("password=fake-first-half\nfake-second-half", "fake-second-half"),
        ("value fQ7xK2mPz9Lw\nR4tYv8NbC3sD", "R4tYv8NbC3sD"),
    ],
    ids=["after-a-keyword", "random-token"],
)
def test_unknown_secret_split_across_lines(text: str, fragment: str) -> None:
    assert fragment not in Redactor().redact(text).text


@pytest.mark.xfail(strict=True, reason="Nothing marks these as secret")
@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("login with hunter22 was refused", "hunter22"),
        ("connecting as admin / Summer2026!", "Summer2026!"),
        ("https://example.com/hook?sig=abc123", "abc123"),
        ("https://faketoken@git.example.com/repo.git", "faketoken"),
        ("- name: PASSWORD\n  value: fake-plain-value\n", "fake-plain-value"),
        ("password: fake pass phrase", "phrase"),
        ("password: |\n  fake-block-value\n", "fake-block-value"),
        ("newvendor_live_short1", "newvendor_live_short1"),
    ],
    ids=[
        "short-password-in-prose",
        "ordinary-password-no-keyword",
        "low-randomness-url-parameter",
        "token-as-url-username",
        "name-and-value-on-separate-lines",
        "unquoted-value-with-spaces",
        "yaml-block-value",
        "unlisted-vendor-format",
    ],
)
def test_unknown_secret_that_looks_ordinary(text: str, fragment: str) -> None:
    assert fragment not in Redactor().redact(text).text


@pytest.mark.xfail(strict=True, reason="Only plain, URL, base64 and JSON forms are matched")
@pytest.mark.parametrize(
    "text",
    [
        FAKE.encode().hex(),
        quote(quote(FAKE, safe=""), safe=""),
        base64.b64encode(base64.b64encode(FAKE.encode())).decode(),
        FAKE.upper(),
        FAKE[::-1],
        f"{FAKE[:9]}\x1b[0m{FAKE[9:]}",
        f"{FAKE[:9]}​{FAKE[9:]}",
    ],
    ids=[
        "hex",
        "double-url-encoded",
        "double-base64",
        "changed-case",
        "reversed",
        "colour-code-inside",
        "invisible-character-inside",
    ],
)
def test_known_secret_in_an_unhandled_form(text: str) -> None:
    result = Redactor(known_secrets=(KNOWN,)).redact(text)
    assert "<REDACTED:KNOWN_SECRET>" in result.text


@pytest.mark.xfail(strict=True, reason="Line-break matching stops at 512 characters")
def test_very_long_known_secret_split_across_lines() -> None:
    text = f"{LONG_FAKE[:100]}\n{LONG_FAKE[100:]}"
    result = Redactor(known_secrets=(LONG_KNOWN,)).redact(text)
    assert "<REDACTED:LONG_SECRET>" in result.text


@pytest.mark.xfail(strict=True, reason="Each call sees only the text it is given")
def test_known_secret_cut_in_two_by_separate_calls() -> None:
    redactor = Redactor(known_secrets=(KNOWN,))
    first = redactor.redact(FAKE[:9]).text
    second = redactor.redact(FAKE[9:]).text
    assert "<REDACTED:KNOWN_SECRET>" in first + second
