"""Layer 1: known secret formats, auth headers, and secret-looking assignments.

Token shapes follow the public gitleaks rules (https://github.com/gitleaks/gitleaks),
loosened where a provider could lengthen its tokens. Any new pattern needs a test.
"""

import re
from collections import Counter

from deploy_agent.logs.redaction.placeholders import placeholder, sub_outside_placeholders

_MAX_LABEL_LENGTH = 64

_PRIVATE_KEY = re.compile(
    r"-----BEGIN[ A-Z0-9_-]{0,100}PRIVATE KEY(?: BLOCK)?-----"
    r"[\s\S]*?"
    r"(?:-----END[ A-Z0-9_-]{0,100}PRIVATE KEY(?: BLOCK)?-----|\Z)"
)

# Order matters: more specific shapes come before ones that would also match them.
_FORMATS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("PRIVATE_KEY", _PRIVATE_KEY),
    ("AWS_ACCESS_KEY", re.compile(r"\b(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z2-7]{16}\b")),
    ("GITHUB_TOKEN", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("GITHUB_TOKEN", re.compile(r"\bgithub_pat_\w{22,}")),
    ("GITLAB_TOKEN", re.compile(r"\bglpat-[\w-]{20,}")),
    ("SLACK_TOKEN", re.compile(r"\bxox[a-z]-[A-Za-z0-9-]{10,}")),
    (
        "SLACK_WEBHOOK",
        re.compile(
            r"(?:https?://)?hooks\.slack\.com/(?:services|workflows|triggers)/[A-Za-z0-9+/]+"
        ),
    ),
    ("STRIPE_KEY", re.compile(r"\b[sr]k_(?:test|live|prod)_[A-Za-z0-9]{10,}")),
    ("ANTHROPIC_KEY", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("OPENAI_KEY", re.compile(r"\bsk-(?:proj-|svcacct-|admin-)[A-Za-z0-9_-]{20,}")),
    ("OPENAI_KEY", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("GOOGLE_API_KEY", re.compile(r"\bAIza[\w-]{35,}")),
    ("SENDGRID_KEY", re.compile(r"\bSG\.[\w-]{16,}\.[\w-]{16,}")),
    ("NPM_TOKEN", re.compile(r"\bnpm_[A-Za-z0-9]{36,}\b")),
    ("PYPI_TOKEN", re.compile(r"\bpypi-AgEIcHlwaS5vcmc[\w-]{50,}")),
    ("TWILIO_KEY", re.compile(r"\bSK[0-9a-fA-F]{32}\b")),
    ("DIGITALOCEAN_TOKEN", re.compile(r"\bdop_v1_[a-f0-9]{64}\b")),
    ("JWT", re.compile(r"\beyJ[\w-]{10,}\.eyJ[\w-]{10,}\.[\w-]*")),
)

_AUTH_SCHEMES = frozenset({"bearer", "basic", "token", "digest"})
_AUTH_HEADER = re.compile(
    r"\b(?P<prefix>(?:proxy-)?authorization[\"']?\s*[:=]\s*[\"']?"
    r"(?P<scheme>[A-Za-z][A-Za-z0-9-]*\s+)?)"
    r"(?P<value>[^\s\"',;]+)",
    re.IGNORECASE,
)
_COOKIE_HEADER = re.compile(
    r"\b(?P<prefix>(?:set-)?cookie[\"']?\s*:\s*[\"']?)(?P<value>[^\r\n]+)",
    re.IGNORECASE,
)

_NAME_PART = r"[A-Za-z0-9_.-]{0,40}"
_SECRET_WORDS = (
    r"password|passwd|passphrase|secret|credentials?"
    r"|api[_-]?key|access[_-]?key|private[_-]?key"
    r"|(?:auth|access|refresh|id|session)[_-]?token"
)
_SHORT_WORDS = r"pass|pwd|token"
_ASSIGNMENT = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    rf"(?P<key>{_NAME_PART}(?:{_SECRET_WORDS}){_NAME_PART}"
    rf"|(?:[A-Za-z0-9]+[_.-])*(?:{_SHORT_WORDS})(?:[_.-][A-Za-z0-9]+)*)"
    r"\\?[\"']?\s*(?:=>|:=|=|:)\s*"
    r"(?:"
    r"\\\"(?P<escaped>[^\"\n]*?)\\\""
    r"|\"(?P<double>(?:[^\"\\\n]|\\.)*)\""
    r"|'(?P<single>(?:[^'\\\n]|\\.)*)'"
    r"|(?P<bare>[^\s,;&\"'`)}\]<>]+)"
    r")",
    re.IGNORECASE,
)
_VALUE_GROUPS = ("escaped", "double", "single", "bare")

_NON_SECRET_WORDS = frozenset({"", "none", "null", "nil", "undefined", "true", "false"})
_NON_SECRET_SHAPE = re.compile(
    r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?"  # a reference to a variable, not its value
    r"|\*+"  # already masked
    r"|\d{1,5}"  # a count or a port, such as token_count: 512
)


def _is_non_secret(value: str) -> bool:
    return value.lower() in _NON_SECRET_WORDS or _NON_SECRET_SHAPE.fullmatch(value) is not None


def _label_from_key(key: str) -> str:
    cleaned = re.sub(r"[^A-Z0-9]+", "_", key.upper()).strip("_")
    return cleaned[:_MAX_LABEL_LENGTH]


def _replace_formats(text: str, counts: Counter[str]) -> str:
    for label, pattern in _FORMATS:

        def replace(_: re.Match[str], label: str = label) -> str:
            counts[label] += 1
            return placeholder(label)

        text = sub_outside_placeholders(pattern, replace, text)
    return text


def _replace_headers(text: str, counts: Counter[str]) -> str:
    def replace_auth(match: re.Match[str]) -> str:
        # "Bearer " right before a placeholder parses as a value. It is not a secret.
        if match["scheme"] is None and match["value"].lower() in _AUTH_SCHEMES:
            return match.group()
        counts["AUTHORIZATION"] += 1
        return f"{match['prefix']}{placeholder('AUTHORIZATION')}"

    def replace_cookie(match: re.Match[str]) -> str:
        counts["COOKIE"] += 1
        return f"{match['prefix']}{placeholder('COOKIE')}"

    text = sub_outside_placeholders(_AUTH_HEADER, replace_auth, text)
    return sub_outside_placeholders(_COOKIE_HEADER, replace_cookie, text)


def _replace_assignments(text: str, counts: Counter[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        group = next(name for name in _VALUE_GROUPS if match[name] is not None)
        if _is_non_secret(match[group]):
            return match.group()
        label = _label_from_key(match["key"])
        counts[label] += 1
        whole = match.string
        before = whole[match.start() : match.start(group)]
        after = whole[match.end(group) : match.end()]
        return f"{before}{placeholder(label)}{after}"

    return sub_outside_placeholders(_ASSIGNMENT, replace, text)


def redact_patterns(text: str) -> tuple[str, Counter[str]]:
    counts: Counter[str] = Counter()
    text = _replace_formats(text, counts)
    text = _replace_headers(text, counts)
    text = _replace_assignments(text, counts)
    return text, counts
