"""Tests for the Rich rendering of a plan."""

from pathlib import Path

from rich.console import Console

from deploy_agent.models import (
    DeploymentPlan,
    Environment,
    PlanStatus,
    PlanStep,
    PlanTarget,
    PolicyReason,
    ProjectInfo,
    SafetyTier,
)
from deploy_agent.planner import build_plan, render_plan
from deploy_agent.planner.render import NOTHING_RUN
from deploy_agent.preflight import build_context, run_preflight

FIXTURES = Path(__file__).parent.parent / "fixtures" / "projects"


def text_of(plan: DeploymentPlan) -> str:
    console = Console(width=200, record=True, color_system=None)
    console.print(render_plan(plan))
    return console.export_text()


def plan_for(name: str, target: PlanTarget | None = None) -> DeploymentPlan:
    context = build_context(FIXTURES / name)
    return build_plan(context.project, run_preflight(context), target)


def test_ready_plan_shows_header_steps_and_tiers() -> None:
    output = text_of(plan_for("python_app"))

    assert "Deployment plan: READY FOR REVIEW" in output
    assert "placeholder (staging)" in output
    assert "not a real provider yet" in output
    assert "python fastapi" in output
    assert "Run database migrations with alembic" in output
    assert "AUTO" in output
    assert "NEEDS APPROVAL" in output
    assert "Not reversible" in output
    assert "Blocked:" not in output


def test_blocked_plan_shows_blockers_with_evidence_and_fix() -> None:
    output = text_of(plan_for("broken_app"))

    assert "Deployment plan: BLOCKED" in output
    assert "Blocked: fix these preflight errors before deploying." in output
    assert "dockerfile_base_image" in output
    assert "Fix:" in output


def test_warnings_are_shown() -> None:
    output = text_of(plan_for("python_app"))

    assert "Warnings worth a look:" in output
    assert "dockerfile_non_root" in output


def test_every_plan_says_nothing_was_run() -> None:
    assert NOTHING_RUN in text_of(plan_for("preflight_pass"))


def test_production_plan_shows_promote_step() -> None:
    output = text_of(plan_for("python_app", PlanTarget(environment=Environment.PRODUCTION)))

    assert "placeholder (production)" in output
    assert "to production" in output


def test_named_target_has_no_placeholder_note() -> None:
    output = text_of(plan_for("python_app", PlanTarget(name="sandbox")))

    assert "sandbox (staging)" in output
    assert "not a real provider yet" not in output


def test_forbidden_tier_is_rendered() -> None:
    step = PlanStep(
        number=1,
        kind="unknown_thing",
        what="Something odd",
        changes="Unknown",
        tier=SafetyTier.FORBIDDEN,
        policy_reason=PolicyReason.UNKNOWN_ACTION,
        reversible=False,
    )
    plan = DeploymentPlan(
        target=PlanTarget(),
        project=ProjectInfo(language="python"),
        status=PlanStatus.READY_FOR_REVIEW,
        steps=(step,),
    )

    assert "FORBIDDEN" in text_of(plan)


def test_rich_markup_in_text_is_shown_literally() -> None:
    step = PlanStep(
        number=1,
        kind="read_file",
        what="Read [bold red]config[/bold red]",
        changes="Nothing [link=http://evil.invalid]click[/link]",
        tier=SafetyTier.AUTO,
        policy_reason=PolicyReason.CATALOG_RULE,
        reversible=True,
        undo_instructions="Nothing to undo",
    )
    plan = DeploymentPlan(
        target=PlanTarget(),
        project=ProjectInfo(language="python"),
        status=PlanStatus.READY_FOR_REVIEW,
        steps=(step,),
    )

    output = text_of(plan)

    assert "[bold red]config[/bold red]" in output
    assert "[link=http://evil.invalid]click[/link]" in output
