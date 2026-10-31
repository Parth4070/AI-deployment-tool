"""Tests for Layer 2: high-randomness strings.

All secret-looking values in this file are fake.
"""

import pytest

from deploy_agent.logs.redaction.entropy import redact_high_entropy, shannon_entropy

TAG = "<REDACTED:HIGH_ENTROPY>"


def scrub(text: str) -> str:
    return redact_high_entropy(text)[0]


def test_entropy_of_one_repeated_character_is_zero() -> None:
    assert shannon_entropy("aaaa") == 0.0


def test_entropy_of_four_different_characters_is_two_bits() -> None:
    assert shannon_entropy("abcd") == 2.0


@pytest.mark.parametrize(
    "token",
    [
        "fQ7xK2mPz9LwR4tYv8NbC3sD",
        "xJ4_kL9-mN2_pQ7-rS5_tV8w",
        "cGFzc3dvcmQ6ZmFrZS12YWx1ZS0xMjM=",
        "9f86d081884c7d659a2feaa0c55ad015",
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "QwErTyUiOpAsDfGhJkLzXcVb",
    ],
    ids=["base62", "with-separators", "base64-padded", "hex-32", "hex-64", "letters-only"],
)
def test_random_looking_token_is_replaced(token: str) -> None:
    assert scrub(f"value {token} rejected") == f"value {TAG} rejected"


def test_padding_goes_with_the_token() -> None:
    assert scrub("x cGFzc3dvcmQ6ZmFrZS12YWx1ZS0xMjM= y") == f"x {TAG} y"


def test_assignment_name_is_kept() -> None:
    assert scrub("BUILD_REF=fQ7xK2mPz9LwR4tYv8NbC3sD") == f"BUILD_REF={TAG}"


@pytest.mark.parametrize(
    "text",
    [
        "short3Token9",
        "/usr/local/lib/python3/site-packages/requests/adapters",
        "node_modules/some-package-name/dist/index",
        "test_redaction_known_values_are_replaced",
        "ThisIsAVeryLongCamelCaseClassName",
        "AbstractSingletonProxyFactoryBean",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "================================",
        "--------------------------------",
        "550e8400-e29b-41d4-a716-446655440000",
        "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "sha512-z4PhNX7vuL3xVChQ1m2AB9Yg5AULVxXcg/SpIdNs6c5H0NE8XYXysP+DGNKHfuwvY7kxvUdBeoGlODJ6",
    ],
    ids=[
        "short",
        "unix-path",
        "node-path",
        "snake-case",
        "camel-case",
        "long-class-name",
        "repeated-character",
        "equals-rule",
        "dash-rule",
        "uuid",
        "docker-digest",
        "npm-integrity",
    ],
)
def test_ordinary_text_is_unchanged(text: str) -> None:
    assert scrub(text) == text


def test_long_placeholder_name_is_not_replaced() -> None:
    text = "<REDACTED:A1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q7R8S9T0>"
    assert scrub(text) == text


def test_replacements_are_counted() -> None:
    _, counts = redact_high_entropy("fQ7xK2mPz9LwR4tYv8NbC3sD gH5jK8lM2nB4vC6xZ9qW3eRt")
    assert counts == {"HIGH_ENTROPY": 2}
