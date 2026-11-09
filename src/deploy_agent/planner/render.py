"""Turns a deployment plan into Rich output a person can read.

Builds renderables only; the caller prints them. Every piece of text is a Rich ``Text``
object, never a markup string, so text from a project cannot be read as formatting.
"""

from rich import box
from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from deploy_agent.models.common import SafetyTier
from deploy_agent.models.plan import DeploymentPlan, PlanStatus
from deploy_agent.models.preflight import PreflightResult

TIER_LABELS: dict[SafetyTier, tuple[str, str]] = {
    SafetyTier.AUTO: ("AUTO", "green"),
    SafetyTier.NEEDS_APPROVAL: ("NEEDS APPROVAL", "yellow"),
    SafetyTier.MANUAL: ("MANUAL", "magenta"),
    SafetyTier.FORBIDDEN: ("FORBIDDEN", "bold red"),
}

STATUS_LABELS: dict[PlanStatus, tuple[str, str]] = {
    PlanStatus.READY_FOR_REVIEW: ("READY FOR REVIEW", "bold green"),
    PlanStatus.BLOCKED: ("BLOCKED", "bold red"),
}

NOTHING_RUN = "This is a plan only. Nothing has been run, changed or deployed."


def _header(plan: DeploymentPlan) -> Text:
    label, style = STATUS_LABELS[plan.status]
    project = plan.project
    stack = " ".join(
        part for part in (project.language, project.framework, project.runtime_version) if part
    )
    header = Text()
    header.append("Deployment plan: ", style="bold")
    header.append(label, style=style)
    header.append(f"\nTarget:  {plan.target.name} ({plan.target.environment})")
    if plan.target.name == "placeholder":
        header.append("  - not a real provider yet", style="dim")
    header.append(f"\nProject: {stack}")
    return header


def _steps_table(plan: DeploymentPlan) -> Table:
    table = Table(box=box.SIMPLE_HEAD, show_lines=False, expand=False)
    for column in ("#", "Step", "What it changes", "Tier", "Undo"):
        table.add_column(column, overflow="fold")
    for step in plan.steps:
        tier_label, tier_style = TIER_LABELS[step.tier]
        undo = (
            Text(step.undo_instructions)
            if step.undo_instructions is not None
            else Text("Not reversible", style="bold red")
        )
        table.add_row(
            Text(str(step.number)),
            Text(step.what),
            Text(step.changes),
            Text(tier_label, style=tier_style),
            undo,
        )
    return table


def _findings(title: str, style: str, items: tuple[PreflightResult, ...]) -> Text:
    text = Text(title, style=style)
    for item in items:
        text.append(f"\n  - {item.check_name}")
        if item.evidence:
            text.append(f"\n      {item.evidence}")
        if item.suggested_fix:
            text.append(f"\n      Fix: {item.suggested_fix}")
    return text


def render_plan(plan: DeploymentPlan) -> RenderableType:
    """The whole plan: header, a table of steps, then blockers and warnings."""
    parts: list[RenderableType] = [_header(plan), _steps_table(plan)]
    if plan.blockers:
        parts.append(
            _findings(
                "Blocked: fix these preflight errors before deploying.",
                "bold red",
                plan.blockers,
            )
        )
    if plan.warnings:
        parts.append(_findings("Warnings worth a look:", "yellow", plan.warnings))
    parts.append(Text(f"\n{NOTHING_RUN}", style="dim"))
    return Group(*parts)
