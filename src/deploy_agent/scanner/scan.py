"""Runs every detector and builds the final result. No AI, and no project code is run."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from deploy_agent.models.project import ProjectInfo, ScanResult, ScanWarning
from deploy_agent.scanner.docker_parser import DockerfileInfo, parse_dockerfile
from deploy_agent.scanner.env_names import (
    clean_env_names,
    names_from_javascript,
    names_from_python,
    names_from_template,
)
from deploy_agent.scanner.files import (
    ENV_TEMPLATE_NAMES,
    JAVASCRIPT_SUFFIXES,
    PYTHON_SUFFIXES,
    ProjectSnapshot,
    load_snapshot,
)
from deploy_agent.scanner.manifests import Manifests, read_manifests
from deploy_agent.scanner.ports import (
    clean_ports,
    ports_from_command,
    ports_from_javascript,
    ports_from_python,
)
from deploy_agent.scanner.runtime import Runtime, detect_runtime
from deploy_agent.scanner.source import parse_javascript, parse_python
from deploy_agent.scanner.stack import UNKNOWN, detect_stack


class ScanError(RuntimeError):
    """The scan could not start. Problems inside a project are warnings, not this error."""


def _source_texts(snapshot: ProjectSnapshot, suffixes: frozenset[str]) -> Iterator[str]:
    for path, text in snapshot.texts.items():
        if Path(path).suffix.lower() in suffixes:
            yield text


def _collect_env_names(snapshot: ProjectSnapshot, docker: DockerfileInfo) -> Iterator[str]:
    yield from docker.env_names
    for path, text in snapshot.texts.items():
        if path.lower() in ENV_TEMPLATE_NAMES:
            yield from names_from_template(text)
    for text in _source_texts(snapshot, PYTHON_SUFFIXES):
        yield from names_from_python(parse_python(text))
    for text in _source_texts(snapshot, JAVASCRIPT_SUFFIXES):
        yield from names_from_javascript(parse_javascript(text))


def _collect_ports(
    snapshot: ProjectSnapshot, manifests: Manifests, docker: DockerfileInfo
) -> Iterator[int]:
    yield from docker.ports
    commands = (
        *docker.commands,
        *manifests.node_scripts,
        *snapshot.texts.get("Procfile", "").splitlines(),
    )
    for command in commands:
        yield from ports_from_command(command)
    for text in _source_texts(snapshot, PYTHON_SUFFIXES):
        yield from ports_from_python(parse_python(text))
    for text in _source_texts(snapshot, JAVASCRIPT_SUFFIXES):
        yield from ports_from_javascript(parse_javascript(text))


def _merge_warnings(*groups: Iterable[ScanWarning]) -> tuple[ScanWarning, ...]:
    merged = {warning for group in groups for warning in group}
    return tuple(sorted(merged, key=lambda warning: (warning.code, warning.path or "")))


@dataclass(frozen=True)
class ScanDetails:
    """The scan result plus the in-memory facts behind it.

    Only for local use by preflight. Never send this to the model: ``snapshot`` holds raw
    file text. ``result`` is the narrow, safe summary.
    """

    result: ScanResult
    snapshot: ProjectSnapshot
    manifests: Manifests
    docker: DockerfileInfo
    runtime: Runtime


def scan_project(root: Path | str) -> ScanResult:
    """Scan a project folder. Broken files become warnings, never a crash.

    Raises ScanError only when the folder itself cannot be used.
    """
    return scan_details(root).result


def scan_details(root: Path | str) -> ScanDetails:
    """Like scan_project, but also return the facts preflight needs."""
    folder = Path(root)
    if not folder.is_dir():
        raise ScanError(
            f"Cannot scan {folder}: it is not an existing folder. Check the path and try again."
        )
    return analyse_snapshot(load_snapshot(folder))


def analyse_snapshot(snapshot: ProjectSnapshot) -> ScanDetails:
    """Run every detector on files already in memory. Pure: no file I/O."""
    manifests = read_manifests(snapshot)
    docker = parse_dockerfile(snapshot.texts.get("Dockerfile", ""))
    stack = detect_stack(snapshot, manifests, docker)
    runtime = detect_runtime(stack.language, snapshot, manifests, docker)

    # With no project at the root, source files in subfolders say nothing reliable.
    has_project = stack.language != UNKNOWN
    env = clean_env_names(_collect_env_names(snapshot, docker) if has_project else ())
    ports = clean_ports(_collect_ports(snapshot, manifests, docker) if has_project else ())

    result = ScanResult(
        project=ProjectInfo(
            language=stack.language,
            framework=stack.framework,
            runtime_version=runtime.version,
            ports=ports,
            env_var_names=env.names,
            migration_tool=stack.migration_tool,
            detected_files=stack.detected_files,
        ),
        warnings=_merge_warnings(
            snapshot.warnings, manifests.warnings, stack.warnings, runtime.warnings, env.warnings
        ),
    )
    return ScanDetails(
        result=result, snapshot=snapshot, manifests=manifests, docker=docker, runtime=runtime
    )
