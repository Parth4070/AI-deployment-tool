"""The failure catalog: known failures, how to spot them, and what they mean.

Only failures whose error text and cause are well known go here. Each pattern matches one
line of cleaned log text. Explanations and next steps are fixed text written in this file.
The only log text that can reach an explanation is a ``name`` captured by a pattern, and it
must pass that entry's strict ``name_format`` or the line does not match at all.

Entries never set a tier. The matcher asks the policy engine for the tier of
``next_step_kind``.
"""

import re
from dataclasses import dataclass

from deploy_agent.models.common import Confidence

# How many lines before a match a pattern's context may appear in.
CONTEXT_LINES = 10


@dataclass(frozen=True)
class LinePattern:
    """A regex for one log line. ``context``, if set, must also match one of the
    ``CONTEXT_LINES`` lines just before it, for errors that only mean something in a
    certain place (a KeyError only means "missing env var" inside os.environ).
    """

    regex: re.Pattern[str]
    context: re.Pattern[str] | None = None


def line(pattern: str, context: str | None = None) -> LinePattern:
    return LinePattern(re.compile(pattern), None if context is None else re.compile(context))


@dataclass(frozen=True)
class FailureEntry:
    """One known failure. ``cause``, ``alternative_causes`` and ``next_step`` may contain
    ``{name}``, filled from the pattern's ``name`` group after it passes ``name_format``.
    """

    failure_id: str
    patterns: tuple[LinePattern, ...]
    cause: str
    confidence: Confidence
    alternative_causes: tuple[str, ...]
    next_step: str
    next_step_kind: str
    name_format: re.Pattern[str] | None = None


_PYTHON_MODULE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){0,20}")
# npm package names (optionally scoped) with an optional subpath, like "lodash/fp".
_NODE_PACKAGE = re.compile(
    r"(?:@[a-z0-9][a-z0-9._~-]{0,213}/)?[a-z0-9][a-z0-9._~-]{0,213}(?:/[A-Za-z0-9._~-]{1,100}){0,10}"
)
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")

PYTHON_MISSING_MODULE = FailureEntry(
    failure_id="python_missing_module",
    patterns=(line(r"ModuleNotFoundError: No module named '(?P<name>[^']{1,300})'"),),
    cause=(
        "Python could not import the module '{name}'. It is not installed where the app runs, "
        "or it is not on the import path."
    ),
    confidence=Confidence.MEDIUM,
    alternative_causes=(
        "The package is installed on your machine but missing from the dependency file "
        "(pyproject.toml or requirements.txt), so the deploy never installed it.",
        "'{name}' is your own code, and the app starts from a different folder than "
        "expected, so Python cannot find it.",
        "The import name differs from the package name (for example, 'yaml' comes from "
        "the PyYAML package).",
    ),
    next_step=(
        "Check that the package providing '{name}' is listed in your dependency file and "
        "lockfile, then deploy again. If '{name}' is your own code, check the start "
        "command's working folder."
    ),
    next_step_kind="edit_repo_file",
    name_format=_PYTHON_MODULE,
)

NODE_MISSING_MODULE = FailureEntry(
    failure_id="node_missing_module",
    patterns=(
        # CommonJS require(). Relative ('./x') and absolute paths are excluded on purpose:
        # those are missing files, not missing packages.
        line(r"Error: Cannot find module '(?P<name>[^'./\\][^']{0,300})'"),
        # ES modules (import).
        line(r"Cannot find package '(?P<name>[^'./\\][^']{0,300})' imported from"),
    ),
    cause="Node could not load the package '{name}'. It is not installed where the app runs.",
    confidence=Confidence.HIGH,
    alternative_causes=(
        "'{name}' is listed under devDependencies, and the deploy installs production "
        "dependencies only.",
        "'{name}' is used in the code but missing from package.json, and it only worked "
        "locally because it was installed by hand.",
        "The install step was skipped or cached from an older package.json.",
    ),
    next_step=(
        "Check that '{name}' is listed under dependencies (not devDependencies) in "
        "package.json and in the lockfile, then deploy again."
    ),
    next_step_kind="edit_repo_file",
    name_format=_NODE_PACKAGE,
)

PORT_IN_USE = FailureEntry(
    failure_id="port_in_use",
    patterns=(
        line(r"\bEADDRINUSE\b"),
        line(r"(?i)\[Errno \d+\].*\baddress already in use\b"),
    ),
    cause=(
        "The app tried to listen on a port that another process on the same machine or "
        "container is already using."
    ),
    confidence=Confidence.HIGH,
    alternative_causes=(
        "The app is started twice, for example by both the Dockerfile and a process "
        "manager, and the second copy finds the port taken.",
        "An earlier copy of the app is still running and has not let go of the port.",
    ),
    next_step=(
        "Find what else is listening on that port and make sure only one copy of the app "
        "starts. If the port is taken on purpose, change the app's port setting."
    ),
    next_step_kind="edit_repo_file",
)

