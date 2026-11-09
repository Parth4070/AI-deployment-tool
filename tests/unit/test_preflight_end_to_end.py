"""Every check against two sample projects: one where all pass, one where all fail."""

from pathlib import Path

from deploy_agent.models import DeploymentTarget, PreflightReport
from deploy_agent.preflight import build_context, run_preflight
from deploy_agent.preflight.registry import ALL_CHECKS

FIXTURES = Path(__file__).parent.parent / "fixtures" / "projects"


def run(project: str, target: DeploymentTarget) -> PreflightReport:
    return run_preflight(build_context(FIXTURES / project, target))


def test_every_check_passes_on_the_good_project() -> None:
    target = DeploymentTarget(
        runtime_version="3.12",
        port=8000,
        health_check_path="/health",
        provided_env_names=("DATABASE_URL",),
    )
    report = run("preflight_pass", target)

    not_passed = [r.check_name for r in report.results if not r.passed]
    skipped = [r.check_name for r in report.results if (r.evidence or "").startswith("Skipped")]
    assert not_passed == []
    assert skipped == [], "every check should really run on this project, not be skipped"
    assert not report.has_errors


def test_every_check_fails_on_the_bad_project() -> None:
    target = DeploymentTarget(
        runtime_version="20",
        port=9000,
        health_check_path="/status",
        provided_env_names=(),
    )
    report = run("preflight_fail", target)

    still_passing = [r.check_name for r in report.results if r.passed]
    assert still_passing == []
    assert len(report.results) == len(ALL_CHECKS)
    assert report.has_errors
    for result in report.results:
        assert result.evidence and result.suggested_fix
