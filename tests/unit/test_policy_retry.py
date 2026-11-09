"""Tests for the retry budget."""

from deploy_agent.policy import RetryBudget


def test_new_budget_has_no_attempts() -> None:
    budget = RetryBudget()

    assert budget.attempts("port-in-use", "edit_repo_file") == 0
    assert not budget.is_exhausted("port-in-use", "edit_repo_file")


def test_default_limit_allows_one_attempt() -> None:
    budget = RetryBudget()
    budget.record_attempt("port-in-use", "edit_repo_file")

    assert budget.is_exhausted("port-in-use", "edit_repo_file")


def test_network_timeout_retry_allows_two_attempts() -> None:
    budget = RetryBudget()
    budget.record_attempt("network-timeout", "retry_network_timeout")
    assert not budget.is_exhausted("network-timeout", "retry_network_timeout")

    budget.record_attempt("network-timeout", "retry_network_timeout")
    assert budget.is_exhausted("network-timeout", "retry_network_timeout")


def test_each_failure_and_action_pair_has_its_own_budget() -> None:
    budget = RetryBudget()
    budget.record_attempt("port-in-use", "edit_repo_file")

    assert not budget.is_exhausted("missing-module", "edit_repo_file")
    assert not budget.is_exhausted("port-in-use", "change_runtime_version")


def test_spelling_tricks_share_one_budget() -> None:
    budget = RetryBudget()
    budget.record_attempt("Port-In-Use", " EDIT_REPO_FILE ")

    assert budget.attempts("port-in-use", "edit_repo_file") == 1
