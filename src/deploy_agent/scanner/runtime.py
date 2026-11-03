"""Works out the required runtime version. Pinned version files beat ranges and images."""

import re
from dataclasses import dataclass

from pydantic import TypeAdapter, ValidationError

from deploy_agent.models.project import RuntimeVersion, ScanWarning, ScanWarningCode
from deploy_agent.scanner.docker_parser import DockerfileInfo
from deploy_agent.scanner.files import ProjectSnapshot, make_warning
from deploy_agent.scanner.manifests import Manifests

_version_check: TypeAdapter[str] = TypeAdapter(RuntimeVersion)
_LEADING_NUMBERS = re.compile(r"\d+(?:\.\d+)*")


@dataclass(frozen=True)
class Runtime:
    version: str | None = None
    warnings: tuple[ScanWarning, ...] = ()
    sources: tuple[tuple[str, str], ...] = ()
    """Every valid (file, version) found, most trusted first. Preflight compares them."""


def normalise_version(raw: str) -> str | None:
    """Tidy a version string, or return None if it does not fit the strict format."""
    version = raw.strip().removeprefix("python-")
    if re.match(r"[vV]\d", version):
        version = version[1:]
    version = re.sub(r"([<>=!~^])\s+", r"\1", version)
    version = re.sub(r"\s*,\s*|\s+", ",", version)
    try:
        return _version_check.validate_python(version)
    except ValidationError:
        return None


def _first_line(text: str | None) -> str | None:
    if text is None:
        return None
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def _image_version(docker: DockerfileInfo, image: str) -> str | None:
    """Return the version from the last stage using this image, which is what really runs."""
    for name, tag in reversed(docker.images):
        if name == image:
            match = _LEADING_NUMBERS.match(tag)
            return match.group() if match else None
    return None


def _candidates(
    language: str, snapshot: ProjectSnapshot, manifests: Manifests, docker: DockerfileInfo
) -> list[tuple[str, str | None]]:
    """List (source file, raw version) from most to least trusted."""
    texts = snapshot.texts
    if language == "python":
        return [
            (".python-version", _first_line(texts.get(".python-version"))),
            ("pyproject.toml", manifests.requires_python),
            ("Pipfile", manifests.pipfile_python),
            ("runtime.txt", _first_line(texts.get("runtime.txt"))),
            ("Dockerfile", _image_version(docker, "python")),
        ]
    if language == "node":
        return [
            (".nvmrc", _first_line(texts.get(".nvmrc"))),
            (".node-version", _first_line(texts.get(".node-version"))),
            ("package.json", manifests.engines_node),
            ("Dockerfile", _image_version(docker, "node")),
        ]
    return []


def _pins_disagree(versions: list[str]) -> bool:
    """Compare exact versions only, and only as far as both are specific."""
    pins: list[list[str]] = []
    for version in versions:
        match = _LEADING_NUMBERS.fullmatch(version)
        if match:
            pins.append(match.group().split("."))
    return any(
        any(left != right for left, right in zip(first, second, strict=False))
        for first in pins
        for second in pins
    )


def detect_runtime(
    language: str, snapshot: ProjectSnapshot, manifests: Manifests, docker: DockerfileInfo
) -> Runtime:
    sources: list[tuple[str, str]] = []
    warnings: list[ScanWarning] = []
    for path, raw in _candidates(language, snapshot, manifests, docker):
        if raw is None:
            continue
        version = normalise_version(raw)
        if version is None:
            warnings.append(make_warning(ScanWarningCode.INVALID_RUNTIME_VERSION, path))
        else:
            sources.append((path, version))

    versions = [version for _, version in sources]
    if _pins_disagree(versions):
        warnings.append(make_warning(ScanWarningCode.RUNTIME_CONFLICT))
    return Runtime(
        version=versions[0] if versions else None,
        warnings=tuple(warnings),
        sources=tuple(sources),
    )
