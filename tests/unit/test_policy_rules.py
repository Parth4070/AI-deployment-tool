"""Tests for the action catalog and the hard denylist."""

import pytest

from deploy_agent.models import SafetyTier
from deploy_agent.policy.denylist import DENYLISTED_KINDS, contains_banned_word, is_denylisted
from deploy_agent.policy.rules import (
    ACTION_CATALOG,
    DEFAULT_RETRY_LIMIT,
    UNKNOWN_ACTION_TIER,
    lookup_tier,
    normalize_kind,
    retry_limit,
    strictness,
)


class TestCatalog:
    @pytest.mark.parametrize(
        ("kind", "tier"),
        [
            ("run_preflight", SafetyTier.AUTO),
            ("read_logs", SafetyTier.AUTO),
            ("retry_network_timeout", SafetyTier.AUTO),
            ("clear_build_cache", SafetyTier.AUTO),
            ("edit_repo_file", SafetyTier.NEEDS_APPROVAL),
            ("change_runtime_version", SafetyTier.NEEDS_APPROVAL),
            ("create_paid_resource", SafetyTier.NEEDS_APPROVAL),
            ("change_iam_policy", SafetyTier.NEEDS_APPROVAL),
            ("change_dns_record", SafetyTier.NEEDS_APPROVAL),
            ("run_migrations", SafetyTier.NEEDS_APPROVAL),
            ("promote_to_production", SafetyTier.NEEDS_APPROVAL),
            ("restore_database", SafetyTier.MANUAL),
            ("open_port_to_internet", SafetyTier.MANUAL),
            ("change_billing", SafetyTier.MANUAL),
        ],
    )
    def test_tiers_follow_the_claude_md_table(self, kind: str, tier: SafetyTier) -> None:
        assert lookup_tier(kind) is tier

    def test_unknown_kind_has_no_catalog_tier(self) -> None:
        assert lookup_tier("launch_rockets") is None

    def test_unknown_actions_default_to_the_safest_tier(self) -> None:
        assert UNKNOWN_ACTION_TIER is SafetyTier.FORBIDDEN
        assert strictness(UNKNOWN_ACTION_TIER) == max(strictness(tier) for tier in SafetyTier)

    def test_catalog_cannot_be_changed_at_runtime(self) -> None:
        with pytest.raises(TypeError):
            ACTION_CATALOG["drop_database"] = SafetyTier.AUTO  # type: ignore[index]

    def test_no_catalog_entry_is_destructive(self) -> None:
        """A destructive action must live in the denylist, never in the catalog."""
        for kind in ACTION_CATALOG:
            assert not is_denylisted(kind, "harmless description"), kind

    def test_lookup_ignores_case_width_and_space(self) -> None:
        assert lookup_tier("  RUN_PREFLIGHT ") is SafetyTier.AUTO
        assert lookup_tier("ｒｕｎ_ｐｒｅｆｌｉｇｈｔ") is SafetyTier.AUTO

    def test_extra_text_after_a_known_kind_makes_it_unknown(self) -> None:
        assert lookup_tier("run_preflight; rm -rf /") is None

    def test_normalize_kind(self) -> None:
        assert normalize_kind(" Read_Logs ") == "read_logs"

    def test_tiers_are_ordered_from_loosest_to_strictest(self) -> None:
        order = [SafetyTier.AUTO, SafetyTier.NEEDS_APPROVAL, SafetyTier.MANUAL]
        order.append(SafetyTier.FORBIDDEN)
        assert [strictness(tier) for tier in order] == [0, 1, 2, 3]

    def test_retry_limits(self) -> None:
        assert retry_limit("retry_network_timeout") == 2
        assert retry_limit("edit_repo_file") == DEFAULT_RETRY_LIMIT == 1


class TestDenylist:
    @pytest.mark.parametrize("kind", sorted(DENYLISTED_KINDS))
    def test_every_listed_kind_is_denied(self, kind: str) -> None:
        assert is_denylisted(kind, "harmless description")

    @pytest.mark.parametrize(
        "text",
        [
            "delete the old volume",
            "DROP TABLE users",
            "destroy the stack",
            "truncate the logs table",
            "purge the bucket",
            "wipe the disk",
            "erase all records",
            "git push --force",
            "force-push to main",
            "rotate the API key",
            "revoke the token",
            "nuke it",
            "rm -rf /",
            "rmdir build",
        ],
    )
    def test_destructive_words_are_caught(self, text: str) -> None:
        assert contains_banned_word(text)

    @pytest.mark.parametrize(
        "text",
        [
            "dropdatabase",
            "safedelete",
            "ｄｒｏｐ the database",
            "dr​op the database",
            "de‍lete the volume",
            "DeLeTe",
            "drop_database",
        ],
    )
    def test_hidden_destructive_words_are_still_caught(self, text: str) -> None:
        assert contains_banned_word(text)

    @pytest.mark.parametrize(
        "text",
        ["read the logs", "run the preflight checks", "show the plan", "check port 8000"],
    )
    def test_harmless_text_is_not_flagged(self, text: str) -> None:
        assert not contains_banned_word(text)

    def test_destructive_description_denies_a_known_kind(self) -> None:
        assert is_denylisted("run_migrations", "Run migrations, then drop the old column")

    def test_errs_on_the_side_of_blocking(self) -> None:
        """'enforce' contains 'force'. Blocking a harmless action is the safe mistake."""
        assert contains_banned_word("enforce https")
