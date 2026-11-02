"""Works out language, framework and migration tool.

Every label comes from the fixed tables below, never from file text, so nothing a project
contains can end up in these fields.
"""

from dataclasses import dataclass
from pathlib import Path

from deploy_agent.models.project import ScanWarning, ScanWarningCode
from deploy_agent.scanner.docker_parser import DockerfileInfo
from deploy_agent.scanner.files import (
    CONFIG_FILE_NAMES,
    ENV_TEMPLATE_NAMES,
    JAVASCRIPT_SUFFIXES,
    PYTHON_SUFFIXES,
    ProjectSnapshot,
    make_warning,
)
from deploy_agent.scanner.manifests import NODE_MANIFESTS, PYTHON_MANIFESTS, Manifests

PYTHON = "python"
NODE = "node"
UNKNOWN = "unknown"

# Order matters: the first match wins, so more specific frameworks come first.
PYTHON_FRAMEWORKS = (("django", "django"), ("fastapi", "fastapi"), ("flask", "flask"))
NODE_FRAMEWORKS = (
    ("next", "next"),
    ("nuxt", "nuxt"),
    ("@nestjs/core", "nestjs"),
    ("fastify", "fastify"),
    ("koa", "koa"),
    ("express", "express"),
)

PYTHON_MIGRATION_DEPS = (("alembic", "alembic"), ("flask-migrate", "alembic"))
NODE_MIGRATION_DEPS = (
    ("prisma", "prisma"),
    ("@prisma/client", "prisma"),
    ("drizzle-kit", "drizzle"),
    ("knex", "knex"),
    ("sequelize-cli", "sequelize"),
    ("typeorm", "typeorm"),
)

PYTHON_MIGRATION_FILES = (("alembic.ini", "alembic"), ("alembic/env.py", "alembic"))
NODE_MIGRATION_FILES = (
    ("prisma/schema.prisma", "prisma"),
    ("drizzle.config.ts", "drizzle"),
    ("drizzle.config.js", "drizzle"),
    ("knexfile.js", "knex"),
    ("knexfile.ts", "knex"),
    (".sequelizerc", "sequelize"),
)

LOCKFILES = frozenset(
    {
        "Pipfile.lock",
        "bun.lock",
        "bun.lockb",
        "package-lock.json",
        "pnpm-lock.yaml",
        "poetry.lock",
        "uv.lock",
        "yarn.lock",
    }
)
_MARKER_FILES = (
    CONFIG_FILE_NAMES
    | ENV_TEMPLATE_NAMES
    | LOCKFILES
    | PYTHON_MANIFESTS
    | NODE_MANIFESTS
    | {"manage.py"}
    | {path for path, _ in PYTHON_MIGRATION_FILES + NODE_MIGRATION_FILES}
)


@dataclass(frozen=True)
class Stack:
    language: str
    framework: str | None
    migration_tool: str | None
    detected_files: tuple[str, ...]
    warnings: tuple[ScanWarning, ...]


def _first_match(pairs: tuple[tuple[str, str], ...], present: frozenset[str]) -> str | None:
    return next((label for key, label in pairs if key in present), None)


def _has_nested_manifest(paths: tuple[str, ...]) -> bool:
    manifests = PYTHON_MANIFESTS | NODE_MANIFESTS
    return any("/" in path and Path(path).name in manifests for path in paths)


def _language_signals(
    snapshot: ProjectSnapshot, manifests: Manifests, docker: DockerfileInfo
) -> tuple[bool, bool, bool]:
    """Return (python, node, missing manifest), using the strongest evidence that exists."""
    if manifests.has_python or manifests.has_node:
        return manifests.has_python, manifests.has_node, False

    image_names = {name for name, _ in docker.images}
    if PYTHON in image_names or NODE in image_names:
        return PYTHON in image_names, NODE in image_names, True

    suffixes = {Path(path).suffix.lower() for path in snapshot.paths}
    python = not suffixes.isdisjoint(PYTHON_SUFFIXES)
    node = not suffixes.isdisjoint(JAVASCRIPT_SUFFIXES)
    return python, node, python or node


def _choose_language(
    python: bool, node: bool, python_framework: str | None, node_framework: str | None
) -> tuple[str, bool]:
    """Return the language and whether both were present."""
    if python and node:
        if node_framework and not python_framework:
            return NODE, True
        return PYTHON, True
    if python:
        return PYTHON, False
    return (NODE, False) if node else (UNKNOWN, False)


def _migration_tool(
    language: str, framework: str | None, snapshot: ProjectSnapshot, manifests: Manifests
) -> str | None:
    paths = frozenset(snapshot.paths)
    if language == PYTHON:
        found = _first_match(PYTHON_MIGRATION_DEPS, manifests.python_deps) or _first_match(
            PYTHON_MIGRATION_FILES, paths
        )
        if found:
            return found
        has_django_migrations = any(
            path == "migrations/__init__.py" or path.endswith("/migrations/__init__.py")
            for path in paths
        )
        return "django" if framework == "django" and has_django_migrations else None
    if language == NODE:
        return _first_match(NODE_MIGRATION_DEPS, manifests.node_deps) or _first_match(
            NODE_MIGRATION_FILES, paths
        )
    return None


def detect_stack(snapshot: ProjectSnapshot, manifests: Manifests, docker: DockerfileInfo) -> Stack:
    python_framework = _first_match(PYTHON_FRAMEWORKS, manifests.python_deps)
    node_framework = _first_match(NODE_FRAMEWORKS, manifests.node_deps)
    python, node, missing_manifest = _language_signals(snapshot, manifests, docker)

    warnings: list[ScanWarning] = []
    nested_only = _has_nested_manifest(snapshot.paths) and missing_manifest
    no_root_evidence = not (manifests.has_python or manifests.has_node or docker.images)
    if nested_only and no_root_evidence:
        python, node, missing_manifest = False, False, False
        warnings.append(make_warning(ScanWarningCode.NESTED_PROJECTS))

    language, mixed = _choose_language(python, node, python_framework, node_framework)
    if mixed:
        warnings.append(make_warning(ScanWarningCode.MIXED_LANGUAGES))
    if missing_manifest:
        warnings.append(make_warning(ScanWarningCode.MISSING_MANIFEST))
    if language == UNKNOWN and not warnings:
        warnings.append(make_warning(ScanWarningCode.NO_PROJECT_FOUND))

    framework = {PYTHON: python_framework, NODE: node_framework}.get(language)
    return Stack(
        language=language,
        framework=framework,
        migration_tool=_migration_tool(language, framework, snapshot, manifests),
        detected_files=tuple(path for path in snapshot.paths if path in _MARKER_FILES),
        warnings=tuple(warnings),
    )
