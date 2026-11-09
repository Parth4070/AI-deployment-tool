"""A reviewable deployment plan.

A plan only describes steps. Nothing in it is ever run by the planner. Each step's tier
comes from the policy engine, never from the planner itself.
"""

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from deploy_agent.models.action import Action
from deploy_agent.models.common import Label, NonBlankText, Severity, StrictModel
from deploy_agent.models.policy import PolicyReason
from deploy_agent.models.preflight import DeploymentTarget, PreflightResult
from deploy_agent.models.project import ProjectInfo


class Environment(StrEnum):
    STAGING = "staging"
    PRODUCTION = "production"


class PlanTarget(StrictModel):
    """Where the plan deploys to. Provider-neutral; a placeholder until providers are chosen.

    ``requirements`` holds what the target expects (runtime, port, health path, variable
    names). Names only, never values.
    """

    name: Label = "placeholder"
    environment: Environment = Environment.STAGING
    requirements: DeploymentTarget = DeploymentTarget()


class PlanStep(Action):
    """One step of a plan: an Action plus what it changes and why it got its tier."""

    number: int = Field(ge=1)
    kind: Label
    changes: NonBlankText
    policy_reason: PolicyReason


class PlanStatus(StrEnum):
    READY_FOR_REVIEW = "ready_for_review"
    BLOCKED = "blocked"


class DeploymentPlan(StrictModel):
    target: PlanTarget
    project: ProjectInfo
    status: PlanStatus
    blockers: tuple[PreflightResult, ...] = ()
    warnings: tuple[PreflightResult, ...] = ()
    steps: tuple[PlanStep, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if [step.number for step in self.steps] != list(range(1, len(self.steps) + 1)):
            raise ValueError("steps must be numbered 1, 2, 3, ... in order")
        if any(item.passed or item.severity is not Severity.ERROR for item in self.blockers):
            raise ValueError("a blocker must be a failed check with error severity")
        if any(item.passed for item in self.warnings):
            raise ValueError("a warning must be a failed check")
        if (self.status is PlanStatus.BLOCKED) != bool(self.blockers):
            raise ValueError("a plan is blocked exactly when it has blockers")
        return self
