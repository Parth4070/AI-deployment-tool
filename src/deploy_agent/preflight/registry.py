"""The list of checks that run, in order.

To add a check:
1. Write a function ``my_check(context: PreflightContext) -> PreflightResult`` in a module
   under ``preflight/checks/``. Name the function after the check.
2. Add it to ALL_CHECKS below.
3. Add a passing and a failing test in ``tests/unit/test_preflight_<topic>.py``.
"""

from deploy_agent.preflight.checks.dockerfile import (
    dockerfile_base_image,
    dockerfile_dockerignore,
    dockerfile_no_baked_secrets,
    dockerfile_non_root,
    dockerfile_start_command,
)
from deploy_agent.preflight.checks.env_vars import env_vars_provided
from deploy_agent.preflight.checks.lockfile import lockfile_present
from deploy_agent.preflight.checks.migrations import risky_migrations
from deploy_agent.preflight.checks.network import health_check_path, listen_address, port_consistent
from deploy_agent.preflight.checks.runtime import runtime_version_mismatch
from deploy_agent.preflight.context import Check

ALL_CHECKS: tuple[Check, ...] = (
    runtime_version_mismatch,
    lockfile_present,
    env_vars_provided,
    port_consistent,
    listen_address,
    health_check_path,
    dockerfile_base_image,
    dockerfile_start_command,
    dockerfile_non_root,
    dockerfile_no_baked_secrets,
    dockerfile_dockerignore,
    risky_migrations,
)
