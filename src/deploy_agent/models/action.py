"""One thing the agent could do.

The tier here only records a classification. The policy engine enforces it.
"""

from typing import Self

from pydantic import model_validator

from deploy_agent.models.common import NonBlankText, SafetyTier, StrictModel


class Action(StrictModel):
    what: NonBlankText
    tier: SafetyTier
    reversible: bool
    undo_instructions: NonBlankText | None = None

    @model_validator(mode="after")
    def _undo_matches_reversible(self) -> Self:
        if self.reversible and self.undo_instructions is None:
            raise ValueError("a reversible action needs undo instructions")
        if not self.reversible and self.undo_instructions is not None:
            raise ValueError("an irreversible action cannot have undo instructions")
        return self
