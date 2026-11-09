"""Builds a deployment plan from scan facts and preflight results.

Pure: no files, no network, no commands. The planner picks which steps apply and words
them. It never picks a tier. Each step is sent to the policy engine and keeps the tier
the engine returns.
"""

from dataclasses import dataclass

from deploy_agent.models.common import Severity
from deploy_agent.models.plan import (
    DeploymentPlan,
    Environment,
    PlanStatus,
    PlanStep,
    PlanTarget,
)
from deploy_agent.models.policy import ProposedAction
from deploy_agent.models.preflight import PreflightReport
from deploy_agent.models.project import ProjectInfo
from deploy_agent.policy import evaluate

# Long lists of variable names are cut short so a step stays readable.
MAX_NAMES_SHOWN = 6

READ_ONLY_CHANGES = "Nothing. This step only reads."
READ_ONLY_UNDO = "Nothing to undo: this step only reads."


@dataclass(frozen=True)
class StepDraft:
    """A step before the policy engine has given it a tier."""

    kind: str
    what: str
    changes: str
    reversible: bool
    undo: str | None = None


def _name_list(names: tuple[str, ...]) -> str:
    shown = ", ".join(names[:MAX_NAMES_SHOWN])
    hidden = len(names) - MAX_NAMES_SHOWN
    return f"{shown} and {hidden} more" if hidden > 0 else shown


def _preflight_step() -> StepDraft:
    return StepDraft(
        kind="run_preflight",
        what="Run the preflight checks again just before deploying",
        changes=READ_ONLY_CHANGES,
        reversible=True,
        undo=READ_ONLY_UNDO,
    )


def _build_step(project: ProjectInfo) -> StepDraft:
    how = (
        "as a container image from the Dockerfile"
        if "Dockerfile" in project.detected_files
        else "with its own build tooling"
    )
    return StepDraft(
        kind="build_artifact",
        what=f"Build the {project.language} app {how}",
        changes="Creates a build on this machine. Nothing on the target changes.",
        reversible=True,
        undo="Remove the local build output. It can be rebuilt at any time.",
    )


def _env_names_step(project: ProjectInfo, target: PlanTarget) -> StepDraft | None:
    if not project.env_var_names:
        return None
    count = len(project.env_var_names)
    noun = "variable" if count == 1 else "variables"
    return StepDraft(
        kind="set_target_env_names",
        what=(
            f"Make sure {target.name} provides {count} environment {noun}: "
            f"{_name_list(project.env_var_names)}"
        ),
        changes=(
            "Adds variable names to the target's settings. You type the values on the "
            "target yourself; the agent never sees them."
        ),
        reversible=True,
        undo="Remove the added variables from the target's settings.",
    )


def _migrations_step(project: ProjectInfo) -> StepDraft | None:
    if project.migration_tool is None:
        return None
    return StepDraft(
        kind="run_migrations",
        what=f"Run database migrations with {project.migration_tool}",
        changes=(
            "Changes the database structure on the target. Some migrations cannot be "
            "undone, so back up the database first."
        ),
        reversible=False,
    )


def _deploy_step(target: PlanTarget) -> StepDraft:
    return StepDraft(
        kind="deploy_release",
        what=f"Deploy the new build to {target.name} (staging)",
        changes=f"Replaces the release running on {target.name} (staging) with the new build.",
        reversible=True,
        undo="Deploy the previous release again.",
    )


def _health_step(project: ProjectInfo, target: PlanTarget) -> StepDraft:
    requirements = target.requirements
    port = requirements.port or (project.ports[0] if project.ports else None)
    port_text = f"port {port}" if port is not None else "its configured port"
    path_text = requirements.health_check_path or "the health-check path"
    return StepDraft(
        kind="verify_health",
        what=f"Check that the app answers on {port_text} at {path_text}",
        changes=READ_ONLY_CHANGES,
        reversible=True,
        undo=READ_ONLY_UNDO,
    )


def _promote_step(target: PlanTarget) -> StepDraft | None:
    if target.environment is not Environment.PRODUCTION:
        return None
    return StepDraft(
        kind="promote_to_production",
        what=f"Promote the checked release on {target.name} to production",
        changes="Production traffic starts going to the new release.",
        reversible=True,
        undo="Promote the previous release back to production.",
    )


def draft_steps(project: ProjectInfo, target: PlanTarget) -> list[StepDraft]:
    """Pick the steps that apply to this project and target, in the order they would run."""
    candidates = [
        _preflight_step(),
        _build_step(project),
        _env_names_step(project, target),
        _migrations_step(project),
        _deploy_step(target),
        _health_step(project, target),
        _promote_step(target),
    ]
    return [draft for draft in candidates if draft is not None]


def classify(draft: StepDraft, number: int) -> PlanStep:
    """Ask the policy engine for the step's tier and turn the draft into a plan step."""
    decision = evaluate(ProposedAction(kind=draft.kind, description=draft.what))
    return PlanStep(
        number=number,
        kind=draft.kind,
        what=draft.what,
        changes=draft.changes,
        tier=decision.tier,
        policy_reason=decision.reason,
        reversible=draft.reversible,
        undo_instructions=draft.undo,
    )


def build_plan(
    project: ProjectInfo, report: PreflightReport, target: PlanTarget | None = None
) -> DeploymentPlan:
    """Turn scan facts and preflight results into a plan for a person to review.

    Preflight errors do not stop the plan from being built. They mark it as blocked and
    are listed, so the person sees both what is wrong and what would happen after.
    """
    chosen = target or PlanTarget()
    failures = report.failures
    blockers = tuple(item for item in failures if item.severity is Severity.ERROR)
    warnings = tuple(item for item in failures if item.severity is not Severity.ERROR)
    steps = tuple(
        classify(draft, number)
        for number, draft in enumerate(draft_steps(project, chosen), start=1)
    )
    return DeploymentPlan(
        target=chosen,
        project=project,
        status=PlanStatus.BLOCKED if blockers else PlanStatus.READY_FOR_REVIEW,
        blockers=blockers,
        warnings=warnings,
        steps=steps,
    )
