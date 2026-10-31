"""Building placeholders, and making sure no layer rewrites one another layer wrote."""

import re
from collections.abc import Callable

_PLACEHOLDER_SPLIT = re.compile(r"(<REDACTED:[A-Z0-9_]+>)")

FORGED_PREFIX = "<REDACTED:"
DISARMED_PREFIX = "[REDACTED:"


def placeholder(label: str) -> str:
    return f"<REDACTED:{label}>"


def disarm_forged_placeholders(text: str) -> str:
    """Stop input from posing as a placeholder.

    Layers skip real placeholders, so a log line like ``<REDACTED:FAKE_KEY_VALUE>``
    could otherwise hide a secret from them.
    """
    return text.replace(FORGED_PREFIX, DISARMED_PREFIX)


def sub_outside_placeholders(
    pattern: re.Pattern[str],
    replace: Callable[[re.Match[str]], str],
    text: str,
) -> str:
    """Apply ``pattern`` to the text between placeholders, leaving placeholders intact."""
    parts = _PLACEHOLDER_SPLIT.split(text)
    # re.split with one capture group puts the placeholders at the odd positions.
    parts[0::2] = [pattern.sub(replace, part) for part in parts[0::2]]
    return "".join(parts)
