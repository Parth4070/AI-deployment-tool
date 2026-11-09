"""Tests for the policy engine's decisions."""

from typing import Any

import pytest
from pydantic import ValidationError

from deploy_agent.models import PolicyReason, ProposedAction, SafetyTier
from deploy_agent.policy import RetryBudget, evaluate


def proposal(**overrides: Any) -> ProposedAction:
    values: dict[str, Any] = {"kind": "run_preflight", "description": "Run the checks"}
    return ProposedAction(**(values | overrides))


class TestCatalogDecisions:
    def test_known_auto_action_may_execute(self) -> None:
        decision = evaluate(proposal())

        assert decision.tier is SafetyTier.AUTO
        assert decision.reason is PolicyReason.CATALOG_RULE
        assert decision.matched_kind == "run_preflight"
        assert decision.may_execute

    def test_approval_action_may_not_execute_on_its_own(self) -> None:
        decision = evaluate(proposal(kind="run_migrations", description="Apply migrations"))

        assert decision.tier is SafetyTier.NEEDS_APPROVAL
        assert decision.needs_approval
        assert not decision.may_execute

    def test_manual_action_may_not_execute(self) -> None:
        decision = evaluate(proposal(kind="open_port_to_internet", description="Open 5432"))

        assert decision.tier is SafetyTier.MANUAL
        assert not decision.may_execute
        assert not decision.needs_approval

    @pytest.mark.parametrize("tier", list(SafetyTier))
    def test_only_auto_may_execute(self, tier: SafetyTier) -> None:
        decision = evaluate(proposal(claimed_tier=tier))

        assert decision.may_execute is (decision.tier is SafetyTier.AUTO)


class TestUnknownActions:
    @pytest.mark.parametrize(
        "kind", ["launch_rockets", "run_preflight_and_more", "read logs", "x", "auto"]
    )
    def test_unknown_action_is_forbidden(self, kind: str) -> None:
        decision = evaluate(proposal(kind=kind))

        assert decision.tier is SafetyTier.FORBIDDEN
        assert decision.reason is PolicyReason.UNKNOWN_ACTION
        assert decision.matched_kind is None
        assert not decision.may_execute

    def test_unknown_action_claiming_auto_is_still_forbidden(self) -> None:
        decision = evaluate(proposal(kind="launch_rockets", claimed_tier=SafetyTier.AUTO))

        assert decision.tier is SafetyTier.FORBIDDEN
        assert not decision.may_execute


class TestDenylistDecisions:
    def test_denylisted_kind_is_forbidden(self) -> None:
        decision = evaluate(proposal(kind="drop_database"))

        assert decision.tier is SafetyTier.FORBIDDEN
        assert decision.reason is PolicyReason.DENYLISTED

    def test_destructive_description_on_a_known_kind_is_forbidden(self) -> None:
        decision = evaluate(proposal(kind="edit_repo_file", description="Delete the tests folder"))

        assert decision.tier is SafetyTier.FORBIDDEN
        assert decision.reason is PolicyReason.DENYLISTED

    def test_denylist_wins_over_retry_budget(self) -> None:
        budget = RetryBudget()
        budget.record_attempt("disk-full", "wipe_data")

        decision = evaluate(proposal(kind="wipe_data", failure_signature="disk-full"), budget)

        assert decision.reason is PolicyReason.DENYLISTED


class TestClaimedTier:
    @pytest.mark.parametrize(
        "claimed", [SafetyTier.NEEDS_APPROVAL, SafetyTier.MANUAL, SafetyTier.FORBIDDEN]
    )
    def test_stricter_claim_is_used(self, claimed: SafetyTier) -> None:
        decision = evaluate(proposal(claimed_tier=claimed))

        assert decision.tier is claimed
        assert decision.reason is PolicyReason.STRICTER_CLAIM

    @pytest.mark.parametrize("claimed", [SafetyTier.AUTO, SafetyTier.NEEDS_APPROVAL])
    def test_looser_or_equal_claim_is_ignored(self, claimed: SafetyTier) -> None:
        decision = evaluate(
            proposal(kind="restore_database", description="Restore it", claimed_tier=claimed)
        )

        assert decision.tier is SafetyTier.MANUAL
        assert decision.reason is PolicyReason.CATALOG_RULE


class TestRetryBudget:
    def test_first_attempt_keeps_the_catalog_tier(self) -> None:
        decision = evaluate(
            proposal(kind="edit_repo_file", description="Fix port", failure_signature="port"),
            RetryBudget(),
        )

        assert decision.tier is SafetyTier.NEEDS_APPROVAL

    def test_used_up_budget_stops_and_escalates(self) -> None:
        budget = RetryBudget()
        budget.record_attempt("port", "edit_repo_file")

        decision = evaluate(
            proposal(kind="edit_repo_file", description="Fix port", failure_signature="port"),
            budget,
        )

        assert decision.tier is SafetyTier.MANUAL
        assert decision.reason is PolicyReason.RETRY_BUDGET_EXHAUSTED
        assert not decision.may_execute

    def test_auto_retry_is_stopped_after_its_limit(self) -> None:
        budget = RetryBudget()
        action = proposal(
            kind="retry_network_timeout", description="Retry", failure_signature="timeout"
        )

        budget.record_attempt("timeout", "retry_network_timeout")
        assert evaluate(action, budget).may_execute

        budget.record_attempt("timeout", "retry_network_timeout")
        assert not evaluate(action, budget).may_execute

    def test_evaluate_does_not_spend_the_budget(self) -> None:
        budget = RetryBudget()
        action = proposal(kind="edit_repo_file", description="Fix", failure_signature="port")

        for _ in range(5):
            evaluate(action, budget)

        assert budget.attempts("port", "edit_repo_file") == 0

    def test_budget_does_not_loosen_a_stricter_tier(self) -> None:
        budget = RetryBudget()
        budget.record_attempt("x", "run_preflight")

        decision = evaluate(
            proposal(claimed_tier=SafetyTier.FORBIDDEN, failure_signature="x"), budget
        )

        assert decision.tier is SafetyTier.FORBIDDEN

    def test_no_failure_signature_means_no_budget_check(self) -> None:
        budget = RetryBudget()
        budget.record_attempt("port", "edit_repo_file")

        decision = evaluate(proposal(kind="edit_repo_file", description="Fix"), budget)

        assert decision.tier is SafetyTier.NEEDS_APPROVAL


class TestProposalModel:
    def test_blank_kind_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            proposal(kind="")

    def test_overlong_kind_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            proposal(kind="a" * 201)

    def test_unknown_field_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            proposal(approved_by="admin")

    def test_decision_cannot_be_changed_after_creation(self) -> None:
        decision = evaluate(proposal(kind="drop_database"))

        with pytest.raises(ValidationError):
            decision.tier = SafetyTier.AUTO