NODE_ENGINE_MISMATCH = FailureEntry(
    failure_id="node_engine_mismatch",
    patterns=(
        line(r"npm (?:ERR!|error) code EBADENGINE\b"),
        line(r'The engine "node" is incompatible with this module\.'),
    ),
    cause=(
        "The Node version used by the deploy does not match the version that the project "
        'or one of its packages requires (the "engines" field).'
    ),
    confidence=Confidence.HIGH,
    alternative_causes=(
        'The project\'s own "engines" range is right, but one dependency requires a '
        "newer Node version than the project allows.",
        "The deploy image or platform setting picks a different Node version than "
        ".nvmrc or .node-version says.",
    ),
    next_step=(
        "Compare the wanted and current versions in the lines after this error. Then set "
        "the deploy's Node version to one that satisfies them, for example in the "
        "Dockerfile FROM line or the platform's runtime setting."
    ),
    next_step_kind="change_runtime_version",
)

PYTHON_VERSION_MISMATCH = FailureEntry(
    failure_id="python_version_mismatch",
    patterns=(line(r"requires a different Python: \S+ not in '[^']{1,100}'"),),
    cause=(
        "pip refused to install a package because the Python version used by the deploy "
        "is outside the range that package supports."
    ),
    confidence=Confidence.HIGH,
    alternative_causes=(
        "The project itself needs a newer Python than the deploy image provides.",
        "A dependency was upgraded to a release that dropped support for this Python "
        "version, and its version is not pinned.",
    ),
    next_step=(
        "Set the deploy's Python version to one inside the range shown in this line, for "
        "example in the Dockerfile FROM line, or pin the package to an older release."
    ),
    next_step_kind="change_runtime_version",
)

MISSING_ENV_VAR = FailureEntry(
    failure_id="missing_env_var",
    patterns=(
        # Python os.environ["NAME"]. Upper-case names only: a lower-case KeyError is
        # far more likely an ordinary dictionary.
        # The traceback just above must show os.environ (Python 3.11+ prints "<frozen os>",
        # older versions print the path to os.py).
        line(
            r"^\s*KeyError: '(?P<name>[A-Z_][A-Z0-9_]{0,127})'\s*$",
            context=r"os\.environ|<frozen os>|[\\/]os\.py\"",
        ),
        # Prisma reading DATABASE_URL and similar from schema.prisma.
        line(r"Environment variable not found: (?P<name>[A-Za-z_][A-Za-z0-9_]{0,127})"),
    ),
    cause="The app needs the environment variable {name}, but it is not set where the app runs.",
    confidence=Confidence.HIGH,
    alternative_causes=(
        "{name} is set, but under a slightly different name (spelling or upper/lower case).",
        "{name} is set for the build step but not for the running app, or the other way round.",
    ),
    next_step=(
        "Add {name} to the deploy target's environment settings (the name and its value, "
        "set in the platform, never in the repo), then deploy again."
    ),
    next_step_kind="set_target_env_names",
    name_format=_ENV_NAME,
)

CATALOG: tuple[FailureEntry, ...] = (
    PYTHON_MISSING_MODULE,
    NODE_MISSING_MODULE,
    PORT_IN_USE,
    NODE_ENGINE_MISMATCH,
    PYTHON_VERSION_MISMATCH,
    MISSING_ENV_VAR,
)

# Not a line pattern: the matcher compares this line's port with the expected port.
PORT_MISMATCH_ID = "port_mismatch"
# Uvicorn's startup line, e.g. "Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)".
UVICORN_LISTENING = re.compile(
    r"Uvicorn running on https?://(?:\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]+):(?P<port>\d{1,5})\b"
)
PORT_MISMATCH_CAUSE = (
    "The app started on port {actual}, but the deploy target expects port {expected}, so "
    "the platform's health check and traffic will not reach it."
)
PORT_MISMATCH_ALTERNATIVES = (
    "The expected port given to deploy-agent (--port) is out of date, and {actual} is "
    "actually right.",
    "The start command sets the port from a variable such as PORT that the deploy target "
    "does not set, so the app fell back to its default.",
)
PORT_MISMATCH_NEXT_STEP = (
    "Make the app listen on port {expected}, for example with uvicorn's --port option or "
    "by reading the port from an environment variable. Or, if {actual} is right, update "
    "the target's port setting."
)
PORT_MISMATCH_KIND = "edit_repo_file"
