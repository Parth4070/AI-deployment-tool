"""Tests for Layer 1: known secret formats and secret-looking assignments.

All secret-looking values in this file are fake. Tokens are joined from pieces so that
secret scanners do not mistake this file for a real leak.
"""

import pytest

from deploy_agent.logs.redaction.patterns import redact_patterns

ALNUM = "a1B2c3D4e5"
HEX_32 = "0123456789abcdef" * 2

JWT = "eyJ" + "hbGciOiJIUzI1NiJ9" + ".eyJ" + "zdWIiOiJmYWtlIn0" + ".ZmFrZS1zaWduYXR1cmU"


def scrub(text: str) -> str:
    return redact_patterns(text)[0]


@pytest.mark.parametrize(
    ("token", "label"),
    [
        ("AKIA" + "IOSFODNN7EXAMPLE", "AWS_ACCESS_KEY"),
        ("ASIA" + "IOSFODNN7EXAMPLE", "AWS_ACCESS_KEY"),
        ("ghp_" + ALNUM * 4, "GITHUB_TOKEN"),
        ("gho_" + ALNUM * 4, "GITHUB_TOKEN"),
        ("ghs_" + ALNUM * 4, "GITHUB_TOKEN"),
        ("github_pat_" + ALNUM * 9, "GITHUB_TOKEN"),
        ("glpat-" + ALNUM * 2, "GITLAB_TOKEN"),
        ("xoxb-" + "1234567890-1234567890-" + ALNUM, "SLACK_TOKEN"),
        ("https://hooks.slack.com/services/" + "T000/B000/" + ALNUM * 3, "SLACK_WEBHOOK"),
        ("sk_live_" + ALNUM * 2, "STRIPE_KEY"),
        ("rk_test_" + ALNUM * 2, "STRIPE_KEY"),
        ("sk-ant-api03-" + ALNUM * 4, "ANTHROPIC_KEY"),
        ("sk-proj-" + ALNUM * 4, "OPENAI_KEY"),
        ("AIza" + ALNUM * 3 + "abcde", "GOOGLE_API_KEY"),
        ("SG." + ALNUM * 2 + "." + ALNUM * 3, "SENDGRID_KEY"),
        ("npm_" + ALNUM * 3 + "abcdef", "NPM_TOKEN"),
        ("pypi-AgEIcHlwaS5vcmc" + ALNUM * 6, "PYPI_TOKEN"),
        ("SK" + HEX_32, "TWILIO_KEY"),
        ("dop_v1_" + HEX_32 * 2, "DIGITALOCEAN_TOKEN"),
        (JWT, "JWT"),
    ],
    ids=lambda value: value if value.isupper() else "",
)
def test_known_format_is_replaced(token: str, label: str) -> None:
    assert scrub(f"before {token} after") == f"before <REDACTED:{label}> after"


def test_whole_github_token_is_removed_not_just_its_prefix() -> None:
    token = "ghp_" + ALNUM * 4
    assert ALNUM not in scrub(f"auth failed for {token}")


def test_private_key_block_spanning_lines_is_replaced() -> None:
    begin = "-----BEGIN RSA " + "PRIVATE KEY-----"
    end = "-----END RSA " + "PRIVATE KEY-----"
    text = f"start\n{begin}\nZmFrZQ==\nZmFrZQ==\n{end}\nfinish"
    assert scrub(text) == "start\n<REDACTED:PRIVATE_KEY>\nfinish"


def test_cut_off_private_key_is_replaced_to_the_end_of_the_text() -> None:
    begin = "-----BEGIN " + "PRIVATE KEY-----"
    assert scrub(f"start\n{begin}\nZmFrZQ==\nZmFr") == "start\n<REDACTED:PRIVATE_KEY>"


