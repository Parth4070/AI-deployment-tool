"""Parses source code into trees without running it.

The parser understands code structure, so a variable mentioned in a comment or a string is
not mistaken for a real read. It also keeps going past syntax errors, and the JavaScript
grammar still finds expressions in most TypeScript files.
"""

from collections.abc import Iterator

import tree_sitter_javascript
import tree_sitter_python
from tree_sitter import Language, Node, Parser

_python_parser = Parser(Language(tree_sitter_python.language()))
_javascript_parser = Parser(Language(tree_sitter_javascript.language()))

_STRING_DELIMITERS = frozenset({"string_start", "string_end"})
_STRING_CONTENT = frozenset({"string_content", "string_fragment"})
_NUMBER_TYPES = frozenset({"integer", "number"})


def parse_python(text: str) -> Node:
    return _python_parser.parse(text.encode("utf-8", errors="replace")).root_node


def parse_javascript(text: str) -> Node:
    return _javascript_parser.parse(text.encode("utf-8", errors="replace")).root_node


def walk(root: Node) -> Iterator[Node]:
    """Visit every node. Uses a stack, so deeply nested files cannot overflow recursion."""
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(node.children)


def node_text(node: Node | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.decode("utf-8", errors="replace")


def string_value(node: Node | None) -> str | None:
    """Return a plain string's text. Strings built at runtime return None."""
    if node is None or node.type != "string":
        return None
    parts = [child for child in node.named_children if child.type not in _STRING_DELIMITERS]
    if len(parts) != 1 or parts[0].type not in _STRING_CONTENT:
        return None
    return node_text(parts[0])


def int_value(node: Node | None) -> int | None:
    """Return the number in a number literal, or in a string that holds only digits."""
    if node is None:
        return None
    text = node_text(node) if node.type in _NUMBER_TYPES else string_value(node)
    return int(text) if text and len(text) <= 5 and text.isascii() and text.isdigit() else None
