"""Does the deploy target provide every environment variable the code reads?

Only NAMES are compared. No value is read, asked for or shown.
"""

from deploy_agent.models.common import Severity
from deploy_agent.models.preflight import PreflightResult
from deploy_agent.preflight.context import PreflightContext
from deploy_agent.preflight.evidence import failed, listing, passed, skipped


def env_vars_provided(context: PreflightContext) -> PreflightResult:
    name = "env_vars_provided"
    provided = context.target.provided_env_names
    if provided is None:
        return skipped(name, "the deploy target's variable names are not known.")

    used = context.project.env_var_names
    if not used:
        return passed(name, "The project does not read any environment variables we can see.")

    missing = sorted(set(used) - set(provided))
    if missing:
        return failed(
            name,
            Severity.WARNING,
            f"The project reads {len(missing)} variable(s) the target does not provide: "
            f"{listing(missing)}.",
            "Set these variables on the deploy target, or remove the code that reads them. "
            "Some may be optional: the scanner cannot yet tell required from optional.",
        )
    return passed(name, f"All {len(used)} variable names are provided.")
