"""Runs checks and collects their results. A broken check cannot stop the others."""

from collections.abc import Iterable

from deploy_agent.models.common import Severity
from deploy_agent.models.preflight import PreflightReport, PreflightResult
from deploy_agent.preflight.context import Check, PreflightContext
from deploy_agent.preflight.evidence import failed
from deploy_agent.preflight.registry import ALL_CHECKS


def run_check(check: Check, context: PreflightContext) -> PreflightResult:
    try:
        return check(context)
    except Exception as error:  # noqa: BLE001 - one bad check must not hide the rest
        # Only the exception's type goes into the result. Its message could quote file text.
        return failed(
            check.__name__,
            Severity.ERROR,
            f"The check stopped with an internal error ({type(error).__name__}).",
            "This is a bug in deploy-agent. Please report it; the other checks still ran.",
        )


def run_preflight(
    context: PreflightContext, checks: Iterable[Check] | None = None
) -> PreflightReport:
    """Run every registered check (or the ones given) in order."""
    chosen = ALL_CHECKS if checks is None else checks
    return PreflightReport(results=tuple(run_check(check, context) for check in chosen))
