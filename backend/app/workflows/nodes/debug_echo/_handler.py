"""`debug.echo`: the one sample node, and what makes it a complete example.

It has no real effect - which is the point. #1786 exists to prove the
contract a node is written against (a typed config, a typed input, a typed
output, a handler returning `NodeResult`) works end to end with no executor
yet to call it. Every real node #1789/#1790/#1791/#1792 add follows this same
three-file shape.
"""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.workflows.contracts.results import Completed, NodeResult


class DebugEchoConfig(BaseModel):
    """The message to echo - configured on the node, or bound to its `in` port."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str = Field(default="", max_length=4000)


class DebugEchoOutput(BaseModel):
    """What `out` carries: the message, and when the node ran."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    echoed: str
    received_at: datetime


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Echo the configured or bound message back, stamped with the current time.

    `node_input` wins when the `in` port is bound to something - a graph
    author may wire another node's output into it rather than typing a
    constant - and the node's own `config.message` is the fallback a graph
    with nothing bound to `in` still runs with.
    """
    message = config.message if isinstance(config, DebugEchoConfig) else ""
    if isinstance(node_input, DebugEchoConfig) and node_input.message:
        message = node_input.message
    return Completed[DebugEchoOutput](
        output=DebugEchoOutput(echoed=message, received_at=datetime.now(UTC))
    )
