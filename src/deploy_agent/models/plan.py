"""A reviewable deployment plan."""

from pydantic import Field

from deploy_agent.models.action import Action
from deploy_agent.models.common import StrictModel


class DeploymentPlan(StrictModel):
    steps: tuple[Action, ...] = Field(min_length=1)
