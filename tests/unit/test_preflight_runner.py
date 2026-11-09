"""Tests for the preflight runner, registry, models and evidence helpers."""

import pytest
from pydantic import ValidationError

from deploy_agent.models import DeploymentTarget, PreflightReport, PreflightResult, Severity
from deploy_agent.preflight import PreflightContext, run_preflight
from deploy_agent.preflight.evidence import failed, listing, passed, skipped
from deploy_agent.preflight.registry import ALL_CHECKS


def ok_check(context: PreflightContext) -> PreflightResult:
    return passed("ok_check")


def broken_check(context: PreflightContext) -> PreflightResult:
    raise ValueError("fake-secret-in-exception-message")


class TestRunner:
    def test_runs_given_checks_in_order(self, make_context) -> None:
        report = run_preflight(make_context({}), [ok_check, ok_check])

        assert [result.check_name for result in report.results] == ["ok_check", "ok_check"]

    def test_crashing_check_becomes_failure_without_message(self, make_context) -> None:
        report = run_preflight(make_context({}), [broken_check, ok_check])

        crashed, still_ran = report.results
        assert crashed.check_name == "broken_check"
        assert not crashed.passed
        assert crashed.severity == Severity.ERROR
        assert "ValueError" in (crashed.evidence or "")
        assert "fake-secret" not in crashed.model_dump_json()
        assert still_ran.passed

    def test_default_runs_registry(self, make_context) -> None:
        report = run_preflight(make_context({}))

        assert len(report.results) == len(ALL_CHECKS)


class TestRegistry:
    def test_names_are_unique(self) -> None:
        names = [check.__name__ for check in ALL_CHECKS]
        assert len(names) == len(set(names))

    def test_each_check_reports_its_own_name(self, make_context) -> None:
        context = make_context({})
        for check in ALL_CHECKS:
            assert check(context).check_name == check.__name__


class TestReport:
    def test_has_errors_only_for_failed_errors(self) -> None:
        warning = failed("a", Severity.WARNING, "evidence", "fix")
        error = failed("b", Severity.ERROR, "evidence", "fix")

        assert not PreflightReport(results=(passed("c"), warning)).has_errors
        assert PreflightReport(results=(warning, error)).has_errors
        assert PreflightReport(results=(warning, error)).failures == (warning, error)


class TestTarget:
    def test_all_fields_optional(self) -> None:
        assert DeploymentTarget().provided_env_names is None

    def test_rejects_bad_env_name(self) -> None:
        with pytest.raises(ValidationError):
            DeploymentTarget(provided_env_names=("NOT A NAME",))

    def test_rejects_health_path_with_spaces(self) -> None:
        with pytest.raises(ValidationError):
            DeploymentTarget(health_check_path="/health check")


class TestEvidence:
    def test_skipped_is_a_pass_with_reason(self) -> None:
        result = skipped("x", "no Dockerfile")
        assert result.passed and result.evidence == "Skipped: no Dockerfile"

    def test_listing_cuts_long_lists(self) -> None:
        assert listing(range(3)) == "0, 1, 2"
        assert listing(range(12), limit=2) == "0, 1 (+10 more)"
