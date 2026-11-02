"""Finds ports the app seems to use. Other ports, such as a database's, are left out on purpose."""

import re
from collections.abc import Iterable

from tree_sitter import Node

from deploy_agent.scanner.env_names import javascript_env_read, python_env_read
from deploy_agent.scanner.source import int_value, node_text, walk

_PORT_NAME = re.compile(r"(?:app_|server_|http_)?port", re.IGNORECASE)
_COMMAND_PORT = re.compile(
    r"(?:(?:^|\s)(?:--port|--bind|-b|-p)[=\s]+|\brunserver\s+|(?:^|\s)PORT=)"
    r"(?:[\w.*\[\]-]*:)?(\d{2,5})\b"
)
_EXEC_FORM_PUNCTUATION = re.compile(r"""["',\[\]]""")


def ports_from_command(command: str) -> list[int]:
    """Search a shell or Dockerfile command for a port."""
    plain = _EXEC_FORM_PUNCTUATION.sub(" ", command)
    return [int(port) for port in _COMMAND_PORT.findall(plain)]


def _named_port_assignment(name: Node | None, value: Node | None) -> int | None:
    if name is None or name.type != "identifier" or not _PORT_NAME.fullmatch(node_text(name)):
        return None
    return int_value(value)


def _python_run_call_port(node: Node) -> int | None:
    """Handle ``app.run(port=5000)`` and ``uvicorn.run(app, port=8000)``."""
    if not node_text(node.child_by_field_name("function")).endswith(".run"):
        return None
    arguments = node.child_by_field_name("arguments")
    for argument in arguments.named_children if arguments else ():
        if argument.type == "keyword_argument":
            if node_text(argument.child_by_field_name("name")) == "port":
                return int_value(argument.child_by_field_name("value"))
    return None


def ports_from_python(root: Node) -> list[int]:
    ports: list[int | None] = []
    for node in walk(root):
        read = python_env_read(node)
        if read and read[1] is not None and _PORT_NAME.fullmatch(read[0]):
            ports.append(int_value(read[1]))
        elif node.type == "call":
            ports.append(_python_run_call_port(node))
        elif node.type == "assignment":
            ports.append(
                _named_port_assignment(
                    node.child_by_field_name("left"), node.child_by_field_name("right")
                )
            )
    return [port for port in ports if port is not None]


def _javascript_listen_port(node: Node) -> int | None:
    """Handle ``app.listen(3000)`` and ``server.listen({ port: 3000 })``."""
    function = node.child_by_field_name("function")
    if function is None or function.type != "member_expression":
        return None
    if node_text(function.child_by_field_name("property")) != "listen":
        return None
    arguments = node.child_by_field_name("arguments")
    if arguments is None or not arguments.named_children:
        return None
    first = arguments.named_children[0]
    if first.type != "object":
        return int_value(first)
    for pair in first.named_children:
        if pair.type == "pair" and node_text(pair.child_by_field_name("key")) == "port":
            return int_value(pair.child_by_field_name("value"))
    return None


def _javascript_env_default(node: Node) -> int | None:
    """Handle ``process.env.PORT || 3000`` and the same with ``??``."""
    if node_text(node.child_by_field_name("operator")) not in {"||", "??"}:
        return None
    left = node.child_by_field_name("left")
    name = javascript_env_read(left) if left is not None else None
    if not name or not _PORT_NAME.fullmatch(name):
        return None
    return int_value(node.child_by_field_name("right"))


def ports_from_javascript(root: Node) -> list[int]:
    ports: list[int | None] = []
    for node in walk(root):
        if node.type == "call_expression":
            ports.append(_javascript_listen_port(node))
        elif node.type == "binary_expression":
            ports.append(_javascript_env_default(node))
        elif node.type == "variable_declarator":
            ports.append(
                _named_port_assignment(
                    node.child_by_field_name("name"), node.child_by_field_name("value")
                )
            )
    return [port for port in ports if port is not None]


def clean_ports(ports: Iterable[int]) -> tuple[int, ...]:
    return tuple(sorted({port for port in ports if 1 <= port <= 65535}))
