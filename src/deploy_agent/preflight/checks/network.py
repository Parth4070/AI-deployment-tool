"""Will traffic reach the app? Port, listen address and health-check path."""

import re
from pathlib import Path

from deploy_agent.models.common import Severity
from deploy_agent.models.preflight import PreflightResult
from deploy_agent.preflight.context import PreflightContext
from deploy_agent.preflight.evidence import failed, listing, passed, skipped
from deploy_agent.scanner.files import JAVASCRIPT_SUFFIXES, PYTHON_SUFFIXES

_LOCAL_BIND = re.compile(
    r"(?:^|\s)(?:--host|--bind|-b|-H|HOST=|HOSTNAME=)[=\s]*(?:127\.0\.0\.1|localhost)(?![\w.-])"
)
_EXEC_FORM_PUNCTUATION = re.compile(r"""["',\[\]]""")
_SAFE_PATH = re.compile(r"/[A-Za-z0-9._~/-]{0,200}")


def port_consistent(context: PreflightContext) -> PreflightResult:
    name = "port_consistent"
    detected = context.project.ports
    target = context.target.port
    if not detected:
        if target is None:
            return skipped(name, "no port was found and the target port is not known.")
        return passed(name, f"No port found in the project; the target uses {target}.")

    if target is not None and target not in detected:
        return failed(
            name,
            Severity.ERROR,
            f"The app seems to listen on {listing(detected)}, but the target sends traffic "
            f"to {target}.",
            f"Make the app listen on {target} (ideally by reading the PORT variable), or "
            "change the target port to match the app.",
        )
    if len(detected) > 1:
        return failed(
            name,
            Severity.WARNING,
            f"More than one port was found: {listing(detected)}.",
            "Make the app, the Dockerfile EXPOSE line and the start command agree on one "
            "port. A dev-only script with its own port can cause this too.",
        )
    return passed(name, f"Port {detected[0]}.")


def _start_commands(context: PreflightContext) -> list[tuple[str, str]]:
    """Return (where it came from, command). Command text never leaves this module."""
    commands = [("a Dockerfile CMD/ENTRYPOINT", command) for command in context.docker.commands]
    commands += [("a package.json script", script) for script in context.manifests.node_scripts]
    procfile = context.snapshot.texts.get("Procfile", "")
    commands += [("the Procfile", line) for line in procfile.splitlines()]
    return commands


def binds_localhost(command: str) -> bool:
    return _LOCAL_BIND.search(_EXEC_FORM_PUNCTUATION.sub(" ", command)) is not None


def listen_address(context: PreflightContext) -> PreflightResult:
    name = "listen_address"
    commands = _start_commands(context)
    if not commands:
        return skipped(name, "no start command was found.")

    local = sorted({source for source, command in commands if binds_localhost(command)})
    if local:
        return failed(
            name,
            Severity.ERROR,
            f"The app is told to listen on 127.0.0.1/localhost in {listing(local)}. Traffic "
            "from outside the container or server cannot reach it.",
            "Listen on 0.0.0.0 instead, for example `--host 0.0.0.0`.",
        )
    return passed(name)


def _route_appears(path: str, sources: list[str]) -> bool:
    """Look for the path as a quoted string. Also tries the forms Django uses: 'health/'."""
    trimmed = path.strip("/")
    forms = {path, path.rstrip("/") or "/", trimmed, f"{trimmed}/"} - {"", "/"} or {"/"}
    pattern = re.compile(
        "[\"'`](?:" + "|".join(re.escape(form) for form in sorted(forms)) + ")[\"'`]"
    )
    return any(pattern.search(text) for text in sources)


def health_check_path(context: PreflightContext) -> PreflightResult:
    name = "health_check_path"
    if context.target.health_check_path is not None:
        path, origin = context.target.health_check_path, "the deploy target"
    elif context.docker.healthcheck_path is not None:
        path, origin = context.docker.healthcheck_path, "the Dockerfile HEALTHCHECK"
    else:
        return skipped(name, "no health-check path is set.")

    if not _SAFE_PATH.fullmatch(path):
        # The path is not echoed: it failed the safe format, so it could hold anything.
        return failed(
            name,
            Severity.WARNING,
            f"The health-check path from {origin} is not a plain path. It must start with / "
            "and contain no spaces, query string (?) or fragment (#).",
            "Use a plain path such as /health or /healthz.",
        )

    code_suffixes = PYTHON_SUFFIXES | JAVASCRIPT_SUFFIXES
    sources = [
        text
        for file, text in context.snapshot.texts.items()
        if Path(file).suffix.lower() in code_suffixes
    ]
    if not sources:
        return skipped(name, "no Python or JavaScript source was found to compare against.")
    if _route_appears(path, sources):
        return passed(name, f"{path} appears in the source code.")
    return failed(
        name,
        Severity.WARNING,
        f"The health-check path {path} from {origin} does not appear in the source code, "
        "so the health check may get a 404 and the deploy may be marked as failed.",
        f"Add a route for {path} that returns 200, or point the health check at a route "
        "that exists. If the route is built at runtime, you can ignore this warning.",
    )
