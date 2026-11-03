"""Pulls facts out of a Dockerfile. ENV and ARG values are thrown away; only names are kept."""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ASSIGNMENT = re.compile(r"""([A-Za-z_][A-Za-z0-9_]*)=("(?:[^"\\]|\\.)*"|'[^']*'|\S*)""")
_PORT_ASSIGNMENT = re.compile(r"""(?:^|\s)PORT[=\s]["']?(\d+)""")
_EXPOSED_PORT = re.compile(r"(\d{1,5})(?:/(?:tcp|udp))?", re.IGNORECASE)
_IMAGE_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_URL_PATH = re.compile(r"https?://[^/\s\"']+(/[A-Za-z0-9._~/-]*)")
_SAFE_PATH = re.compile(r"/[A-Za-z0-9._~/-]{0,200}")
_EXEC_FORM_PUNCTUATION = re.compile(r"""["',\[\]]""")

# A name that looks like it holds a secret. Names ending in _FILE or _PATH point at a
# secret instead of holding one, which is the safe pattern, so they are left out.
_SECRET_NAME = re.compile(
    r"(SECRET|PASSWORD|PASSWD|TOKEN|PRIVATE|CREDENTIAL|API_?KEY|ACCESS_?KEY|(^|_)KEY$)"
)
_POINTER_SUFFIXES = ("_FILE", "_PATH", "_DIR", "_NAME")


class ImageKind(StrEnum):
    EXTERNAL = "external"  # pulled from a registry, so its tag matters
    STAGE = "stage"  # FROM an earlier build stage, like ``FROM build``
    SCRATCH = "scratch"  # the empty image
    VARIABLE = "variable"  # ``FROM ${BASE}``: unknown until build time


@dataclass(frozen=True)
class BaseImage:
    line: int
    kind: ImageKind
    name: str | None  # only set when it fits a strict format, so it is safe to show
    tag: str
    has_digest: bool


@dataclass(frozen=True)
class DockerfileInfo:
    images: tuple[tuple[str, str], ...] = ()
    ports: tuple[int, ...] = ()
    env_names: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    # Facts for preflight. Values are never stored, only names and line numbers.
    base_images: tuple[BaseImage, ...] = ()
    has_start_command: bool = False
    final_user_is_root: bool | None = None  # None: the last stage has no USER line
    copies_whole_context: bool = False
    secret_assignments: tuple[tuple[str, int], ...] = ()  # (name, line)
    healthcheck_path: str | None = None


def logical_lines(text: str) -> Iterator[tuple[int, str]]:
    """Yield (first line number, instruction), joining lines that end in a backslash."""
    start: int | None = None
    parts: list[str] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if start is None:
            start = number
        stripped = raw.rstrip()
        if stripped.endswith("\\"):
            parts.append(stripped[:-1])
            continue
        parts.append(stripped)
        yield start, " ".join(parts)
        start, parts = None, []
    if start is not None:
        yield start, " ".join(parts)


def _parse_image(arguments: str) -> tuple[str, str] | None:
    tokens = [token for token in arguments.split() if not token.startswith("--")]
    if not tokens:
        return None
    image = tokens[0].split("@")[0]
    name_part, _, tag = image.rpartition(":") if ":" in image else (image, "", "")
    if "/" in tag:
        name_part, tag = image, ""
    return name_part.rsplit("/", 1)[-1].lower(), tag


def _base_image(line: int, arguments: str, stages: set[str]) -> BaseImage | None:
    tokens = [token for token in arguments.split() if not token.startswith("--")]
    parsed = _parse_image(arguments)
    if not tokens or parsed is None:
        return None
    reference = tokens[0].lower()
    name, tag = parsed
    if "$" in reference:
        kind = ImageKind.VARIABLE
    elif reference in stages:
        kind = ImageKind.STAGE
    elif reference == "scratch":
        kind = ImageKind.SCRATCH
    else:
        kind = ImageKind.EXTERNAL
    if len(tokens) >= 3 and tokens[1].lower() == "as":
        stages.add(tokens[2].lower())
    safe_name = name if _IMAGE_NAME.fullmatch(name) else None
    safe_tag = tag if _IMAGE_NAME.fullmatch(tag) else ""
    return BaseImage(line, kind, safe_name, safe_tag, has_digest="@" in tokens[0])


