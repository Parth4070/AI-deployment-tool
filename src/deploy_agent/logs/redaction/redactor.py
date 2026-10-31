"""Runs the redaction layers in order and fails closed.

Secret values are not sent onward by design, and this is tested, but the layers that
guess can miss things. See tests/security/test_redaction_known_gaps.py.
"""

from collections import Counter
from collections.abc import Iterable

from deploy_agent.logs.redaction.connection_strings import redact_connection_strings
from deploy_agent.logs.redaction.entropy import redact_high_entropy
from deploy_agent.logs.redaction.known_values import compile_known_secrets, redact_known_values
from deploy_agent.logs.redaction.models import (
    Finding,
    KnownSecret,
    RedactionLayer,
    RedactionResult,
)
from deploy_agent.logs.redaction.patterns import redact_patterns
from deploy_agent.logs.redaction.placeholders import disarm_forged_placeholders


class RedactionError(RuntimeError):
    """Redaction failed, so no text is available. Holds no input text."""


def _findings_for(layer: RedactionLayer, counts: Counter[str]) -> list[Finding]:
    return [
        Finding(layer=layer, label=label, count=count) for label, count in sorted(counts.items())
    ]


class Redactor:
    """Removes secrets from text. Create once, then call ``redact`` for each piece of text.

    Pass complete text. A value cut in two by separate calls is not matched.
    """

    def __init__(self, known_secrets: Iterable[KnownSecret] = ()) -> None:
        self._compiled = compile_known_secrets(known_secrets)

    def _run_layers(self, text: str) -> RedactionResult:
        # Surest layers first, so a value gets its exact name before a layer that guesses.
        text = disarm_forged_placeholders(text)
        text, known = redact_known_values(text, self._compiled)
        text, connections = redact_connection_strings(text)
        text, patterns = redact_patterns(text)
        text, entropy = redact_high_entropy(text)
        return RedactionResult(
            text=text,
            findings=(
                *_findings_for(RedactionLayer.KNOWN_VALUE, known),
                *_findings_for(RedactionLayer.CONNECTION_STRING, connections),
                *_findings_for(RedactionLayer.PATTERN, patterns),
                *_findings_for(RedactionLayer.ENTROPY, entropy),
            ),
        )

    def redact(self, text: str) -> RedactionResult:
        result: RedactionResult | None
        try:
            result = self._run_layers(text)
        except Exception:
            result = None
        # Raised outside the except block so the original error, which could quote
        # the input, is not attached to this one.
        if result is None:
            raise RedactionError(
                "Redaction failed, so the text was withheld rather than shown unredacted. "
                "Try again; if it keeps failing, report it as a bug."
            )
        return result
