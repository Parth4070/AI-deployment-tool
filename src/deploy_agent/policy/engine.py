"""The policy engine: decides the tier of a proposed action, using rules in code only.

Checks run in this order, and each one can only make the result stricter:

1. Hard denylist  -> forbidden, and nothing after it can change that.
2. Action catalog -> the listed tier, or forbidden when the kind is unknown.
3. Claimed tier   -> used only if it is stricter than the catalog tier.
4. Retry budget   -> manual (stop and get a person) when the budget is used up.
"""

from deploy_agent.models.common import SafetyTier
from deploy_agent.models.policy import PolicyDecision, PolicyReason, ProposedAction
from deploy_agent.policy.denylist import is_denylisted
from deploy_agent.policy.retry import RetryBudget
from deploy_agent.policy.rules import (
    RETRY_EXHAUSTED_TIER,
    UNKNOWN_ACTION_TIER,
    lookup_tier,
    normalize_kind,
    strictness,
)

# Fixed text only. A message never repeats the proposal, which may hold hostile text.
_MESSAGES: dict[PolicyReason, str] = {
    PolicyReason.DENYLISTED: (
        "Blocked: this is a destructive operation on the hard denylist. "
        "The agent will never run it. If it is really needed, do it yourself."
    ),
    PolicyReason.UNKNOWN_ACTION: (
        "Blocked: this action is not in the action catalog, so it is treated as forbidden. "
        "Add a reviewed rule for it if the agent should handle it."
    ),
    PolicyReason.CATALOG_RULE: "Tier set by the action catalog.",
    PolicyReason.STRICTER_CLAIM: (
        "Tier raised: the proposal asked for more caution than the catalog requires."
    ),
    PolicyReason.RETRY_BUDGET_EXHAUSTED: (
        "Stopped: this fix was already tried for this failure as many times as allowed. "
        "A person needs to look at it."
    ),
}


def _decision(
    tier: SafetyTier, reason: PolicyReason, matched_kind: str | None = None
) -> PolicyDecision:
    return PolicyDecision(
        tier=tier, reason=reason, matched_kind=matched_kind, message=_MESSAGES[reason]
    )


def evaluate(action: ProposedAction, budget: RetryBudget | None = None) -> PolicyDecision:
    """Decide the tier of one proposed action. Does not change the budget."""
    if is_denylisted(action.kind, action.description):
        return _decision(SafetyTier.FORBIDDEN, PolicyReason.DENYLISTED)

    catalog_tier = lookup_tier(action.kind)
    if catalog_tier is None:
        return _decision(UNKNOWN_ACTION_TIER, PolicyReason.UNKNOWN_ACTION)

    kind = normalize_kind(action.kind)
    tier, reason = catalog_tier, PolicyReason.CATALOG_RULE

    if action.claimed_tier is not None and strictness(action.claimed_tier) > strictness(tier):
        tier, reason = action.claimed_tier, PolicyReason.STRICTER_CLAIM

    if (
        budget is not None
        and action.failure_signature is not None
        and budget.is_exhausted(action.failure_signature, kind)
        and strictness(RETRY_EXHAUSTED_TIER) > strictness(tier)
    ):
        tier, reason = RETRY_EXHAUSTED_TIER, PolicyReason.RETRY_BUDGET_EXHAUSTED

    return _decision(tier, reason, matched_kind=kind)
