"""The result of one preflight check."""

from typing import Self

from pydantic import model_validator

from deploy_agent.models.common import Label, NonBlankText, Severity, StrictModel


class PreflightResult(StrictModel):
    check_name: Label
    passed: bool
    severity: Severity
    evidence: NonBlankText | None = None
    suggested_fix: NonBlankText | None = None

    @model_validator(mode="after")
    def _failure_explains_itself(self) -> Self:
        if not self.passed and (self.evidence is None or self.suggested_fix is None):
            raise ValueError("a failed check needs evidence and a suggested fix")
        return self
