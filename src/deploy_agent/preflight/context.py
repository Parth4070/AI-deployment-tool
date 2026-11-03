"""Everything a check is allowed to look at, gathered once.

The context stays on this machine. It holds raw file text (in ``details.snapshot``), so it
must never be sent to the model. Checks turn it into results built only from safe pieces;
see ``evidence.py``.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from deploy_agent.models.preflight import DeploymentTarget, PreflightResult
from deploy_agent.models.project import ProjectInfo
from deploy_agent.scanner.docker_parser import DockerfileInfo
from deploy_agent.scanner.files import ProjectSnapshot
from deploy_agent.scanner.manifests import Manifests
from deploy_agent.scanner.scan import ScanDetails, scan_details


@dataclass(frozen=True)
class PreflightContext:
    details: ScanDetails
    target: DeploymentTarget

    @property
    def project(self) -> ProjectInfo:
        return self.details.result.project

    @property
    def snapshot(self) -> ProjectSnapshot:
        return self.details.snapshot

    @property
    def manifests(self) -> Manifests:
        return self.details.manifests

    @property
    def docker(self) -> DockerfileInfo:
        return self.details.docker

    @property
    def runtime_sources(self) -> tuple[tuple[str, str], ...]:
        return self.details.runtime.sources

    @property
    def has_dockerfile(self) -> bool:
        return "Dockerfile" in self.details.snapshot.texts

    def root_files(self) -> frozenset[str]:
        """Names of files sitting directly in the project folder."""
        return frozenset(path for path in self.details.snapshot.paths if "/" not in path)


def build_context(root: Path | str, target: DeploymentTarget | None = None) -> PreflightContext:
    """Scan the folder once and wrap the result for the checks.

    Raises ScanError if the folder cannot be used.
    """
    return PreflightContext(details=scan_details(root), target=target or DeploymentTarget())


Check = Callable[[PreflightContext], PreflightResult]
"""A check: a plain function from the context to one result. Its name is the check name."""
