"""Log handling: clean and redact raw logs, then match them against known failures."""

from deploy_agent.logs.catalog import CATALOG, FailureEntry
from deploy_agent.logs.clean import CleanLog, clean_log
from deploy_agent.logs.matcher import match_failure

__all__ = ["CATALOG", "CleanLog", "FailureEntry", "clean_log", "match_failure"]
