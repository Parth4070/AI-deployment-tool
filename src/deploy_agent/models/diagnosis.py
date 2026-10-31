"""An explanation of a failure, with its evidence."""

from typing import Self

from pydantic import Field, model_validator

from deploy_agent.models.common import Confidence, NonBlankText, SafetyTier, StrictModel


class Diagnosis(StrictModel):
    cause: NonBlankText
    evidence_line: NonBlankText
    confidence: Confidence
    alternative_causes: tuple[NonBlankText, ...] = Field(min_length=1)
    suggested_next_step: NonBlankText
    next_step_tier: SafetyTier

    @model_validator(mode="after")
    def _alternatives_differ_from_cause(self) -> Self:
        cause = self.cause.casefold()
        if any(alternative.casefold() == cause for alternative in self.alternative_causes):
            raise ValueError("an alternative cause cannot repeat the main cause")
        return self
