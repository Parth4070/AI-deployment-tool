"""The action catalog: every action the agent knows, and its tier.

These rules are code on purpose. Changing one is a reviewed code change, never a prompt.
An action that is not listed here is unknown, and unknown actions are forbidden.
"""

import unicodedata
from collections.abc import Mapping
from types import MappingProxyType

from deploy_agent.models.common import SafetyTier

# Tier given to any action the catalog does not list. The safest tier, never auto.
UNKNOWN_ACTION_TIER = SafetyTier.FORBIDDEN

# Tier given when the retry budget for a failure is used up: stop and get a person.
RETRY_EXHAUSTED_TIER = SafetyTier.MANUAL

_STRICTNESS: Mapping[SafetyTier, int] = MappingProxyType(
    {
        SafetyTier.AUTO: 0,
        SafetyTier.NEEDS_APPROVAL: 1,
        SafetyTier.MANUAL: 2,
        SafetyTier.FORBIDDEN: 3,
    }
)

# From the tier table in CLAUDE.md. Destructive actions are not listed here: they live
# in the denylist, which is checked first and always wins.
ACTION_CATALOG: Mapping[str, SafetyTier] = MappingProxyType(
    {
        # Auto: read-only, or harmless and limited.
        "read_file": SafetyTier.AUTO,
        "scan_project": SafetyTier.AUTO,
        "run_preflight": SafetyTier.AUTO,
        "read_logs": SafetyTier.AUTO,
        "retry_network_timeout": SafetyTier.AUTO,
        "clear_build_cache": SafetyTier.AUTO,
        "build_artifact": SafetyTier.AUTO,  # local build only; nothing on the target changes
        "verify_health": SafetyTier.AUTO,  # read-only request to the health-check path
        # Needs approval: show the exact change and how to undo it, then wait for yes.
        "edit_repo_file": SafetyTier.NEEDS_APPROVAL,
        "change_runtime_version": SafetyTier.NEEDS_APPROVAL,
        "create_paid_resource": SafetyTier.NEEDS_APPROVAL,
        "change_firewall_rule": SafetyTier.NEEDS_APPROVAL,
        "change_iam_policy": SafetyTier.NEEDS_APPROVAL,
        "change_dns_record": SafetyTier.NEEDS_APPROVAL,
        "run_migrations": SafetyTier.NEEDS_APPROVAL,
        "promote_to_production": SafetyTier.NEEDS_APPROVAL,
        "set_target_env_names": SafetyTier.NEEDS_APPROVAL,  # changes target config
        "deploy_release": SafetyTier.NEEDS_APPROVAL,  # changes what is running
        # Manual only: explain and give steps, never execute.
        "restore_database": SafetyTier.MANUAL,
        "open_port_to_internet": SafetyTier.MANUAL,
        "change_billing": SafetyTier.MANUAL,
    }
)

# How many times one action may be tried for one failure before the agent must stop.
DEFAULT_RETRY_LIMIT = 1
RETRY_LIMITS: Mapping[str, int] = MappingProxyType(
    {
        "retry_network_timeout": 2,
    }
)


def normalize_kind(kind: str) -> str:
    """Fold width, case and surrounding space so look-alike spellings compare equal."""
    return unicodedata.normalize("NFKC", kind).strip().casefold()


def lookup_tier(kind: str) -> SafetyTier | None:
    """The catalog tier for an action kind, or None when the kind is unknown."""
    return ACTION_CATALOG.get(normalize_kind(kind))


def retry_limit(kind: str) -> int:
    return RETRY_LIMITS.get(normalize_kind(kind), DEFAULT_RETRY_LIMIT)


def strictness(tier: SafetyTier) -> int:
    """How strict a tier is: auto 0, needs approval 1, manual 2, forbidden 3."""
    return _STRICTNESS[tier]
