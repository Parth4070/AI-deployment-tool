"""Rule-based checks that run before a deploy. Plain code, no AI."""

from deploy_agent.preflight.context import Check, PreflightContext, build_context
from deploy_agent.preflight.runner import run_preflight

__all__ = ["Check", "PreflightContext", "build_context", "run_preflight"]
