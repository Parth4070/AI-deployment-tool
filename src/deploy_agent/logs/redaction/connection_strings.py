"""Layer 4: remove the password from connection strings, keeping the useful parts.

The scheme, username, host and database stay, because they help explain a failure.
"""

import re
from collections import Counter

from deploy_agent.logs.redaction.placeholders import placeholder, sub_outside_placeholders

DEFAULT_LABEL = "CONNECTION_PASSWORD"

# The password is greedy, so it runs to the last @ and survives an unencoded @ or /.
# The lookbehind and the length cap on the scheme keep matching time linear: without them,
# a long run of letters is rescanned from every position.
_CONNECTION_STRING = re.compile(
    r"(?<![a-zA-Z0-9+.-])"
    r"(?P<prefix>[a-zA-Z][a-zA-Z0-9+.-]{0,30}://(?P<user>[^\s:/?#@'\"`<>]{0,256}):)"
    r"(?P<password>[^\s'\"`<>]{1,512})"
    r"(?=@)"
)

_KEY_BEFORE_VALUE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)[\"']?\s*[=:]\s*[\"']?$")
_CONNECTION_KEY_WORDS = re.compile(r"url|uri|dsn|conn|database", re.IGNORECASE)
_PORT_THEN_PATH = re.compile(r"\d{1,5}/")
_KEY_LOOKBACK = 80
_MAX_LABEL_LENGTH = 64


def _is_host_port_path(user: str, password: str) -> bool:
    """Recognise ``host:443/@scope/pkg``, where nothing before the @ is a credential."""
    looks_like_host = "." in user or user == "localhost"
    return looks_like_host and _PORT_THEN_PATH.match(password) is not None


def _label_for(match: re.Match[str]) -> str:
    before = match.string[max(0, match.start() - _KEY_LOOKBACK) : match.start()]
    key = _KEY_BEFORE_VALUE.search(before)
    if key is not None and _CONNECTION_KEY_WORDS.search(key.group(1)):
        return key.group(1).upper()[:_MAX_LABEL_LENGTH]
    return DEFAULT_LABEL


def redact_connection_strings(text: str) -> tuple[str, Counter[str]]:
    counts: Counter[str] = Counter()

    def replace(match: re.Match[str]) -> str:
        if _is_host_port_path(match["user"], match["password"]):
            return match.group()
        label = _label_for(match)
        counts[label] += 1
        return f"{match['prefix']}{placeholder(label)}"

    return sub_outside_placeholders(_CONNECTION_STRING, replace, text), counts
