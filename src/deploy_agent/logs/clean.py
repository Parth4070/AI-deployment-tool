"""Turns raw log text into cleaned text that is safe to match, quote and show.

Order matters: terminal codes are removed before redaction, because a color code in the
middle of a secret would hide it from the redactor.
"""

import re

from deploy_agent.logs.redaction import Finding, Redactor
from deploy_agent.models.common import StrictModel

# Terminal control sequences: colors and cursor moves (CSI), and window titles or links (OSC).
_CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_OTHER_ESCAPE = re.compile(r"\x1b[@-_]?")


class CleanLog(StrictModel):
    """Log text after cleaning and redaction. The only input the matcher accepts.

    ``findings`` says what the redactor removed (layer, kind, count), never the values.
    """

    text: str
    findings: tuple[Finding, ...]


def strip_terminal_codes(text: str) -> str:
    text = _OSC.sub("", text)
    text = _CSI.sub("", text)
    return _OTHER_ESCAPE.sub("", text)


def normalize_newlines(text: str) -> str:
    """Windows endings and lone carriage returns (progress bars) become plain newlines."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def clean_log(raw_text: str, redactor: Redactor) -> CleanLog:
    """Clean and redact a whole log. Raises RedactionError, with no text, if redaction fails.

    Pass the complete log in one call: a secret split between two calls is not matched.
    """
    text = normalize_newlines(strip_terminal_codes(raw_text))
    result = redactor.redact(text)
    return CleanLog(text=result.text, findings=result.findings)
