"""Command-line entry point for deploy-agent."""

from importlib.metadata import version as package_version
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.text import Text

from deploy_agent.models import (
    DeploymentTarget,
    Environment,
    PlanStatus,
    PlanTarget,
    PreflightReport,
    PreflightResult,
    Severity,
)
from deploy_agent.planner import build_plan, render_plan
from deploy_agent.preflight import PreflightContext, build_context, run_preflight
from deploy_agent.scanner import ScanError

app = typer.Typer(help="Scan a project, plan a deployment, and explain failures.")

_OPTION_FOR_FIELD = {
    "runtime_version": "--runtime",
    "port": "--port",
    "health_check_path": "--health-path",
    "provided_env_names": "--env-name",
}


@app.callback()
def main() -> None:
    """Scan a project, plan a deployment, and explain failures."""


@app.command()
def version() -> None:
    """Show the installed deploy-agent version."""
    Console().print(
        f"deploy-agent {package_version('deploy-agent')}", markup=False, highlight=False
    )


def _status(result: PreflightResult) -> tuple[str, str]:
    if result.passed:
        if (result.evidence or "").startswith("Skipped"):
            return "SKIP", "dim"
        return "PASS", "green"
    return {
        Severity.ERROR: ("FAIL", "bold red"),
        Severity.WARNING: ("WARN", "yellow"),
    }.get(result.severity, ("NOTE", "cyan"))


def _print_report(console: Console, report: PreflightReport) -> None:
    # Text objects, never markup strings: evidence must not be read as Rich formatting.
    for result in report.results:
        label, style = _status(result)
        line = Text()
        line.append(f"{label:<5}", style=style)
        line.append(f" {result.check_name}")
        console.print(line, soft_wrap=True)
        if result.evidence:
            console.print(Text(f"      {result.evidence}"), soft_wrap=True)
        if result.suggested_fix:
            console.print(Text(f"      Fix: {result.suggested_fix}"), soft_wrap=True)

    labels = [_status(result)[0] for result in report.results]
    words = (("PASS", "passed"), ("SKIP", "skipped"), ("WARN", "warnings"), ("FAIL", "errors"))
    summary = ", ".join(f"{labels.count(label)} {word}" for label, word in words)
    console.print(Text(f"\n{len(labels)} checks: {summary}"), soft_wrap=True)


PathArg = Annotated[Path, typer.Argument(help="Project folder to check.")]
RuntimeOpt = Annotated[
    str | None, typer.Option("--runtime", help="Runtime version the target uses, e.g. 3.12.")
]
PortOpt = Annotated[int | None, typer.Option("--port", help="Port the target sends traffic to.")]
HealthPathOpt = Annotated[
    str | None, typer.Option("--health-path", help="Health-check path, e.g. /health.")
]
EnvNamesOpt = Annotated[
    list[str] | None,
    typer.Option(
        "--env-name",
        help="A variable NAME the target provides. Repeat for each. Never pass values.",
    ),
]


def _parse_target(
    console: Console,
    runtime: str | None,
    port: int | None,
    health_path: str | None,
    env_names: list[str] | None,
) -> DeploymentTarget:
    """Build the target from CLI options, or explain the bad option and exit with code 2."""
    try:
        return DeploymentTarget(
            runtime_version=runtime,
            port=port,
            health_check_path=health_path,
            provided_env_names=None if env_names is None else tuple(env_names),
        )
    except ValidationError as error:
        # Name the option, never the rejected text: it may be a value pasted by mistake.
        fields = sorted({str(issue["loc"][0]) for issue in error.errors() if issue["loc"]})
        options = ", ".join(_OPTION_FOR_FIELD.get(field, field) for field in fields)
        console.print(
            Text(
                f"Invalid input for {options}. Check the format: --runtime like 3.12, --port "
                "1-65535, --health-path like /health, --env-name like DATABASE_URL (a name "
                "only, no '=' or value)."
            ),
            soft_wrap=True,
        )
        raise typer.Exit(code=2) from None


def _load_context(console: Console, path: Path, target: DeploymentTarget) -> PreflightContext:
    """Scan the project folder, or explain why it cannot be used and exit with code 2."""
    try:
        return build_context(path, target)
    except ScanError as error:
        console.print(Text(str(error)), soft_wrap=True)
        raise typer.Exit(code=2) from None


@app.command()
def preflight(
    path: PathArg = Path("."),
    runtime: RuntimeOpt = None,
    port: PortOpt = None,
    health_path: HealthPathOpt = None,
    env_names: EnvNamesOpt = None,
) -> None:
    """Run rule-based checks before a deploy. Read-only: nothing is changed or deployed."""
    console = Console()
    target = _parse_target(console, runtime, port, health_path, env_names)
    report = run_preflight(_load_context(console, path, target))
    _print_report(console, report)
    raise typer.Exit(code=1 if report.has_errors else 0)


@app.command()
def plan(
    path: PathArg = Path("."),
    environment: Annotated[
        Environment,
        typer.Option("--environment", help="Where the release should end up."),
    ] = Environment.STAGING,
    runtime: RuntimeOpt = None,
    port: PortOpt = None,
    health_path: HealthPathOpt = None,
    env_names: EnvNamesOpt = None,
) -> None:
    """Show a deployment plan for review. Nothing is run, changed or deployed.

    The target is a placeholder until real providers are added.
    """
    console = Console()
    requirements = _parse_target(console, runtime, port, health_path, env_names)
    context = _load_context(console, path, requirements)
    deployment_plan = build_plan(
        context.project,
        run_preflight(context),
        PlanTarget(environment=Environment(environment), requirements=requirements),
    )
    console.print(render_plan(deployment_plan), soft_wrap=False)
    raise typer.Exit(code=1 if deployment_plan.status is PlanStatus.BLOCKED else 0)