@pytest.mark.parametrize(
    ("text", "want"),
    [
        (
            "Authorization: Bearer fake.opaque.value",
            "Authorization: Bearer <REDACTED:AUTHORIZATION>",
        ),
        (
            "authorization: token fakeOpaqueValue",
            "authorization: token <REDACTED:AUTHORIZATION>",
        ),
        (
            '{"Authorization": "Basic ZmFrZTpmYWtl"}',
            '{"Authorization": "Basic <REDACTED:AUTHORIZATION>"}',
        ),
        ("Cookie: session=fakevalue; other=x", "Cookie: <REDACTED:COOKIE>"),
        ("Set-Cookie: sid=fakevalue; Path=/", "Set-Cookie: <REDACTED:COOKIE>"),
    ],
    ids=["bearer", "token-scheme", "json-header", "cookie", "set-cookie"],
)
def test_auth_headers_are_replaced(text: str, want: str) -> None:
    assert scrub(text) == want


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("password=fake-value-1", "password=<REDACTED:PASSWORD>"),
        ("DB_PASSWORD=fake-value-1", "DB_PASSWORD=<REDACTED:DB_PASSWORD>"),
        ("export API_KEY='fake value 1'", "export API_KEY='<REDACTED:API_KEY>'"),
        ("client_secret: fake-value-1", "client_secret: <REDACTED:CLIENT_SECRET>"),
        ('password: "fake value 1"', 'password: "<REDACTED:PASSWORD>"'),
        ('{"api_key": "fake-value-1"}', '{"api_key": "<REDACTED:API_KEY>"}'),
        ('{"password":"fa\\"ke-1"}', '{"password":"<REDACTED:PASSWORD>"}'),
        ('{\\"token\\":\\"fake-value-1\\"}', '{\\"token\\":\\"<REDACTED:TOKEN>\\"}'),
        ("dbPassword = fake-value-1", "dbPassword = <REDACTED:DBPASSWORD>"),
        ("apiKey => fake-value-1", "apiKey => <REDACTED:APIKEY>"),
        (
            "jdbc:postgresql://db/app?user=me&password=fake1&ssl=true",
            "jdbc:postgresql://db/app?user=me&password=<REDACTED:PASSWORD>&ssl=true",
        ),
        (
            "Server=db;User=me;Password=fake1;Encrypt=true",
            "Server=db;User=me;Password=<REDACTED:PASSWORD>;Encrypt=true",
        ),
        (
            "host=db user=me password=fake1 port=5",
            "host=db user=me password=<REDACTED:PASSWORD> port=5",
        ),
    ],
    ids=[
        "env",
        "prefixed-env",
        "shell-quoted",
        "yaml",
        "yaml-quoted",
        "json",
        "json-escaped-quote",
        "json-inside-json",
        "camel-case",
        "ruby-arrow",
        "jdbc-query",
        "semicolon-dsn",
        "libpq-dsn",
    ],
)
def test_secret_assignments_are_replaced(text: str, want: str) -> None:
    assert scrub(text) == want


@pytest.mark.parametrize(
    "text",
    [
        "tests: 12 passed=12 failed=0",
        "bypass: 3",
        "max_tokens=1000",
        "token_count: 512",
        "password=None",
        "password: null",
        "use_token: true",
        'password: ""',
        "password=${DB_PASSWORD}",
        "password=$DB_PASSWORD",
        "password: ****",
        "Bearer authentication is required",
        "Missing required variable SECRET_KEY",
    ],
)
def test_harmless_text_is_unchanged(text: str) -> None:
    assert scrub(text) == text


def test_label_from_a_hostile_key_stays_a_valid_placeholder() -> None:
    assert scrub("my.weird-password=fake1") == "my.weird-password=<REDACTED:MY_WEIRD_PASSWORD>"


def test_existing_placeholder_is_left_alone() -> None:
    text = "password=<REDACTED:DB_PASSWORD> <REDACTED:GITHUB_TOKEN>"
    assert scrub(text) == text


def test_replacements_are_counted_by_label() -> None:
    _, counts = redact_patterns("password=fake1 password=fake2 " + "AKIA" + "IOSFODNN7EXAMPLE")
    assert counts == {"PASSWORD": 2, "AWS_ACCESS_KEY": 1}
