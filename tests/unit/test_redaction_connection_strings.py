"""Tests for Layer 4: the password part of connection strings.

All secret-looking values in this file are fake.
"""

import pytest

from deploy_agent.logs.redaction.connection_strings import redact_connection_strings


def scrub(text: str) -> str:
    return redact_connection_strings(text)[0]


@pytest.mark.parametrize(
    ("text", "want"),
    [
        (
            "postgres://user:fakepass123@db.example.com:5432/app",
            "postgres://user:<REDACTED:CONNECTION_PASSWORD>@db.example.com:5432/app",
        ),
        (
            "mysql+pymysql://root:fakepass123@localhost/app",
            "mysql+pymysql://root:<REDACTED:CONNECTION_PASSWORD>@localhost/app",
        ),
        (
            "redis://:fakepass123@cache:6379/0",
            "redis://:<REDACTED:CONNECTION_PASSWORD>@cache:6379/0",
        ),
        (
            "https://bot:fakepass123@git.example.com/repo.git",
            "https://bot:<REDACTED:CONNECTION_PASSWORD>@git.example.com/repo.git",
        ),
        (
            "mongodb+srv://u:fake%40pass@cluster.example.net/db",
            "mongodb+srv://u:<REDACTED:CONNECTION_PASSWORD>@cluster.example.net/db",
        ),
    ],
    ids=["postgres", "driver-suffix", "no-username", "https", "percent-encoded-password"],
)
def test_password_is_replaced_and_the_rest_is_kept(text: str, want: str) -> None:
    assert scrub(text) == want


def test_password_containing_at_and_slash_is_fully_removed() -> None:
    cleaned = scrub("postgres://user:fake@pa/ss@db.example.com/app")
    assert cleaned == "postgres://user:<REDACTED:CONNECTION_PASSWORD>@db.example.com/app"


@pytest.mark.parametrize(
    ("text", "want"),
    [
        (
            "DATABASE_URL=postgres://u:fakepass123@db/app",
            "DATABASE_URL=postgres://u:<REDACTED:DATABASE_URL>@db/app",
        ),
        (
            'database_url: "postgres://u:fakepass123@db/app"',
            'database_url: "postgres://u:<REDACTED:DATABASE_URL>@db/app"',
        ),
        (
            '{"redis_uri": "redis://u:fakepass123@cache"}',
            '{"redis_uri": "redis://u:<REDACTED:REDIS_URI>@cache"}',
        ),
    ],
    ids=["env-line", "yaml", "json"],
)
def test_a_url_style_key_names_the_placeholder(text: str, want: str) -> None:
    assert scrub(text) == want


def test_an_ordinary_word_before_the_url_does_not_name_the_placeholder() -> None:
    cleaned = scrub("Error: postgres://u:fakepass123@db/app refused")
    assert cleaned == "Error: postgres://u:<REDACTED:CONNECTION_PASSWORD>@db/app refused"


def test_string_inside_a_quoted_error_message_stops_at_the_quote() -> None:
    cleaned = scrub("could not connect to 'postgres://u:fakepass123@db/app': timeout, retry @ 5s")
    assert cleaned == (
        "could not connect to 'postgres://u:<REDACTED:CONNECTION_PASSWORD>@db/app': "
        "timeout, retry @ 5s"
    )


def test_two_strings_on_one_line_lose_both_passwords() -> None:
    cleaned = scrub("a postgres://u:fakeone111@h1/d b redis://v:faketwo222@h2/0")
    assert "fakeone111" not in cleaned
    assert "faketwo222" not in cleaned


def test_each_replacement_is_counted() -> None:
    _, counts = redact_connection_strings("a://u:p1@h b://u:p2@h")
    assert counts == {"CONNECTION_PASSWORD": 2}


@pytest.mark.parametrize(
    "text",
    [
        "postgres://user@db.example.com/app",
        "https://example.com/path?a=1",
        "https://registry.npmjs.org:443/@types/node",
        "http://localhost:3000/@vite/client",
    ],
    ids=["username-only", "plain-url", "npm-scoped-package", "dev-server-path"],
)
def test_urls_without_a_password_are_unchanged(text: str) -> None:
    assert scrub(text) == text
