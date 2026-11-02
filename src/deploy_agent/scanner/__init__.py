"""Deterministic project discovery. No AI, and no project code is run."""

from deploy_agent.scanner.scan import ScanError, scan_project

__all__ = ["ScanError", "scan_project"]
