"""Private worker hand-off at a workflow Python action call."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.workflows.contracts.results import Waiting

MAX_ACTION_CALLS = 100


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


class ScriptResume(BaseModel):
    """The interpreter state plus the durable result of its completed call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    index: int
    alias: str
    checkpoint: str
    stdout: str
    output: dict[str, JsonValue]