def _assignments(arguments: str) -> list[tuple[str, bool]]:
    """Return (name, has a non-empty value) for each ENV assignment. Values are dropped."""
    tokens = arguments.split()
    if not tokens:
        return []
    if "=" not in tokens[0]:  # legacy form: ENV NAME value
        return [(tokens[0], len(tokens) > 1)] if _NAME.fullmatch(tokens[0]) else []
    return [
        (match.group(1), match.group(2) not in {"", '""', "''"})
        for match in _ASSIGNMENT.finditer(arguments)
    ]


def _arg_assignment(arguments: str) -> list[tuple[str, bool]]:
    name, equals, value = arguments.partition("=")
    name = name.strip()
    has_value = bool(equals) and value.strip() not in {"", '""', "''"}
    return [(name, has_value)] if _NAME.fullmatch(name) else []


def looks_like_secret_name(name: str) -> bool:
    upper = name.upper()
    return bool(_SECRET_NAME.search(upper)) and not upper.endswith(_POINTER_SUFFIXES)


def _copies_whole_context(arguments: str) -> bool:
    tokens = _EXEC_FORM_PUNCTUATION.sub(" ", arguments).split()
    if any(token.startswith("--from") for token in tokens):
        return False  # copying out of another stage, not from the build context
    sources = [token for token in tokens if not token.startswith("--")][:-1]
    return any(source in {".", "./"} for source in sources)


def _is_root(user: str) -> bool:
    return user.split(":", 1)[0].strip() in {"root", "0"}


def _healthcheck_path(arguments: str) -> str | None:
    match = _URL_PATH.search(arguments)
    if match and _SAFE_PATH.fullmatch(match.group(1)):
        return match.group(1)
    return None


def parse_dockerfile(text: str) -> DockerfileInfo:
    images: list[tuple[str, str]] = []
    ports: list[int] = []
    env_names: list[str] = []
    commands: list[str] = []
    base_images: list[BaseImage] = []
    stages: set[str] = set()
    secrets: list[tuple[str, int]] = []
    has_start_command = False
    stage_user: str | None = None
    copies_whole_context = False
    healthcheck_path: str | None = None

    for number, joined in logical_lines(text):
        line = joined.strip()
        if not line or line.startswith("#"):
            continue
        keyword, _, arguments = line.partition(" ")
        keyword = keyword.upper()
        arguments = arguments.strip()
        if keyword == "FROM":
            image = _parse_image(arguments)
            if image is not None:
                images.append(image)
            base = _base_image(number, arguments, stages)
            if base is not None:
                base_images.append(base)
            stage_user = None  # each stage starts again as the image's default user
        elif keyword == "EXPOSE":
            matches = (_EXPOSED_PORT.fullmatch(token) for token in arguments.split())
            ports.extend(int(match.group(1)) for match in matches if match)
        elif keyword in {"ENV", "ARG"}:
            pairs = _assignments(arguments) if keyword == "ENV" else _arg_assignment(arguments)
            env_names.extend(name for name, _ in pairs)
            secrets.extend(
                (name, number)
                for name, has_value in pairs
                if has_value and looks_like_secret_name(name)
            )
            if keyword == "ENV":
                commands.extend(f"PORT={port}" for port in _PORT_ASSIGNMENT.findall(arguments))
        elif keyword in {"CMD", "ENTRYPOINT"}:
            commands.append(arguments)
            has_start_command = True
        elif keyword == "USER":
            stage_user = arguments
        elif keyword in {"COPY", "ADD"}:
            copies_whole_context = copies_whole_context or _copies_whole_context(arguments)
        elif keyword == "HEALTHCHECK":
            healthcheck_path = _healthcheck_path(arguments)

    return DockerfileInfo(
        images=tuple(images),
        ports=tuple(ports),
        env_names=tuple(env_names),
        commands=tuple(commands),
        base_images=tuple(base_images),
        has_start_command=has_start_command,
        final_user_is_root=None if stage_user is None else _is_root(stage_user),
        copies_whole_context=copies_whole_context,
        secret_assignments=tuple(secrets),
        healthcheck_path=healthcheck_path,
    )
