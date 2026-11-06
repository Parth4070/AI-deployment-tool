"""The retry budget: the same fix for the same failure cannot be tried forever.

The budget only counts. The policy engine reads it; the caller records an attempt when an
action actually runs. Counts live in memory for now and will move to the audit log once
``state/`` exists.
"""

from deploy_agent.policy.rules import normalize_kind, retry_limit


class RetryBudget:
    """Counts attempts for each (failure, action kind) pair."""

    def __init__(self) -> None:
        self._attempts: dict[tuple[str, str], int] = {}

    @staticmethod
    def _key(failure_signature: str, kind: str) -> tuple[str, str]:
        return (failure_signature.casefold(), normalize_kind(kind))

    def attempts(self, failure_signature: str, kind: str) -> int:
        return self._attempts.get(self._key(failure_signature, kind), 0)

    def record_attempt(self, failure_signature: str, kind: str) -> None:
        key = self._key(failure_signature, kind)
        self._attempts[key] = self._attempts.get(key, 0) + 1

    def is_exhausted(self, failure_signature: str, kind: str) -> bool:
        return self.attempts(failure_signature, kind) >= retry_limit(kind)
