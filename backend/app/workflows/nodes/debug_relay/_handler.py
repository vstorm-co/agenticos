"""`debug.relay`: the second sample node, the one an Echo can be wired to.

`debug.echo` reads `{message}` and emits `{echoed, received_at}`, so two Echo
nodes cannot be connected: an edge needs the source and target ports to carry
the same shape. Relay takes exactly what Echo emits and emits exactly what Echo
reads, which makes Echo -> Relay -> Echo a chain the graph validator accepts.
It reuses Echo's models rather than declaring look-alikes, so the two cannot
drift apart.
"""

from pydantic import BaseModel

from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError
from app.workflows.nodes.debug_echo import DebugEchoConfig, DebugEchoOutput


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Hand the echoed message on as a plain `message`, dropping the timestamp.

    Relay has no fallback: its input is required, so an unbound one is a graph
    that should not have validated, not a value to invent.
    """
    if not isinstance(node_input, DebugEchoOutput):
        return Failed(
            error=WorkflowError(
                code="RELAY_INPUT_MISSING",
                message="debug.relay needs an echoed message on its input port",
            )
        )
    return Completed[DebugEchoConfig](output=DebugEchoConfig(message=node_input.echoed))
