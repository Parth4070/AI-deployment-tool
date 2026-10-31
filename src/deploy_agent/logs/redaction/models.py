"""Data shapes for the redactor. None of the output models ever carry a secret value."""

from enum import StrEnum
from typing import Annotated

from pydantic import SecretStr, StringConstraints

from deploy_agent.models.common import StrictModel

PlaceholderLabel = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9_]{0,63}$")]


class RedactionLayer(StrEnum):
    KNOWN_VALUE = "known_value"
    CONNECTION_STRING = "connection_string"
    PATTERN = "pattern"
    ENTROPY = "entropy"


class KnownSecret(StrictModel):
    """A value the program holds, and the name used for its placeholder."""

    name: PlaceholderLabel
    value: SecretStr


class Finding(StrictModel):
    """What was removed: which layer, what kind, how many. Never the value itself."""

    layer: RedactionLayer
    label: PlaceholderLabel
    count: int


class RedactionResult(StrictModel):
    text: str
    findings: tuple[Finding, ...]
