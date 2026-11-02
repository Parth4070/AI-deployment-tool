"""Reads dependency files. Wrong shapes are treated as missing, never as a crash."""

import json
import re
import tomllib
from dataclasses import dataclass, field
from typing import Any

from deploy_agent.models.project import ScanWarning, ScanWarningCode
from deploy_agent.scanner.files import ProjectSnapshot, make_warning

PYTHON_MANIFESTS = frozenset({"Pipfile", "pyproject.toml", "requirements.txt", "setup.py"})
NODE_MANIFESTS = frozenset({"package.json"})

_DEPENDENCY_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True)
class Manifests:
    has_python: bool = False
    has_node: bool = False
    python_deps: frozenset[str] = frozenset()
    node_deps: frozenset[str] = frozenset()
    requires_python: str | None = None
    pipfile_python: str | None = None
    engines_node: str | None = None
    node_scripts: tuple[str, ...] = ()
    warnings: tuple[ScanWarning, ...] = field(default_factory=tuple)


def _table(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _normalise_dependency(requirement: str) -> str | None:
    """Keep only the package name. Anything after it may hold a URL with a token."""
    match = _DEPENDENCY_NAME.match(requirement.strip())
    return re.sub(r"[._-]+", "-", match.group()).lower() if match else None


def _dependency_names(requirements: object) -> set[str]:
    if not isinstance(requirements, list):
        return set()
    names = {_normalise_dependency(item) for item in requirements if isinstance(item, str)}
    return {name for name in names if name}


def _parse_toml(text: str) -> dict[str, Any] | None:
    try:
        return tomllib.loads(text)
    except (tomllib.TOMLDecodeError, RecursionError):
        return None


def _parse_pyproject(data: dict[str, Any]) -> tuple[set[str], str | None]:
    project = _table(data.get("project"))
    poetry = _table(_table(_table(data.get("tool")).get("poetry")).get("dependencies"))

    names = _dependency_names(project.get("dependencies"))
    names |= _dependency_names(list(poetry))
    names.discard("python")
    python = _text_or_none(project.get("requires-python")) or _text_or_none(poetry.get("python"))
    return names, python


def _parse_requirements(text: str) -> set[str]:
    lines = [line.strip() for line in text.splitlines()]
    return _dependency_names([line for line in lines if line and line[0] not in "#-"])


def _parse_pipfile(data: dict[str, Any]) -> tuple[set[str], str | None]:
    names = _dependency_names(list(_table(data.get("packages"))))
    python = _text_or_none(_table(data.get("requires")).get("python_version"))
    return names, python


def _parse_package_json(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def read_manifests(snapshot: ProjectSnapshot) -> Manifests:
    texts = snapshot.texts
    warnings: list[ScanWarning] = []
    python_deps: set[str] = set()
    requires_python = None
    pipfile_python = None
    engines_node = None
    node_deps: set[str] = set()
    node_scripts: tuple[str, ...] = ()

    if "pyproject.toml" in texts:
        data = _parse_toml(texts["pyproject.toml"])
        if data is None:
            warnings.append(make_warning(ScanWarningCode.INVALID_MANIFEST, "pyproject.toml"))
        else:
            names, requires_python = _parse_pyproject(data)
            python_deps |= names

    if "requirements.txt" in texts:
        python_deps |= _parse_requirements(texts["requirements.txt"])

    if "Pipfile" in texts:
        data = _parse_toml(texts["Pipfile"])
        if data is None:
            warnings.append(make_warning(ScanWarningCode.INVALID_MANIFEST, "Pipfile"))
        else:
            names, pipfile_python = _parse_pipfile(data)
            python_deps |= names

    if "package.json" in texts:
        package = _parse_package_json(texts["package.json"])
        if package is None:
            warnings.append(make_warning(ScanWarningCode.INVALID_MANIFEST, "package.json"))
        else:
            for section in ("dependencies", "devDependencies"):
                node_deps |= {name.lower() for name in _table(package.get(section))}
            scripts = _table(package.get("scripts"))
            node_scripts = tuple(
                scripts[key] for key in sorted(scripts) if isinstance(scripts[key], str)
            )
            engines_node = _text_or_none(_table(package.get("engines")).get("node"))

    return Manifests(
        has_python=not PYTHON_MANIFESTS.isdisjoint(snapshot.paths),
        has_node=not NODE_MANIFESTS.isdisjoint(snapshot.paths),
        python_deps=frozenset(python_deps),
        node_deps=frozenset(node_deps),
        requires_python=requires_python,
        pipfile_python=pipfile_python,
        engines_node=engines_node,
        node_scripts=node_scripts,
        warnings=tuple(warnings),
    )
