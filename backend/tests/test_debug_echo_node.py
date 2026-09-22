"""`debug.echo`: the sample node's handler and its registration.

AC1 of #1786: a documented sample action node added with model + handler +
registration + tests, without editing executor dispatch - there is no
executor for this diff to edit, and none of these tests touches one.
"""

import pytest

from app.workflows._registry import all_node_definitions, get, load_builtins
from app.workflows.contracts.results import Completed
from app.workflows.nodes.debug_echo import DebugEchoConfig, DebugEchoOutput
from app.workflows.nodes.debug_echo._handler import handle

pytestmark = pytest.mark.anyio


async def test_handle_echoes_the_configured_message_when_nothing_is_bound():
    result = await handle(DebugEchoConfig(message="hello"), None)
    assert isinstance(result, Completed)
    assert isinstance(result.output, DebugEchoOutput)
    assert result.output.echoed == "hello"


async def test_handle_prefers_a_bound_input_over_the_configured_message():
    result = await handle(DebugEchoConfig(message="default"), DebugEchoConfig(message="bound"))
    assert isinstance(result, Completed)
    assert result.output.echoed == "bound"


async def test_handle_falls_back_to_config_when_the_bound_input_is_empty():
    result = await handle(DebugEchoConfig(message="default"), DebugEchoConfig(message=""))
    assert isinstance(result, Completed)
    assert result.output.echoed == "default"


async def test_handle_with_no_config_and_no_input_echoes_the_empty_string():
    result = await handle(None, None)
    assert isinstance(result, Completed)
    assert result.output.echoed == ""


def test_debug_echo_is_reachable_through_the_registry_after_load_builtins():
    load_builtins()
    definition = get("debug.echo", 1)
    assert definition.name == "Echo"
    assert definition.kind == "action"
    assert definition.effect_kind == "pure"
    assert definition.retry_guarantee == "idempotent"
    assert definition.handler is handle
    assert definition in all_node_definitions()


def test_debug_echo_declares_both_its_ports():
    definition = get("debug.echo", 1)
    ports = {port.id: port for port in definition.ports}
    assert ports["in"].kind == "input"
    assert ports["out"].kind == "output"
    assert ports["in"].schema is DebugEchoConfig
    assert ports["out"].schema is DebugEchoOutput
