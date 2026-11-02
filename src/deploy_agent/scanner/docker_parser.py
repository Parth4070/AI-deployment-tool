"""Pulls facts out of a Dockerfile. ENV and ARG values are thrown away; only names are kept."""

import re
from dataclasses import dataclass

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ASSIGNMENT = re.compile(r"""([A-Za-z_][A-Za-z0-9_]*)=(?:"(?:[^"\\]|\\.)*"|'[^']*'|\S*)""")
_PORT_ASSIGNMENT = re.compile(r"""(?:^|\s)PORT[=\s]["']?(\d+)""")
_EXPOSED_PORT = re.compile(r"(\d{1,5})(?:/(?:tcp|udp))?", re.IGNORECASE)


@dataclass(frozen=True)
class DockerfileInfo:
    images: tuple[tuple[str, str], ...] = ()
    ports: tuple[int, ...] = ()
    env_names: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()


def _parse_image(arguments: str) -> tuple[str, str] | None:
    tokens = [token for token in arguments.split() if not token.startswith("--")]
    if not tokens:
        return None
    image = tokens[0].split("@")[0]
    name_part, _, tag = image.rpartition(":") if ":" in image else (image, "", "")
    if "/" in tag:
        name_part, tag = image, ""
    return name_part.rsplit("/", 1)[-1].lower(), tag


def _env_names(arguments: str) -> list[str]:
    tokens = arguments.split()
    if not tokens:
        return []
    if "=" not in tokens[0]:
        return [tokens[0]] if _NAME.fullmatch(tokens[0]) else []
    return [match.group(1) for match in _ASSIGNMENT.finditer(arguments)]


def _arg_name(arguments: str) -> list[str]:
    name = arguments.split("=", 1)[0].strip()
    return [name] if _NAME.fullmatch(name) else []


def parse_dockerfile(text: str) -> DockerfileInfo:
    images: list[tuple[str, str]] = []
    ports: list[int] = []
    env_names: list[str] = []
    commands: list[str] = []

    joined = text.replace("\\\r\n", " ").replace("\\\n", " ")
    for raw_line in joined.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        keyword, _, arguments = line.partition(" ")
        keyword = keyword.upper()
        arguments = arguments.strip()
        if keyword == "FROM":
            image = _parse_image(arguments)
            if image is not None:
                images.append(image)
        elif keyword == "EXPOSE":
            matches = (_EXPOSED_PORT.fullmatch(token) for token in arguments.split())
            ports.extend(int(match.group(1)) for match in matches if match)
        elif keyword == "ENV":
            env_names.extend(_env_names(arguments))
            commands.extend(f"PORT={port}" for port in _PORT_ASSIGNMENT.findall(arguments))
        elif keyword == "ARG":
            env_names.extend(_arg_name(arguments))
        elif keyword in {"CMD", "ENTRYPOINT"}:
            commands.append(arguments)

    return DockerfileInfo(
        images=tuple(images),
        ports=tuple(ports),
        env_names=tuple(env_names),
        commands=tuple(commands),
    )
