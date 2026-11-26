"""Private worker hand-off at a workflow Python action call."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from app.workflows.contracts.results import Waiting

MAX_ACTION_CALLS = 100


def _jsonb_number_forms(value: JsonValue) -> JsonValue:
    """Match the numeric forms read back by the JSON decoder after a JSONB write."""
    if isinstance(value, dict):
        return {key: _jsonb_number_forms(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonb_number_forms(item) for item in value]
    if isinstance(value, float):
        if value == 0:
            return 0.0  # JSONB drops the negative sign.
        decimal_text = repr(value)
        if "e+" in decimal_text:
            # Python emits a positive exponent only for large integral floats.
            # JSONB expands the JSON *decimal*, not the exact binary float.
            return int(Decimal(decimal_text))
    return value


class ScriptActionRequest(Waiting):
    """An interpreter suspended before calling an alias from its frozen node config.

    The checkpoint and inputs are stored on the parent row, never on a public
    attempt or event. The child is queued in the same transaction.
    """

    reason: Literal["external_event"] = "external_event"
    alias: str
    index: int = Field(ge=0, lt=MAX_ACTION_CALLS)
    inputs: dict[str, JsonValue]
    checkpoint: str
    stdout: str

    @field_validator("inputs")
    @classmethod
    def _durable_inputs(cls, inputs: dict[str, JsonValue]) -> dict[str, JsonValue]:
        # Scope digests and size reservations must see the same numbers before
        # and after dispatch. Preserve ordinary floats and arbitrary-size ints.
        return {key: _jsonb_number_forms(item) for key, item in inputs.items()}


class ScriptResume(BaseModel):
    """The interpreter state plus the durable result of its completed call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    index: int
    alias: str
    checkpoint: str
    stdout: str
    output: dict[str, JsonValue]
