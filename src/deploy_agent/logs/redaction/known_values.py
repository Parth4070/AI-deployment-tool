"""Layer 3: exact-match scrubbing of secret values the program already holds."""

import base64
import binascii
import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import quote, quote_plus

from deploy_agent.logs.redaction.models import KnownSecret
from deploy_agent.logs.redaction.placeholders import placeholder, sub_outside_placeholders

# Shorter values would match ordinary text, so refuse them rather than silently skip them.
MIN_SECRET_LENGTH = 4

# Line-break tolerance adds to the regex for every character, so very long values match
# only when they are unbroken.
MAX_SPLIT_TOLERANT_LENGTH = 512

# Optional trailing spaces, a line break, then up to 40 characters of log prefix.
_LINE_BREAK = r"(?:[ \t]*\r?\n[^\n]{0,40}?)?"

_BASE64_TOKEN = re.compile(r"[A-Za-z0-9+/_-]{8,}={0,2}")
_PERCENT_ESCAPE = re.compile(r"%[0-9A-F]{2}")


class SecretTooShortError(ValueError):
    """A known secret is too short to match safely. The message names it, never shows it."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"Secret {name} is shorter than {MIN_SECRET_LENGTH} characters, so it cannot be "
            "matched safely. Use a longer value, or do not register it with the redactor."
        )


@dataclass(frozen=True, repr=False)
class CompiledSecrets:
    """Prepared matchers. ``repr=False`` keeps the values out of debug output."""

    patterns: tuple[tuple[re.Pattern[str], str], ...]
    raw_values: tuple[tuple[bytes, str], ...]


def _lowercase_percent_escapes(text: str) -> str:
    return _PERCENT_ESCAPE.sub(lambda match: match.group().lower(), text)


def _encoded_forms(value: str) -> set[str]:
    raw = value.encode()
    standard = base64.b64encode(raw).decode()
    urlsafe = base64.urlsafe_b64encode(raw).decode()
    url_forms = {quote(value, safe=""), quote(value), quote_plus(value)}
    return {
        value,
        standard,
        standard.rstrip("="),
        urlsafe,
        urlsafe.rstrip("="),
        json.dumps(value)[1:-1],
        json.dumps(value, ensure_ascii=False)[1:-1],
        *url_forms,
        *(_lowercase_percent_escapes(form) for form in url_forms),
    }


def _compile_form(form: str) -> re.Pattern[str]:
    if len(form) > MAX_SPLIT_TOLERANT_LENGTH:
        return re.compile(re.escape(form))
    return re.compile(_LINE_BREAK.join(re.escape(char) for char in form))


def compile_known_secrets(secrets: Iterable[KnownSecret]) -> CompiledSecrets:
    forms: set[tuple[str, str]] = set()
    raw_values: set[tuple[bytes, str]] = set()
    for secret in secrets:
        value = secret.value.get_secret_value()
        if not value:
            continue
        if len(value) < MIN_SECRET_LENGTH:
            raise SecretTooShortError(secret.name)
        forms.update((form, secret.name) for form in _encoded_forms(value))
        raw_values.add((value.encode(), secret.name))

    # Longest first, so a value that contains another one is matched whole.
    ordered_forms = sorted(forms, key=lambda item: (-len(item[0]), item))
    return CompiledSecrets(
        patterns=tuple((_compile_form(form), label) for form, label in ordered_forms),
        raw_values=tuple(sorted(raw_values, key=lambda item: (-len(item[0]), item))),
    )


def _decode_base64(token: str) -> bytes | None:
    body = token.rstrip("=").replace("-", "+").replace("_", "/")
    try:
        return base64.b64decode(body + "=" * (-len(body) % 4), validate=True)
    except binascii.Error:
        return None


def redact_known_values(text: str, compiled: CompiledSecrets) -> tuple[str, Counter[str]]:
    counts: Counter[str] = Counter()

    def replace_blob(match: re.Match[str]) -> str:
        """Catch a value inside a larger base64 blob, such as ``user:password``."""
        decoded = _decode_base64(match.group())
        if decoded is not None:
            for value, label in compiled.raw_values:
                if value in decoded:
                    counts[label] += 1
                    return placeholder(label)
        return match.group()

    # Blobs go first: matching the value alone could leave the rest of the blob behind.
    if compiled.raw_values:
        text = sub_outside_placeholders(_BASE64_TOKEN, replace_blob, text)

    for pattern, label in compiled.patterns:

        def replace_value(_: re.Match[str], label: str = label) -> str:
            counts[label] += 1
            return placeholder(label)

        text = sub_outside_placeholders(pattern, replace_value, text)

    return text, counts
