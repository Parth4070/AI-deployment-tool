"""Preflight models: where the project is going, and what each check found."""

from typing import Annotated, Self

from pydantic import StringConstraints, model_validator

from deploy_agent.models.common import Label, NonBlankText, Severity, StrictModel
from deploy_agent.models.project import EnvVarName, Port, RuntimeVersion

# Loose on purpose: a badly formed path must reach the health-check rule so it can be
# reported. Printable characters only and a length cap, so it cannot carry much else.
HealthCheckPathInput = Annotated[str, StringConstraints(pattern=r"^[\x21-\x7e]{1,200}$")]


class DeploymentTarget(StrictModel):
    """What the deploy target expects. Provider-neutral, and names only, never values.

    Every field is optional. A missing field means "unknown", and the checks that need it
    are skipped. ``provided_env_names=()`` is different from ``None``: it means the target
    provides no variables at all.
    """

    runtime_version: RuntimeVersion | None = None
    port: Port | None = None
    health_check_path: HealthCheckPathInput | None = None
    provided_env_names: tuple[EnvVarName, ...] | None = None


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


class PreflightReport(StrictModel):
    results: tuple[PreflightResult, ...]

    @property
    def failures(self) -> tuple[PreflightResult, ...]:
        return tuple(result for result in self.results if not result.passed)

    @property
    def has_errors(self) -> bool:
        """True when any failed check is serious enough to block a deploy."""
        return any(result.severity == Severity.ERROR for result in self.failures)
