"""What the scanner found in a project.

Every field has a narrow format so that secret values have nowhere to go.
Adding a field here is a security decision: keep it to names and short labels.
"""

import re
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, Field, StringConstraints

from deploy_agent.models.common import Label, StrictModel

EnvVarName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")]

Port = Annotated[int, Field(ge=1, le=65535)]

RuntimeVersion = Annotated[
    str,
    StringConstraints(pattern=r"^[~^<>=!]{0,2}[0-9][0-9A-Za-z.*,<>=!~^+_-]{0,31}$"),
]


def _ensure_inside_project(path: str) -> str:
    if path.startswith(("/", "\\")):
        raise ValueError("path must be relative to the project root")
    if ".." in re.split(r"[/\\]", path):
        raise ValueError("path must stay inside the project")
    return path


RelativePath = Annotated[
    str,
    StringConstraints(max_length=260, pattern=r"^[\w@()+. /\\-]+$"),
    AfterValidator(_ensure_inside_project),
]


class ProjectInfo(StrictModel):
    language: Label
    framework: Label | None = None
    runtime_version: RuntimeVersion | None = None
    ports: tuple[Port, ...] = ()
    env_var_names: tuple[EnvVarName, ...] = ()
    migration_tool: Label | None = None
    detected_files: tuple[RelativePath, ...] = ()


class ScanWarningCode(StrEnum):
    UNREADABLE_FILE = "unreadable_file"
    FILE_TOO_LARGE = "file_too_large"
    SYMLINK_SKIPPED = "symlink_skipped"
    UNUSUAL_PATH = "unusual_path"
    LIMIT_REACHED = "limit_reached"
    INVALID_MANIFEST = "invalid_manifest"
    MISSING_MANIFEST = "missing_manifest"
    INVALID_RUNTIME_VERSION = "invalid_runtime_version"
    RUNTIME_CONFLICT = "runtime_conflict"
    NO_PROJECT_FOUND = "no_project_found"
    NESTED_PROJECTS = "nested_projects"
    MIXED_LANGUAGES = "mixed_languages"
    SUSPICIOUS_ENV_NAME = "suspicious_env_name"


class ScanWarning(StrictModel):
    """A problem found while scanning. A fixed code and a path, so file text cannot get in."""

    code: ScanWarningCode
    path: RelativePath | None = None


class ScanResult(StrictModel):
    project: ProjectInfo
    warnings: tuple[ScanWarning, ...] = ()
