"""Reads a project folder safely and only once.

This is the scanner's only file I/O. Everything after it works on the snapshot, so the
detectors stay pure and easy to test.

Real .env files are never opened. Only ``secrets/`` may read secret values, and a names-only
read would still load the values into memory. Symlinks are never followed, so a link cannot
pull in a file from outside the project.
"""

import os
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from deploy_agent.models.project import RelativePath, ScanWarning, ScanWarningCode

MAX_FILE_BYTES = 1_000_000
MAX_TOTAL_BYTES = 50_000_000
MAX_FILES = 20_000
MAX_DEPTH = 20

ENV_TEMPLATE_NAMES = frozenset({".env.example", ".env.sample", ".env.template"})

SKIPPED_FOLDERS = frozenset(
    {
        ".git",
        ".hg",
        ".mypy_cache",
        ".next",
        ".nuxt",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "__tests__",
        "build",
        "coverage",
        "dist",
        "env",
        "node_modules",
        "site-packages",
        "test",
        "tests",
        "venv",
    }
)

CONFIG_FILE_NAMES = frozenset(
    {
        ".node-version",
        ".nvmrc",
        ".python-version",
        "Dockerfile",
        "Pipfile",
        "Procfile",
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "runtime.txt",
    }
)

PYTHON_SUFFIXES = frozenset({".py"})
JAVASCRIPT_SUFFIXES = frozenset({".cjs", ".js", ".jsx", ".mjs", ".ts", ".tsx"})

_path_check: TypeAdapter[str] = TypeAdapter(RelativePath)


@dataclass(frozen=True)
class ProjectSnapshot:
    """The files found in a project, and the text of the few the scanner needs."""

    paths: tuple[str, ...] = ()
    texts: Mapping[str, str] = field(default_factory=dict)
    warnings: tuple[ScanWarning, ...] = ()


def is_private_env_file(name: str) -> bool:
    lowered = name.lower()
    if lowered in ENV_TEMPLATE_NAMES:
        return False
    return lowered in {".env", ".envrc"} or lowered.startswith(".env.") or lowered.endswith(".env")


def _is_safe_path(path: str) -> bool:
    try:
        _path_check.validate_python(path)
    except ValidationError:
        return False
    return True


def make_warning(code: ScanWarningCode, path: str | None = None) -> ScanWarning:
    """Build a warning, leaving out a path that does not fit the strict path format."""
    return ScanWarning(code=code, path=path if path and _is_safe_path(path) else None)


def _should_read(path: str) -> bool:
    is_root_file = "/" not in path
    if is_root_file and (path in CONFIG_FILE_NAMES or path.lower() in ENV_TEMPLATE_NAMES):
        return True
    return Path(path).suffix.lower() in PYTHON_SUFFIXES | JAVASCRIPT_SUFFIXES


def _list_files(root: Path, warnings: list[ScanWarning]) -> dict[str, int]:
    """Walk the folder and return each usable file's relative path and size."""
    found: dict[str, int] = {}
    folders: deque[tuple[Path, str, int]] = deque([(root, "", 0)])
    while folders:
        folder, prefix, depth = folders.popleft()
        try:
            with os.scandir(folder) as scan:
                entries = sorted(scan, key=lambda entry: entry.name)
        except OSError:
            warnings.append(make_warning(ScanWarningCode.UNREADABLE_FILE, prefix or None))
            continue

        for entry in entries:
            path = f"{prefix}{entry.name}"
            try:
                if entry.is_symlink() or entry.is_junction():
                    warnings.append(make_warning(ScanWarningCode.SYMLINK_SKIPPED, path))
                elif entry.is_dir(follow_symlinks=False):
                    if entry.name in SKIPPED_FOLDERS:
                        continue
                    if depth >= MAX_DEPTH:
                        warnings.append(make_warning(ScanWarningCode.LIMIT_REACHED, path))
                        continue
                    folders.append((Path(entry.path), f"{path}/", depth + 1))
                elif entry.is_file(follow_symlinks=False) and not is_private_env_file(entry.name):
                    if not _is_safe_path(path):
                        warnings.append(make_warning(ScanWarningCode.UNUSUAL_PATH))
                        continue
                    if len(found) >= MAX_FILES:
                        warnings.append(make_warning(ScanWarningCode.LIMIT_REACHED))
                        return found
                    found[path] = entry.stat(follow_symlinks=False).st_size
            except OSError:
                warnings.append(make_warning(ScanWarningCode.UNREADABLE_FILE, path))
    return found


def _read_text(root: Path, path: str, warnings: list[ScanWarning]) -> str | None:
    try:
        data = (root / path).read_bytes()
    except OSError:
        warnings.append(make_warning(ScanWarningCode.UNREADABLE_FILE, path))
        return None
    if b"\x00" in data:
        warnings.append(make_warning(ScanWarningCode.UNREADABLE_FILE, path))
        return None
    return data.decode("utf-8-sig", errors="replace")


def load_snapshot(root: Path) -> ProjectSnapshot:
    warnings: list[ScanWarning] = []
    sizes = _list_files(root, warnings)
    paths = tuple(sorted(sizes))

    texts: dict[str, str] = {}
    total_bytes = 0
    for path in paths:
        if not _should_read(path):
            continue
        if sizes[path] > MAX_FILE_BYTES:
            warnings.append(make_warning(ScanWarningCode.FILE_TOO_LARGE, path))
            continue
        if total_bytes + sizes[path] > MAX_TOTAL_BYTES:
            warnings.append(make_warning(ScanWarningCode.LIMIT_REACHED))
            break
        text = _read_text(root, path, warnings)
        if text is not None:
            texts[path] = text
            total_bytes += sizes[path]
    return ProjectSnapshot(paths=paths, texts=texts, warnings=tuple(warnings))
