"""Layer 2: high-randomness strings.

This layer guesses, so it leans toward removing too much. A random secret that is short,
or mixed in with ordinary words, can still get past it.
"""

import math
import re
from collections import Counter

from deploy_agent.logs.redaction.placeholders import placeholder, sub_outside_placeholders

LABEL = "HIGH_ENTROPY"

MIN_TOKEN_LENGTH = 20
MIN_HEX_LENGTH = 32

# Bits per character. Tuned on the fixtures in tests/unit/test_redaction_entropy.py.
HEX_THRESHOLD = 3.0
WITH_DIGITS_THRESHOLD = 4.0
LETTERS_ONLY_THRESHOLD = 4.3  # higher, because long names are letters too

_TOKEN = re.compile(rf"[A-Za-z0-9+/_-]{{{MIN_TOKEN_LENGTH},}}={{0,2}}")
_HEX = re.compile(rf"[0-9a-fA-F]{{{MIN_HEX_LENGTH},}}")
_PUBLIC_DIGEST_PREFIX = re.compile(r"sha(?:1|256|384|512)-")
_DIGEST_LABEL_BEFORE = re.compile(r"sha(?:1|256|384|512):$")
_DIGEST_LOOKBACK = 7
_PIECE_SEPARATORS = re.compile(r"[/_.-]+")
_WORD_LIKE_PIECE = re.compile(r"[A-Z]?[a-z]+\d{0,4}|[A-Z]+\d{0,4}|\d+")


def shannon_entropy(text: str) -> float:
    """Average bits per character: higher means less predictable."""
    total = len(text)
    return -sum((n / total) * math.log2(n / total) for n in Counter(text).values())


def _is_public_digest(match: re.Match[str]) -> bool:
    """Image digests and lockfile hashes are public and useful, so they stay."""
    before = match.string[max(0, match.start() - _DIGEST_LOOKBACK) : match.start()]
    return (
        _DIGEST_LABEL_BEFORE.search(before) is not None
        or _PUBLIC_DIGEST_PREFIX.match(match.group()) is not None
    )


def _is_path_or_name(token: str) -> bool:
    pieces = [piece for piece in _PIECE_SEPARATORS.split(token) if piece]
    return all(_WORD_LIKE_PIECE.fullmatch(piece) for piece in pieces)


def _looks_random(token: str) -> bool:
    entropy = shannon_entropy(token)
    if _HEX.fullmatch(token):
        return entropy >= HEX_THRESHOLD
    if any(char.isdigit() for char in token):
        return entropy >= WITH_DIGITS_THRESHOLD
    return entropy >= LETTERS_ONLY_THRESHOLD


def redact_high_entropy(text: str) -> tuple[str, Counter[str]]:
    counts: Counter[str] = Counter()

    def replace(match: re.Match[str]) -> str:
        token = match.group()
        if _is_public_digest(match) or _is_path_or_name(token) or not _looks_random(token):
            return token
        counts[LABEL] += 1
        return placeholder(LABEL)

    return sub_outside_placeholders(_TOKEN, replace, text), counts
