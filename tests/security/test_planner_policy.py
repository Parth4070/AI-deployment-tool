"""The planner must take every tier from the policy engine and never loosen it."""

from pathlib import Path

import pytest

from deploy_agent.models import (
    DeploymentPlan,
    DeploymentTarget,
    Environment,
    PlanTarget,
    PreflightReport,
    ProjectInfo,
    ProposedAction,
    SafetyTier,
)
from deploy_agent.planner import build_plan
from deploy_agent.planner.builder import StepDraft, classify
from deploy_agent.policy import evaluate
from deploy_agent.preflight import build_context, run_preflight

FIXTURES = Path(__file__).parent.parent / "fixtures" / "projects"
ALL_FIXTURES = ["python_app", "node_app", "broken_app", "preflight_pass", "preflight_fail"]


def all_plans() -> list[DeploymentPlan]:
    plans = []
    for name in ALL_FIXTURES:
        context = build_context(FIXTURES / name)
        report = run_preflight(context)
        for environment in Environment:
            plans.append(build_plan(context.project, report, PlanTarget(environment=environment)))
    return plans


@pytest.mark.parametrize("plan", all_plans())
def test_every_tier_matches_the_policy_engine(plan: DeploymentPlan) -> None:
    for step in plan.steps:
        decision = evaluate(ProposedAction(kind=step.kind, description=step.what))
        assert step.tier is decision.tier, step.kind
        assert step.policy_reason is decision.reason, step.kind


@pytest.mark.parametrize("plan", all_plans())
def test_no_fixture_plan_contains_a_forbidden_or_manual_step(plan: DeploymentPlan) -> None:
    assert all(step.tier in (SafetyTier.AUTO, SafetyTier.NEEDS_APPROVAL) for step in plan.steps)


@pytest.mark.parametrize("plan", all_plans())
def test_every_step_that_changes_the_target_needs_approval(plan: DeploymentPlan) -> None:
    changing = {"set_target_env_names", "run_migrations", "deploy_release", "promote_to_production"}
    for step in plan.steps:
        if step.kind in changing:
            assert step.tier is SafetyTier.NEEDS_APPROVAL, step.kind


def test_unknown_step_kind_comes_out_forbidden() -> None:
    draft = StepDraft(
        kind="teleport_server", what="Move it", changes="Everything", reversible=False
    )

    assert classify(draft, 1).tier is SafetyTier.FORBIDDEN


def test_destructive_wording_comes_out_forbidden_even_for_a_known_kind() -> None:
    draft = StepDraft(
        kind="deploy_release",
        what="Deploy and drop the old database",
        changes="Everything",
        reversible=False,
    )

    assert classify(draft, 1).tier is SafetyTier.FORBIDDEN


def test_hostile_health_path_cannot_loosen_the_tier() -> None:
    """A health path is user input that ends up in a step description."""
    target = PlanTarget(requirements=DeploymentTarget(health_check_path="/purge-all"))

    plan = build_plan(ProjectInfo(language="python"), PreflightReport(results=()), target)

    health = next(step for step in plan.steps if step.kind == "verify_health")
    assert health.tier is SafetyTier.FORBIDDEN
