"""An explanation of a failure, with its evidence."""

from typing import Self

from pydantic import Field, model_validator

from deploy_agent.models.common import Confidence, Label, NonBlankText, SafetyTier, StrictModel


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


class FailureMatch(StrictModel):
    """A log line matched a known failure in the catalog.

    ``failure_id`` names the catalog entry, so the retry budget can count fixes for it.
    ``line_number`` counts from 1, in the cleaned log.
    """

    failure_id: Label
    line_number: int = Field(ge=1)
    diagnosis: Diagnosis


NO_MATCH_MESSAGE = (
    "No known failure matched this log. Read the last error lines yourself, "
    "or ask for an AI explanation once that feature exists."
)


class NoMatch(StrictModel):
    """No catalog entry matched. Fixed text only: it never quotes the log."""

    message: NonBlankText = NO_MATCH_MESSAGE
