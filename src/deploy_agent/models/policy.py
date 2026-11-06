"""Policy models: an action someone proposes, and the policy engine's decision about it.

A proposal can come from the AI, so every field in it is untrusted. The decision is built
only by the policy engine, from rules in code.
"""

from enum import StrEnum
from typing import Annotated

from pydantic import StringConstraints

from deploy_agent.models.common import Label, NonBlankText, SafetyTier, StrictModel

# Loose on purpose: an unknown or hostile kind must reach the engine so it can be refused.
# A length cap keeps it from carrying much else.
ProposedKind = Annotated[str, StringConstraints(min_length=1, max_length=200)]
ProposedDescription = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]


class ProposedAction(StrictModel):
    """Something the agent might do. Untrusted: nothing here can loosen the policy.

    ``kind`` is looked up in the action catalog. ``claimed_tier`` can only make the result
    stricter. ``failure_signature`` is set when the action is an attempt to fix a known
    failure, so the retry budget can count attempts.
    """

    kind: ProposedKind
    description: ProposedDescription
    claimed_tier: SafetyTier | None = None
    failure_signature: Label | None = None


class PolicyReason(StrEnum):
    DENYLISTED = "denylisted"
    UNKNOWN_ACTION = "unknown_action"
    CATALOG_RULE = "catalog_rule"
    STRICTER_CLAIM = "stricter_claim"
    RETRY_BUDGET_EXHAUSTED = "retry_budget_exhausted"


class PolicyDecision(StrictModel):
    """The engine's answer. The message is fixed text and never repeats the proposal."""

    tier: SafetyTier
    reason: PolicyReason
    matched_kind: Label | None = None
    message: NonBlankText

    @property
    def may_execute(self) -> bool:
        """Only auto actions may run without a person saying yes."""
        return self.tier is SafetyTier.AUTO

    @property
    def needs_approval(self) -> bool:
        return self.tier is SafetyTier.NEEDS_APPROVAL
