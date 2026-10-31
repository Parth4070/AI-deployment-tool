"""Tests for the command-line interface."""

from importlib.metadata import version as package_version

from typer.testing import CliRunner

from deploy_agent.cli.main import app

runner = CliRunner()


def test_version_prints_package_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"deploy-agent {package_version('deploy-agent')}"


def test_help_lists_version_command() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "version" in result.stdout
