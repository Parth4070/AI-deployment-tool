"""Command-line entry point for deploy-agent."""

from importlib.metadata import version as package_version

import typer
from rich.console import Console

app = typer.Typer(help="Scan a project, plan a deployment, and explain failures.")


@app.callback()
def main() -> None:
    """Scan a project, plan a deployment, and explain failures."""


@app.command()
def version() -> None:
    """Show the installed deploy-agent version."""
    Console().print(
        f"deploy-agent {package_version('deploy-agent')}", markup=False, highlight=False
    )
