"""Building blocks shared by every model."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints


class StrictModel(BaseModel):
    """Base for all models: no coercion, no unknown fields, no changes after creation.

    Rejected input stays out of error messages because it may contain a secret.
    """

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )


class SafetyTier(StrEnum):
    AUTO = "auto"
    NEEDS_APPROVAL = "needs_approval"
    MANUAL = "manual"
    FORBIDDEN = "forbidden"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

Label = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")]
