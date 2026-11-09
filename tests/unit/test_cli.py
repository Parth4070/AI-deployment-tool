"""Tests for the command-line interface."""

from importlib.metadata import version as package_version
from pathlib import Path

from rich.console import Console
from typer.testing import CliRunner

from deploy_agent.cli.main import _print_report, app
from deploy_agent.models import PreflightReport, Severity
from deploy_agent.preflight.evidence import failed

runner = CliRunner()


def test_version_prints_package_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"deploy-agent {package_version('deploy-agent')}"


def test_help_lists_version_command() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "version" in result.stdout


FIXTURES = Path(__file__).parent.parent / "fixtures" / "projects"


def test_preflight_good_project_exits_zero() -> None:
    result = runner.invoke(
        app,
        [
            "preflight",
            str(FIXTURES / "preflight_pass"),
            "--runtime",
            "3.12",
            "--port",
            "8000",
            "--health-path",
            "/health",
            "--env-name",
            "DATABASE_URL",
        ],
    )

    assert result.exit_code == 0
    assert "PASS  dockerfile_no_baked_secrets" in result.output
    assert "0 warnings, 0 errors" in result.output


def test_preflight_bad_project_exits_one_and_explains() -> None:
    result = runner.invoke(app, ["preflight", str(FIXTURES / "preflight_fail")])

    assert result.exit_code == 1
    assert "FAIL  dockerfile_no_baked_secrets" in result.output
    assert "API_TOKEN (line 4)" in result.output
    assert "Fix:" in result.output


def test_preflight_missing_folder_exits_two(tmp_path: Path) -> None:
    result = runner.invoke(app, ["preflight", str(tmp_path / "nope")])

    assert result.exit_code == 2
    assert "not an existing folder" in result.output


def test_report_prints_brackets_literally() -> None:
    """Evidence is printed as plain text, so [bold] can never act as Rich formatting."""
    report = PreflightReport(
        results=(failed("x", Severity.WARNING, "seen [bold]here[/bold]", "fix [red]it"),)
    )
    console = Console(record=True, width=200)
    _print_report(console, report)

    output = console.export_text()
    assert "seen [bold]here[/bold]" in output
    assert "Fix: fix [red]it" in output


def test_plan_ready_project_exits_zero() -> None:
    result = runner.invoke(
        app,
        [
            "plan",
            str(FIXTURES / "preflight_pass"),
            "--port",
            "8000",
            "--health-path",
            "/health",
            "--env-name",
            "DATABASE_URL",
        ],
    )

    assert result.exit_code == 0
    assert "READY FOR REVIEW" in result.output
    assert "Nothing has been run" in result.output


def test_plan_blocked_project_exits_one() -> None:
    result = runner.invoke(app, ["plan", str(FIXTURES / "preflight_fail")])

    assert result.exit_code == 1
    assert "BLOCKED" in result.output
    assert "dockerfile_no_baked_secrets" in result.output


def test_plan_production_adds_promote_step() -> None:
    result = runner.invoke(
        app, ["plan", str(FIXTURES / "python_app"), "--environment", "production"]
    )

    assert result.exit_code == 0
    assert "placeholder (production)" in result.output
    assert "Promote" in result.output


def test_plan_bad_environment_exits_two() -> None:
    result = runner.invoke(app, ["plan", str(FIXTURES / "python_app"), "--environment", "prod"])

    assert result.exit_code == 2


def test_plan_bad_option_names_option_not_value() -> None:
    pasted = "DATABASE_URL=postgres://u:fake-pw-9191@db/app"

    result = runner.invoke(app, ["plan", str(FIXTURES / "python_app"), "--env-name", pasted])

    assert result.exit_code == 2
    assert "--env-name" in result.output
    assert "fake-pw-9191" not in result.output


def test_plan_missing_folder_exits_two(tmp_path: Path) -> None:
    result = runner.invoke(app, ["plan", str(tmp_path / "nope")])

    assert result.exit_code == 2
