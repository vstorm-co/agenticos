"""`debug.relay`: the sample node an Echo can be connected to.

Echo's output and input carry different shapes, so two Echo nodes cannot be
joined by an edge. These tests pin what Relay is for: chains through it validate.
"""

from uuid import UUID, uuid4

import pytest

from app.core.permissions import AuthContext, OrgRoleName
from app.workflows._registry import all_node_definitions, get, load_builtins
from app.workflows.contracts.io import Binding, NodeOutputRef
from app.workflows.contracts.results import Completed, Failed
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import validate_graph
from app.workflows.nodes.debug_echo import DebugEchoConfig, DebugEchoOutput
from app.workflows.nodes.debug_relay._handler import handle

pytestmark = pytest.mark.anyio


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER.value)


def _node(definition_id: str, config: dict | None = None) -> NodeInstance:
    return NodeInstance(
        id=uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
    )


def _edge(source: NodeInstance, target: NodeInstance) -> Edge:
    return Edge(
        id=uuid4(),
        source_node_id=source.id,
        source_port="out",
        target_node_id=target.id,
        target_port="in",
    )


def _feed(source: NodeInstance, target: NodeInstance) -> list[Binding]:
    """Bind a Relay's two required inputs from an Echo's output fields."""
    return [
        Binding(
            target_node_id=target.id,
            target_field=field,
            source=NodeOutputRef(node_id=source.id, port="out", field_path=(field,)),
        )
        for field in ("echoed", "received_at")
    ]


async def test_handle_relays_the_echoed_message_as_a_plain_message():
    echoed = DebugEchoOutput.model_validate(
        {"echoed": "hello", "received_at": "2026-09-28T09:00:00Z"}
    )
    result = await handle(None, echoed)
    assert isinstance(result, Completed)
    assert result.output == DebugEchoConfig(message="hello")


@pytest.mark.parametrize("node_input", [None, DebugEchoConfig(message="not an echo output")])
async def test_handle_fails_rather_than_inventing_a_message_without_an_echoed_input(node_input):
    result = await handle(None, node_input)
    assert isinstance(result, Failed)
    assert result.error.code == "RELAY_INPUT_MISSING"
    assert result.error.retryable is False


def test_debug_relay_is_reachable_through_the_registry_after_load_builtins():
    load_builtins()
    definition = get("debug.relay", 1)
    assert definition.name == "Relay"
    assert definition.kind == "action"
    assert definition.config_schema is None
    assert definition.effect_kind == "pure"
    assert definition.retry_guarantee == "idempotent"
    assert definition.handler is handle
    assert definition in all_node_definitions()


def test_debug_relay_takes_echos_output_and_returns_echos_input():
    definition = get("debug.relay", 1)
    ports = {port.id: port for port in definition.ports}
    assert ports["in"].kind == "input"
    assert ports["out"].kind == "output"
    assert ports["in"].schema is DebugEchoOutput
    assert ports["out"].schema is DebugEchoConfig


async def test_an_echo_feeding_a_relay_validates(mock_db_session):
    echo, relay = _node("debug.echo", {"message": "hi"}), _node("debug.relay")
    graph = WorkflowGraph(
        entry_node_id=echo.id,
        nodes=(echo, relay),
        edges=(_edge(echo, relay),),
        bindings=tuple(_feed(echo, relay)),
    )
    validated = await validate_graph(mock_db_session, _ctx(), graph)
    assert isinstance(validated.entry_node_id, UUID)


async def test_a_relay_can_feed_an_echo_back_so_the_chain_is_any_length(mock_db_session):
    first, relay, last = (
        _node("debug.echo", {"message": "hi"}),
        _node("debug.relay"),
        _node("debug.echo", {"message": "unused"}),
    )
    graph = WorkflowGraph(
        entry_node_id=first.id,
        nodes=(first, relay, last),
        edges=(_edge(first, relay), _edge(relay, last)),
        bindings=tuple(_feed(first, relay)),
    )
    await validate_graph(mock_db_session, _ctx(), graph)


async def test_two_echoes_still_cannot_be_joined_directly(mock_db_session):
    """The reason Relay exists: Echo's `out` is not the shape of Echo's `in`."""
    first, second = _node("debug.echo", {"message": "a"}), _node("debug.echo", {"message": "b"})
    graph = WorkflowGraph(
        entry_node_id=first.id, nodes=(first, second), edges=(_edge(first, second),)
    )
    with pytest.raises(GraphValidationError) as raised:
        await validate_graph(mock_db_session, _ctx(), graph)
    assert "incompatible shapes" in str(raised.value.details)
