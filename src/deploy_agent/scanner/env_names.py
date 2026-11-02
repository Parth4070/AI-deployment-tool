"""Finds the NAMES of environment variables. Values are never kept.

Only literal names are found. A name built at runtime, like ``os.getenv(prefix + "_KEY")``,
cannot be seen without running the code.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from pydantic import TypeAdapter, ValidationError
from tree_sitter import Node

from deploy_agent.logs.redaction import Redactor
from deploy_agent.models.project import EnvVarName, ScanWarning, ScanWarningCode
from deploy_agent.scanner.files import make_warning
from deploy_agent.scanner.source import node_text, string_value, walk

_PYTHON_READ_CALLS = frozenset({"os.getenv", "getenv", "os.environ.get", "environ.get"})
_PYTHON_ENV_OBJECTS = frozenset({"os.environ", "environ"})
_JAVASCRIPT_ENV_OBJECTS = frozenset({"process.env", "import.meta.env"})

# Uppercase only: a base64 line ending in "=" would otherwise look like a name.
_TEMPLATE_LINE = re.compile(r"\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)\s*=(.*)")

_name_check: TypeAdapter[str] = TypeAdapter(EnvVarName)


@dataclass(frozen=True)
class CleanNames:
    names: tuple[str, ...] = ()
    warnings: tuple[ScanWarning, ...] = ()


def python_env_read(node: Node) -> tuple[str, Node | None] | None:
    """If this node reads a variable, return its name and any default value node."""
    if node.type == "subscript":
        if node_text(node.child_by_field_name("value")) in _PYTHON_ENV_OBJECTS:
            name = string_value(node.child_by_field_name("subscript"))
            return (name, None) if name else None
        return None

    if node.type != "call":
        return None
    if node_text(node.child_by_field_name("function")) not in _PYTHON_READ_CALLS:
        return None
    arguments = node.child_by_field_name("arguments")
    if arguments is None or not arguments.named_children:
        return None
    positional = [child for child in arguments.named_children if child.type != "comment"]
    name = string_value(positional[0]) if positional else None
    if not name:
        return None
    return name, positional[1] if len(positional) > 1 else None


def javascript_env_read(node: Node) -> str | None:
    """If this node reads a variable, return its name."""
    if node.type not in {"member_expression", "subscript_expression"}:
        return None
    if node_text(node.child_by_field_name("object")) not in _JAVASCRIPT_ENV_OBJECTS:
        return None
    if node.type == "subscript_expression":
        return string_value(node.child_by_field_name("index"))
    return node_text(node.child_by_field_name("property")) or None


def _destructured_names(declarator: Node) -> Iterator[str]:
    """Handle ``const { A, B: other, C = 1 } = process.env``."""
    pattern = declarator.child_by_field_name("name")
    value = declarator.child_by_field_name("value")
    if pattern is None or pattern.type != "object_pattern":
        return
    if node_text(value) not in _JAVASCRIPT_ENV_OBJECTS:
        return
    for item in pattern.named_children:
        if item.type == "shorthand_property_identifier_pattern":
            yield node_text(item)
        elif item.type == "pair_pattern":
            yield node_text(item.child_by_field_name("key"))
        elif item.type == "object_assignment_pattern":
            yield node_text(item.child_by_field_name("left"))


def names_from_python(root: Node) -> list[str]:
    reads = (python_env_read(node) for node in walk(root))
    return [read[0] for read in reads if read]


def names_from_javascript(root: Node) -> list[str]:
    names: list[str] = []
    for node in walk(root):
        name = javascript_env_read(node)
        if name:
            names.append(name)
        if node.type == "variable_declarator":
            names.extend(_destructured_names(node))
    return names


def _opens_multi_line_value(value: str) -> str | None:
    """Return the quote character if this value starts a quote it does not close."""
    stripped = value.strip()
    if stripped[:1] in {'"', "'"} and stripped[0] not in stripped[1:]:
        return stripped[0]
    return None


def names_from_template(text: str) -> tuple[str, ...]:
    """Read names from a file like .env.example. The value part of each line is discarded."""
    names: list[str] = []
    open_quote: str | None = None
    for line in text.splitlines():
        if open_quote is not None:
            if open_quote in line:
                open_quote = None
            continue
        match = _TEMPLATE_LINE.fullmatch(line)
        if match:
            names.append(match.group(1))
            open_quote = _opens_multi_line_value(match.group(2))
    return tuple(names)


def _is_valid_name(name: str) -> bool:
    try:
        _name_check.validate_python(name)
    except ValidationError:
        return False
    return True


def clean_env_names(candidates: Iterable[str]) -> CleanNames:
    """Keep valid names. Drop any that look like a secret pasted in as a name by mistake."""
    redactor = Redactor()
    names: set[str] = set()
    suspicious = False
    for name in set(candidates):
        if not _is_valid_name(name):
            continue
        if redactor.redact(name).text == name:
            names.add(name)
        else:
            suspicious = True
    warnings = (make_warning(ScanWarningCode.SUSPICIOUS_ENV_NAME),) if suspicious else ()
    return CleanNames(names=tuple(sorted(names)), warnings=warnings)
