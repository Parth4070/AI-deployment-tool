"""Tests for the plan builder, using the fixture projects."""

from pathlib import Path

import pytest

from deploy_agent.models import (
    DeploymentTarget,
    Environment,
    PlanStatus,
    PlanTarget,
    PreflightReport,
    ProjectInfo,
    SafetyTier,
)
from deploy_agent.models.plan import DeploymentPlan
from deploy_agent.planner import build_plan
from deploy_agent.planner.builder import MAX_NAMES_SHOWN, draft_steps
from deploy_agent.preflight import build_context, run_preflight

FIXTURES = Path(__file__).parent.parent / "fixtures" / "projects"
ALL_FIXTURES = ["python_app", "node_app", "broken_app", "preflight_pass", "preflight_fail"]


def plan_for(name: str, target: PlanTarget | None = None) -> DeploymentPlan:
    requirements = target.requirements if target else DeploymentTarget()
    context = build_context(FIXTURES / name, requirements)
    return build_plan(context.project, run_preflight(context), target)


def kinds(plan: DeploymentPlan) -> list[str]:
    return [step.kind for step in plan.steps]


class TestStepsFollowTheProject:
    def test_python_app_gets_the_full_staging_plan(self) -> None:
        plan = plan_for("python_app")

        assert kinds(plan) == [
            "run_preflight",
            "build_artifact",
            "set_target_env_names",
            "run_migrations",
            "deploy_release",
            "verify_health",
        ]

    @pytest.mark.parametrize(("name", "tool"), [("python_app", "alembic"), ("node_app", "prisma")])
    def test_migration_step_names_the_tool(self, name: str, tool: str) -> None:
        step = next(step for step in plan_for(name).steps if step.kind == "run_migrations")

        assert tool in step.what

    def test_no_migration_tool_means_no_migration_step(self) -> None:
        assert "run_migrations" not in kinds(plan_for("broken_app"))

    def test_no_env_names_means_no_env_step(self) -> None:
        project = ProjectInfo(language="python")

        assert "set_target_env_names" not in [d.kind for d in draft_steps(project, PlanTarget())]

    def test_env_step_lists_names_only(self) -> None:
        step = next(s for s in plan_for("python_app").steps if s.kind == "set_target_env_names")

        assert "5 environment variables" in step.what
        assert "DATABASE_URL" in step.what
        assert "SECRET_KEY" in step.what

    def test_long_name_list_is_cut_short(self) -> None:
        names = tuple(f"VAR_{index}" for index in range(MAX_NAMES_SHOWN + 3))
        project = ProjectInfo(language="python", env_var_names=names)

        env_step = draft_steps(project, PlanTarget())[2]

        assert "and 3 more" in env_step.what
        assert names[-1] not in env_step.what

    def test_dockerfile_project_builds_an_image(self) -> None:
        step = plan_for("python_app").steps[1]

        assert "container image" in step.what

    def test_project_without_dockerfile_uses_its_own_tooling(self) -> None:
        step = plan_for("node_app").steps[1]

        assert "own build tooling" in step.what


class TestTarget:
    def test_default_target_is_the_staging_placeholder(self) -> None:
        plan = plan_for("python_app")

        assert plan.target.name == "placeholder"
        assert plan.target.environment is Environment.STAGING
        assert "promote_to_production" not in kinds(plan)

    def test_production_adds_promote_as_the_last_step(self) -> None:
        plan = plan_for("python_app", PlanTarget(environment=Environment.PRODUCTION))

        assert kinds(plan)[-1] == "promote_to_production"
        assert kinds(plan)[-2] == "verify_health"

    def test_health_step_uses_target_port_and_path(self) -> None:
        target = PlanTarget(requirements=DeploymentTarget(port=9000, health_check_path="/up"))

        step = next(s for s in plan_for("python_app", target).steps if s.kind == "verify_health")

        assert "port 9000 at /up" in step.what

    def test_health_step_falls_back_to_scanned_port(self) -> None:
        step = next(s for s in plan_for("python_app").steps if s.kind == "verify_health")

        assert "port 8000" in step.what

    def test_health_step_without_any_port_says_so(self) -> None:
        step = next(s for s in plan_for("broken_app").steps if s.kind == "verify_health")

        assert "its configured port" in step.what


class TestStatus:
    @pytest.mark.parametrize("name", ["python_app", "node_app", "preflight_pass"])
    def test_projects_without_errors_are_ready(self, name: str) -> None:
        plan = plan_for(name)

        assert plan.status is PlanStatus.READY_FOR_REVIEW
        assert plan.blockers == ()

    def test_broken_app_is_blocked_by_its_dockerfile(self) -> None:
        plan = plan_for("broken_app")

        assert plan.status is PlanStatus.BLOCKED
        assert [b.check_name for b in plan.blockers] == ["dockerfile_base_image"]

    def test_preflight_fail_lists_every_error(self) -> None:
        plan = plan_for("preflight_fail")

        assert plan.status is PlanStatus.BLOCKED
        assert {b.check_name for b in plan.blockers} == {
            "runtime_version_mismatch",
            "listen_address",
            "dockerfile_no_baked_secrets",
        }

    def test_warnings_are_kept_but_do_not_block(self) -> None:
        plan = plan_for("python_app")

        assert plan.status is PlanStatus.READY_FOR_REVIEW
        assert [w.check_name for w in plan.warnings] == ["dockerfile_non_root"]

    def test_blocked_plan_still_shows_its_steps(self) -> None:
        assert len(plan_for("broken_app").steps) >= 4

    def test_empty_report_is_ready(self) -> None:
        plan = build_plan(ProjectInfo(language="node"), PreflightReport(results=()))

        assert plan.status is PlanStatus.READY_FOR_REVIEW


class TestStepShape:
    @pytest.mark.parametrize("name", ALL_FIXTURES)
    def test_steps_are_numbered_in_order(self, name: str) -> None:
        plan = plan_for(name)

        assert [s.number for s in plan.steps] == list(range(1, len(plan.steps) + 1))

    def test_migrations_are_marked_not_reversible(self) -> None:
        step = next(s for s in plan_for("python_app").steps if s.kind == "run_migrations")

        assert step.reversible is False
        assert step.undo_instructions is None
        assert "back up the database" in step.changes

    def test_expected_tiers_for_a_staging_plan(self) -> None:
        tiers = {s.kind: s.tier for s in plan_for("python_app").steps}

        assert tiers == {
            "run_preflight": SafetyTier.AUTO,
            "build_artifact": SafetyTier.AUTO,
            "set_target_env_names": SafetyTier.NEEDS_APPROVAL,
            "run_migrations": SafetyTier.NEEDS_APPROVAL,
            "deploy_release": SafetyTier.NEEDS_APPROVAL,
            "verify_health": SafetyTier.AUTO,
        }
