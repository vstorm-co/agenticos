"""Tests for `validate_graph`: one test per rule, refusing with actionable errors.

AC2 of #1786: invalid imports/graphs, missing versions, inaccessible resources
and unavailable branch bindings fail publication with actionable errors.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict

from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.repositories import virtual_table_repo
from app.workflows._registry import REGISTRY, register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.contracts.io import Binding, FileRef, LiteralValue, NodeOutputRef, TableIORef
from app.workflows.contracts.policy import NodePolicy
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, ScopeBoundary, WorkflowGraph
from app.workflows.graph.validate import derive_scopes, validate_graph

pytestmark = pytest.mark.anyio


def _owner_ctx() -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER.value)


def _pos() -> NodePosition:
    return NodePosition(x=0, y=0)


def _echo_node(node_id: UUID | None = None, *, config: dict | None = None) -> NodeInstance:
    return NodeInstance(
        id=node_id or uuid4(),
        definition_id="debug.echo",
        definition_version=1,
        config=config or {"message": "hi"},
        layout=_pos(),
    )


def _edge(source: UUID, source_port: str, target: UUID, target_port: str) -> Edge:
    return Edge(
        id=uuid4(),
        source_node_id=source,
        source_port=source_port,
        target_node_id=target,
        target_port=target_port,
    )


def _one_node_graph() -> tuple[UUID, WorkflowGraph]:
    entry = _echo_node()
    return entry.id, WorkflowGraph(entry_node_id=entry.id, nodes=(entry,))


@pytest.fixture
def registered_node():
    """Register a synthetic node definition, cleaned up afterward."""
    created: list[tuple[str, int]] = []

    def _register(definition: NodeDefinition) -> NodeDefinition:
        register(definition)
        created.append((definition.id, definition.version))
        return definition

    yield _register
    for node_id, version in created:
        REGISTRY.get(node_id, {}).pop(version, None)
        if not REGISTRY.get(node_id):
            REGISTRY.pop(node_id, None)


class _RequiredInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    value: str


class _PlainOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    value: str


class _OptionalInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    value: str = "default"


def _action_definition(
    node_id: str, *, requires_input: bool = True, port_schema: type[BaseModel] | None = None
) -> NodeDefinition:
    """A minimal action node for topology tests.

    `port_schema` is the **port's** declared shape (what rule 3 compares an
    edge against) and is `None` - a pure control port - by default, so an
    edge from any node can trigger it. `requires_input` instead controls
    `input_schema`, which is what rule 9 checks for an unbound required
    field; the two are independent; a node can require a field to be bound
    while still accepting a control-only edge.
    """
    return NodeDefinition(
        id=node_id,
        version=1,
        name=node_id,
        category="test",
        description="test node",
        kind="action",
        config_schema=None,
        input_schema=_RequiredInput if requires_input else None,
        output_schema=_PlainOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=port_schema),
            Port(id="out", label="Out", kind="output", schema=_PlainOutput),
        ),
        effect_kind="pure",
        retry_guarantee="idempotent",
    )


# Happy path


async def test_a_single_node_graph_with_no_bindings_publishes(mock_db_session):
    _, graph = _one_node_graph()
    validated = await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert validated.entry_node_id == graph.entry_node_id


# Graph size ceiling - checked before anything else, including derive_scopes


async def test_a_graph_over_the_node_ceiling_is_refused_before_anything_else(
    mock_db_session, monkeypatch
):
    """The ceiling exists to keep `analyze_graph`'s O(n^2) retained ancestor
    sets bounded, so it is checked ahead of every other pass - a graph this
    oversized never even reaches `derive_scopes`' own per-scope BFS."""
    monkeypatch.setattr(settings, "WORKFLOW_GRAPH_MAX_NODES", 1)
    a, b = _echo_node(), _echo_node()
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(
        f["field"] == "nodes" and "at most 1" in f["message"]
        for f in excinfo.value.details["fields"]
    )


async def test_a_graph_over_the_edge_ceiling_is_refused(mock_db_session, monkeypatch):
    monkeypatch.setattr(settings, "WORKFLOW_GRAPH_MAX_EDGES", 0)
    a, b = _echo_node(), _echo_node()
    edge = _edge(a.id, "out", b.id, "in")
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=(edge,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(f["field"] == "edges" for f in excinfo.value.details["fields"])


async def test_a_graph_over_the_binding_ceiling_is_refused(mock_db_session, monkeypatch):
    monkeypatch.setattr(settings, "WORKFLOW_GRAPH_MAX_BINDINGS", 0)
    a, b = _echo_node(), _echo_node()
    edge = _edge(a.id, "out", b.id, "in")
    binding = Binding(target_node_id=b.id, target_field="message", source=LiteralValue(value="hi"))
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=(edge,), bindings=(binding,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(f["field"] == "bindings" for f in excinfo.value.details["fields"])


# Pass 0 - resource resolution


async def test_an_unknown_node_definition_is_refused(mock_db_session):
    node = _echo_node()
    node = node.model_copy(update={"definition_id": "no.such.node"})
    graph = WorkflowGraph(entry_node_id=node.id, nodes=(node,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    fields = excinfo.value.details["fields"]
    assert any(f"nodes.{node.id}" == f["field"] for f in fields)


async def test_an_unknown_node_version_is_refused(mock_db_session):
    node = _echo_node().model_copy(update={"definition_version": 99})
    graph = WorkflowGraph(entry_node_id=node.id, nodes=(node,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert "nodes." in excinfo.value.details["fields"][0]["field"]


async def test_a_node_requiring_an_ungranted_scope_is_refused(mock_db_session, registered_node):
    definition = registered_node(
        NodeDefinition(
            id="test.scoped",
            version=1,
            name="Scoped",
            category="test",
            description="needs a scope nobody granted",
            kind="action",
            config_schema=None,
            input_schema=None,
            output_schema=None,
            ports=(),
            effect_kind="write",
            retry_guarantee="none",
            scopes=frozenset({"no:such:scope"}),
        )
    )
    node = NodeInstance(
        id=uuid4(), definition_id=definition.id, definition_version=1, config={}, layout=_pos()
    )
    graph = WorkflowGraph(entry_node_id=node.id, nodes=(node,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any("not granted" in f["message"] for f in excinfo.value.details["fields"])


async def test_config_that_fails_its_schema_is_refused(mock_db_session):
    node = _echo_node(config={"message": 12345, "extra": "nope"})
    graph = WorkflowGraph(entry_node_id=node.id, nodes=(node,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(f"nodes.{node.id}" in f["field"] for f in excinfo.value.details["fields"])
    # `include_input=False`: the rejected value itself never reaches the
    # response - only that `message` was the wrong shape, not what was sent.
    rendered = str(excinfo.value.details)
    assert "12345" not in rendered


async def test_config_on_a_node_that_declares_no_config_schema_is_refused(
    mock_db_session, registered_node
):
    """`config_schema=None` used to skip validation outright, regardless of
    `node.config`'s contents - a typo'd or misplaced field silently reached
    nobody, since the handler receives `config=None` for a node like this."""
    consumer = registered_node(_action_definition("test.no_config", requires_input=False))
    node = NodeInstance(
        id=uuid4(),
        definition_id=consumer.id,
        definition_version=1,
        config={"unexpected": "value"},
        layout=_pos(),
    )
    graph = WorkflowGraph(entry_node_id=node.id, nodes=(node,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(f["field"] == f"nodes.{node.id}.config" for f in excinfo.value.details["fields"])


async def test_an_empty_config_on_a_node_with_no_config_schema_publishes(
    mock_db_session, registered_node
):
    consumer = registered_node(_action_definition("test.no_config_ok", requires_input=False))
    node = NodeInstance(
        id=uuid4(), definition_id=consumer.id, definition_version=1, config={}, layout=_pos()
    )
    graph = WorkflowGraph(entry_node_id=node.id, nodes=(node,))
    validated = await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert validated.entry_node_id == node.id


def _config_bound_consumer(registered_node) -> NodeDefinition:
    return registered_node(
        NodeDefinition(
            id="test.config_bound",
            version=1,
            name="Config bound",
            category="test",
            description="a required config field, biddable",
            kind="action",
            config_schema=_RequiredInput,
            input_schema=None,
            output_schema=_PlainOutput,
            ports=(
                Port(id="in", label="In", kind="input"),
                Port(id="out", label="Out", kind="output", schema=_PlainOutput),
            ),
            effect_kind="pure",
            retry_guarantee="idempotent",
        )
    )


async def test_a_required_config_field_left_unset_because_it_is_bound_publishes(
    mock_db_session, registered_node
):
    """`config_schema.value` is required, but the client's own binding
    supplies it - the isolated `node.config` check must not call this
    "missing" just because it never saw it there."""
    consumer = _config_bound_consumer(registered_node)
    a = _echo_node()
    b = NodeInstance(
        id=uuid4(), definition_id=consumer.id, definition_version=1, config={}, layout=_pos()
    )
    edge = _edge(a.id, "out", b.id, "in")
    binding = Binding(target_node_id=b.id, target_field="value", source=LiteralValue(value="hi"))
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=(edge,), bindings=(binding,))
    validated = await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert validated.bindings == (binding,)


async def test_a_config_field_set_both_statically_and_by_a_binding_publishes(
    mock_db_session, registered_node
):
    """A static config value is a default, not an exclusive slot - the same
    `message: "hi"` plus a table binding to `message` that `debug.echo`'s own
    tests already rely on elsewhere. A present, validly-typed static value
    means the schema check never even reaches the "missing" case the bound-
    field carve-out exists for."""
    consumer = _config_bound_consumer(registered_node)
    a = _echo_node()
    b = NodeInstance(
        id=uuid4(),
        definition_id=consumer.id,
        definition_version=1,
        config={"value": "static"},
        layout=_pos(),
    )
    edge = _edge(a.id, "out", b.id, "in")
    binding = Binding(target_node_id=b.id, target_field="value", source=LiteralValue(value="hi"))
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=(edge,), bindings=(binding,))
    validated = await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert validated.bindings == (binding,)


async def test_an_unbound_required_config_field_left_unset_is_still_refused(
    mock_db_session, registered_node
):
    """The binding-aware carve-out must not swallow the ordinary missing-
    config-field refusal for a field nothing binds either."""
    consumer = _config_bound_consumer(registered_node)
    a = _echo_node()
    b = NodeInstance(
        id=uuid4(), definition_id=consumer.id, definition_version=1, config={}, layout=_pos()
    )
    edge = _edge(a.id, "out", b.id, "in")
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=(edge,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(f["field"] == f"nodes.{b.id}.config.value" for f in excinfo.value.details["fields"])


async def test_a_table_binding_to_a_table_nobody_can_reach_is_refused(mock_db_session, monkeypatch):
    monkeypatch.setattr(virtual_table_repo, "get_table", AsyncMock(return_value=None))
    entry_id, graph = _one_node_graph()
    binding = Binding(
        target_node_id=entry_id,
        target_field="message",
        source=TableIORef(table_id=uuid4(), schema_version=1),
    )
    graph = graph.model_copy(update={"bindings": (binding,)})
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(f["field"] == "bindings.0" for f in excinfo.value.details["fields"])


async def test_a_table_binding_with_a_stale_schema_version_is_refused(mock_db_session, monkeypatch):
    table = SimpleNamespace(
        id=uuid4(), organization_id=None, owner_user_id=None, visibility="org", schema_version=2
    )
    monkeypatch.setattr(virtual_table_repo, "get_table", AsyncMock(return_value=table))
    ctx = _owner_ctx()
    table.organization_id = ctx.organization_id
    entry_id, graph = _one_node_graph()
    binding = Binding(
        target_node_id=entry_id,
        target_field="message",
        source=TableIORef(table_id=table.id, schema_version=1),
    )
    graph = graph.model_copy(update={"bindings": (binding,)})
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, ctx, graph)
    assert any("changed since" in f["message"] for f in excinfo.value.details["fields"])


async def test_a_table_binding_naming_an_archived_column_is_refused(mock_db_session, monkeypatch):
    ctx = _owner_ctx()
    table = SimpleNamespace(
        id=uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=None,
        visibility="org",
        schema_version=1,
    )
    archived_column_id = uuid4()
    version = SimpleNamespace(
        columns=[
            {
                "id": str(archived_column_id),
                "label": "Old",
                "type": "text",
                "nullable": True,
                "default": None,
                "options": [],
                "archived": True,
            }
        ]
    )
    monkeypatch.setattr(virtual_table_repo, "get_table", AsyncMock(return_value=table))
    monkeypatch.setattr(virtual_table_repo, "get_schema_version", AsyncMock(return_value=version))
    entry_id, graph = _one_node_graph()
    binding = Binding(
        target_node_id=entry_id,
        target_field="message",
        source=TableIORef(table_id=table.id, column_ids=(archived_column_id,), schema_version=1),
    )
    graph = graph.model_copy(update={"bindings": (binding,)})
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, ctx, graph)
    assert any("live column" in f["message"] for f in excinfo.value.details["fields"])


async def test_a_table_binding_to_a_live_column_publishes(mock_db_session, monkeypatch):
    ctx = _owner_ctx()
    table = SimpleNamespace(
        id=uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=None,
        visibility="org",
        schema_version=1,
    )
    live_column_id = uuid4()
    version = SimpleNamespace(
        columns=[
            {
                "id": str(live_column_id),
                "label": "Live",
                "type": "text",
                "nullable": True,
                "default": None,
                "options": [],
                "archived": False,
            }
        ]
    )
    monkeypatch.setattr(virtual_table_repo, "get_table", AsyncMock(return_value=table))
    monkeypatch.setattr(virtual_table_repo, "get_schema_version", AsyncMock(return_value=version))
    entry_id, graph = _one_node_graph()
    binding = Binding(
        target_node_id=entry_id,
        target_field="message",
        source=TableIORef(table_id=table.id, column_ids=(live_column_id,), schema_version=1),
    )
    graph = graph.model_copy(update={"bindings": (binding,)})
    validated = await validate_graph(mock_db_session, ctx, graph)
    assert validated.bindings == (binding,)


# Rule 1 - exactly one input


async def test_an_entry_node_that_is_the_target_of_an_edge_is_refused(mock_db_session):
    a, b = _echo_node(), _echo_node()
    edge = _edge(a.id, "out", b.id, "in")
    graph = WorkflowGraph(entry_node_id=b.id, nodes=(a, b), edges=(edge,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(f["field"] == "entry_node_id" for f in excinfo.value.details["fields"])


async def test_an_entry_node_not_in_the_graph_is_refused(mock_db_session):
    node = _echo_node()
    graph = WorkflowGraph(entry_node_id=uuid4(), nodes=(node,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert excinfo.value.details["fields"][0]["field"] == "entry_node_id"


# Rule 2 - reachable outputs


async def test_a_second_unreachable_source_node_is_refused(mock_db_session):
    """Rule 1 alone would pass this: only the *named* entry has in-degree 0
    is not the same as it being the *only* zero-in-degree node."""
    entry = _echo_node()
    island = _echo_node()
    graph = WorkflowGraph(entry_node_id=entry.id, nodes=(entry, island))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(f"nodes.{island.id}" == f["field"] for f in excinfo.value.details["fields"])


# Rule 3 - type compatibility


async def test_an_edge_between_incompatible_port_shapes_is_refused(
    mock_db_session, registered_node
):
    other = registered_node(
        _action_definition("test.other_shape", requires_input=False, port_schema=_RequiredInput)
    )
    a = _echo_node()
    b = NodeInstance(
        id=uuid4(), definition_id=other.id, definition_version=1, config={}, layout=_pos()
    )
    edge = _edge(a.id, "out", b.id, "in")
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=(edge,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any("incompatible" in f["message"] for f in excinfo.value.details["fields"])


async def test_a_binding_field_path_that_does_not_exist_is_refused(mock_db_session):
    a, b = _echo_node(), _echo_node()
    edge = _edge(a.id, "out", b.id, "in")
    binding = Binding(
        target_node_id=b.id,
        target_field="message",
        source=NodeOutputRef(node_id=a.id, port="out", field_path=("no_such_field",)),
    )
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=(edge,), bindings=(binding,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any("field path" in f["message"] for f in excinfo.value.details["fields"])


async def test_a_binding_naming_a_target_field_that_does_not_exist_is_refused(mock_db_session):
    """A literal binding has no `NodeOutputRef` for rule 3 to type-check, so
    only this - the field's own existence - ever catches a typo'd target."""
    a, b = _echo_node(), _echo_node()
    edge = _edge(a.id, "out", b.id, "in")
    binding = Binding(
        target_node_id=b.id, target_field="no_such_field", source=LiteralValue(value="hi")
    )
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=(edge,), bindings=(binding,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(f["field"] == "bindings.0" for f in excinfo.value.details["fields"])


async def test_a_binding_to_a_node_with_an_unresolvable_definition_is_left_to_that_refusal(
    mock_db_session,
):
    """The unresolvable node is already refused by rule 0; the field-existence
    check has nothing to compare against and stays quiet rather than piling
    on a second, less useful error about the same node."""
    a = _echo_node()
    b = _echo_node().model_copy(update={"definition_version": 99})
    edge = _edge(a.id, "out", b.id, "in")
    binding = Binding(target_node_id=b.id, target_field="message", source=LiteralValue(value="hi"))
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=(edge,), bindings=(binding,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    fields = excinfo.value.details["fields"]
    assert any(f"nodes.{b.id}" == f["field"] for f in fields)
    assert not any(f["field"] == "bindings.0" for f in fields)


# Rule 4 - branch-local data availability


async def test_a_binding_to_a_node_not_on_every_path_is_refused(mock_db_session, registered_node):
    """`c` binds to `b`'s output, but `b` runs only when the If takes `true` and `c` only
    when it takes `false` - so `b` has not necessarily run when `c` does."""
    source = registered_node(_action_definition("test.branch_source", requires_input=False))
    consumer = registered_node(_action_definition("test.branch_consumer"))
    entry, branch = _echo_node(), _if_node("I")
    b = NodeInstance(
        id=uuid4(), definition_id=source.id, definition_version=1, config={}, layout=_pos()
    )
    c = NodeInstance(
        id=uuid4(), definition_id=consumer.id, definition_version=1, config={}, layout=_pos()
    )
    edges = (
        _edge(entry.id, "out", branch.id, "in"),
        _edge(branch.id, "true", b.id, "in"),
        _edge(branch.id, "false", c.id, "in"),
    )
    binding = Binding(
        target_node_id=c.id,
        target_field="value",
        source=NodeOutputRef(node_id=b.id, port="out", field_path=("value",)),
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, branch, b, c),
        edges=edges,
        bindings=(_decides_on(branch.id), binding),
    )
    fields = await _fields(graph, mock_db_session)
    assert _has(fields, "bindings.1", "has not necessarily run")
    assert not _has(fields, "bindings.1", "does not exist")


async def test_a_binding_to_the_nodes_own_output_is_refused(mock_db_session, registered_node):
    """A node dominates itself, so the membership check alone would call this
    available - it never is, since the node has not run yet at the point it
    would need its own output."""
    self_ref = registered_node(_action_definition("test.self_ref"))
    c = NodeInstance(
        id=uuid4(), definition_id=self_ref.id, definition_version=1, config={}, layout=_pos()
    )
    binding = Binding(
        target_node_id=c.id,
        target_field="value",
        source=NodeOutputRef(node_id=c.id, port="out", field_path=("value",)),
    )
    graph = WorkflowGraph(entry_node_id=c.id, nodes=(c,), bindings=(binding,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(
        f["field"] == "bindings.0" and "own output" in f["message"]
        for f in excinfo.value.details["fields"]
    )


async def test_a_binding_to_a_node_on_every_path_publishes(mock_db_session, registered_node):
    consumer = registered_node(_action_definition("test.linear_consumer"))
    a = _echo_node()
    b = NodeInstance(
        id=uuid4(), definition_id=consumer.id, definition_version=1, config={}, layout=_pos()
    )
    edge = _edge(a.id, "out", b.id, "in")
    binding = Binding(
        target_node_id=b.id,
        target_field="value",
        source=NodeOutputRef(node_id=a.id, port="out", field_path=("echoed",)),
    )
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=(edge,), bindings=(binding,))
    validated = await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert validated.bindings == (binding,)


# Rule 5 - exclusive merge


def _leg() -> NodeInstance:
    """A branch step with an untyped `in`, so a `logic.if` port may lead into it."""
    return NodeInstance(
        id=uuid4(),
        definition_id="data.map",
        definition_version=1,
        config={"mappings": [{"target_field": "a", "source_path": "'x'"}]},
        layout=_pos(),
    )


async def test_a_merges_branches_not_from_one_if_are_refused(mock_db_session, registered_node):
    a, b = _echo_node(), _echo_node()
    c = NodeInstance(
        id=uuid4(), definition_id="logic.merge", definition_version=1, config={}, layout=_pos()
    )
    # Two independent predecessors, no shared `logic.if` ancestor at all: `b` is not
    # reachable, which is what is refused (a Wait for hint would not mend that).
    edges = (_edge(a.id, "out", c.id, "in"), _edge(b.id, "out", c.id, "in"))
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b, c), edges=edges)
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(f"nodes.{b.id}" == f["field"] for f in excinfo.value.details["fields"])


async def test_a_merge_from_one_logic_if_publishes(mock_db_session, registered_node):
    entry = _echo_node()
    branch_node = NodeInstance(
        id=uuid4(),
        definition_id="logic.if",
        definition_version=1,
        config={"condition": "value"},
        layout=_pos(),
    )
    then_leg = _leg()
    else_leg = _leg()
    merge_node = NodeInstance(
        id=uuid4(), definition_id="logic.merge", definition_version=1, config={}, layout=_pos()
    )
    edges = (
        _edge(entry.id, "out", branch_node.id, "in"),
        _edge(branch_node.id, "true", then_leg.id, "in"),
        _edge(branch_node.id, "false", else_leg.id, "in"),
        _edge(then_leg.id, "out", merge_node.id, "in"),
        _edge(else_leg.id, "out", merge_node.id, "in"),
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, branch_node, then_leg, else_leg, merge_node),
        edges=edges,
        bindings=(_decides_on(branch_node.id),),
    )
    validated = await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert validated.entry_node_id == entry.id


async def test_a_merges_branches_from_the_same_if_port_are_refused(
    mock_db_session, registered_node
):
    """Rule 8 lets a control node fan one port out to more than one target,
    so both legs here share `logic.if`'s `true` port - they run together or
    not at all, never exclusively, even though they share a dominator."""
    entry = _echo_node()
    branch_node = NodeInstance(
        id=uuid4(),
        definition_id="logic.if",
        definition_version=1,
        config={"condition": "value"},
        layout=_pos(),
    )
    then_leg = _leg()
    other_leg = _leg()
    merge_node = NodeInstance(
        id=uuid4(), definition_id="logic.merge", definition_version=1, config={}, layout=_pos()
    )
    edges = (
        _edge(entry.id, "out", branch_node.id, "in"),
        _edge(branch_node.id, "true", then_leg.id, "in"),
        _edge(branch_node.id, "true", other_leg.id, "in"),
        _edge(then_leg.id, "out", merge_node.id, "in"),
        _edge(other_leg.id, "out", merge_node.id, "in"),
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, branch_node, then_leg, other_leg, merge_node),
        edges=edges,
    )
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(
        f["field"] == f"nodes.{merge_node.id}"
        and "Several branches reach this merge together" in f["message"]
        for f in excinfo.value.details["fields"]
    )


def _decides_on(node_id: UUID) -> Binding:
    """What an If or a Switch looks at: a literal, since the test is about the wiring."""
    return Binding(target_node_id=node_id, target_field="value", source=LiteralValue(value=True))


def _switch_into_merge(*ports: str, legs: tuple[str, ...] = ()) -> tuple[WorkflowGraph, UUID]:
    """A `logic.switch` wired straight into a `logic.merge` by `ports`, and through a leg by `legs`."""
    entry = _echo_node()
    switch = NodeInstance(
        id=uuid4(),
        definition_id="logic.switch",
        definition_version=1,
        config={
            "rules": [
                {"name": "a", "condition": "value"},
                {"name": "b", "condition": "value"},
            ]
        },
        layout=_pos(),
    )
    merge_node = NodeInstance(
        id=uuid4(), definition_id="logic.merge", definition_version=1, config={}, layout=_pos()
    )
    leg_nodes = [_leg() for _ in legs]
    edges = [
        _edge(entry.id, "out", switch.id, "in"),
        *(_edge(switch.id, port, merge_node.id, "in") for port in ports),
        *(_edge(switch.id, port, leg.id, "in") for port, leg in zip(legs, leg_nodes, strict=True)),
        *(_edge(leg.id, "out", merge_node.id, "in") for leg in leg_nodes),
    ]
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, switch, *leg_nodes, merge_node),
        edges=tuple(edges),
        bindings=(_decides_on(switch.id),),
    )
    return graph, merge_node.id


async def test_a_merge_may_take_two_ports_of_one_branching_step_straight(mock_db_session):
    graph, _merge = _switch_into_merge("a", "otherwise")

    validated = await validate_graph(mock_db_session, _owner_ctx(), graph)

    assert len(validated.edges) == 3


async def test_a_merge_may_join_an_error_routing_steps_out_and_error_ports(mock_db_session):
    entry = _echo_node()
    routed = _echo_node()
    routed = routed.model_copy(update={"policy": NodePolicy(on_error="route")})
    merge_node = NodeInstance(
        id=uuid4(), definition_id="logic.merge", definition_version=1, config={}, layout=_pos()
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, routed, merge_node),
        edges=(
            _edge(entry.id, "out", routed.id, "in"),
            _edge(routed.id, "out", merge_node.id, "in"),
            _edge(routed.id, "error", merge_node.id, "in"),
        ),
    )

    # The error port's shape may be refused on its own terms; the merge itself is not.
    try:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    except GraphValidationError as refused:
        assert refused.details is not None
        assert not any(f["field"] == f"nodes.{merge_node.id}" for f in refused.details["fields"])


async def test_a_merge_may_take_a_port_straight_and_another_through_a_leg(mock_db_session):
    graph, _merge = _switch_into_merge("a", legs=("b",))

    await validate_graph(mock_db_session, _owner_ctx(), graph)


async def test_a_merge_taking_the_same_port_straight_twice_is_refused(mock_db_session):
    graph, merge = _switch_into_merge("a", "a")

    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)

    assert any(
        f["field"] == f"nodes.{merge}" and "same branch" in f["message"]
        for f in excinfo.value.details["fields"]
    )


async def test_a_merge_taking_a_port_straight_and_through_a_leg_of_it_is_refused(mock_db_session):
    graph, merge = _switch_into_merge("a", legs=("a",))

    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)

    assert any(
        f["field"] == f"nodes.{merge}"
        and "Several branches reach this merge together" in f["message"]
        for f in excinfo.value.details["fields"]
    )


async def test_a_merge_taking_two_ports_of_a_step_that_branches_not_exclusively_is_refused(
    mock_db_session, registered_node
):
    both = registered_node(
        NodeDefinition(
            id="test.two_ports",
            version=1,
            name="Two ports",
            category="data",
            description="test",
            kind="action",
            config_schema=None,
            input_schema=None,
            output_schema=None,
            ports=(
                Port(id="in", label="In", kind="input"),
                Port(id="left", label="Left", kind="output"),
                Port(id="right", label="Right", kind="output"),
            ),
            effect_kind="pure",
            retry_guarantee="idempotent",
        )
    )
    step = NodeInstance(
        id=uuid4(), definition_id=both.id, definition_version=1, config={}, layout=_pos()
    )
    merge_node = NodeInstance(
        id=uuid4(), definition_id="logic.merge", definition_version=1, config={}, layout=_pos()
    )
    graph = WorkflowGraph(
        entry_node_id=step.id,
        nodes=(step, merge_node),
        edges=(
            _edge(step.id, "left", merge_node.id, "in"),
            _edge(step.id, "right", merge_node.id, "in"),
        ),
    )

    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)

    assert any(
        f["field"] == f"nodes.{merge_node.id}"
        and "Several branches reach this merge together" in f["message"]
        for f in excinfo.value.details["fields"]
    )


async def test_a_merge_fed_through_two_ports_of_a_step_that_is_not_exclusive_is_refused(
    mock_db_session, registered_node
):
    """`C.a -> M`, `C.b -> X`, `X.p -> M`, `X.q -> M`: C is exclusive, X is not."""
    fan = registered_node(
        NodeDefinition(
            id="test.nested_fan",
            version=1,
            name="Fan",
            category="data",
            description="test",
            kind="control",
            config_schema=None,
            input_schema=None,
            output_schema=None,
            ports=(
                Port(id="in", label="In", kind="input"),
                Port(id="p", label="P", kind="output"),
                Port(id="q", label="Q", kind="output"),
            ),
            effect_kind="pure",
            retry_guarantee="idempotent",
        )
    )
    entry = _echo_node()
    switch = NodeInstance(
        id=uuid4(),
        definition_id="logic.switch",
        definition_version=1,
        config={
            "rules": [{"name": "a", "condition": "value"}, {"name": "b", "condition": "value"}]
        },
        layout=_pos(),
    )
    fanout = NodeInstance(
        id=uuid4(), definition_id=fan.id, definition_version=1, config={}, layout=_pos()
    )
    merge_node = NodeInstance(
        id=uuid4(), definition_id="logic.merge", definition_version=1, config={}, layout=_pos()
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, switch, fanout, merge_node),
        edges=(
            _edge(entry.id, "out", switch.id, "in"),
            _edge(switch.id, "a", merge_node.id, "in"),
            _edge(switch.id, "b", fanout.id, "in"),
            _edge(fanout.id, "p", merge_node.id, "in"),
            _edge(fanout.id, "q", merge_node.id, "in"),
        ),
    )

    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)

    assert any(
        f["field"] == f"nodes.{merge_node.id}"
        and "Several branches reach this merge together" in f["message"]
        for f in excinfo.value.details["fields"]
    )


async def test_publish_refuses_a_stored_config_naming_an_output_like_a_static_port(
    mock_db_session,
):
    entry = _echo_node()
    switch = NodeInstance(
        id=uuid4(),
        definition_id="logic.switch",
        definition_version=1,
        config={"rules": [{"name": "otherwise", "condition": "value"}]},
        layout=_pos(),
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, switch),
        edges=(_edge(entry.id, "out", switch.id, "in"),),
    )

    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)

    assert {
        "field": f"nodes.{switch.id}.config.rules.0.name",
        "message": "Value error, `otherwise` is already a port on this step - rename it",
    } in excinfo.value.details["fields"]


async def test_publish_refuses_an_error_named_output_on_a_step_that_routes_its_errors(
    mock_db_session,
):
    entry = _echo_node()
    switch = NodeInstance(
        id=uuid4(),
        definition_id="logic.switch",
        definition_version=1,
        config={"rules": [{"name": "error", "condition": "value"}]},
        layout=_pos(),
        policy=NodePolicy(on_error="route"),
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, switch),
        edges=(_edge(entry.id, "out", switch.id, "in"),),
    )

    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)

    assert {
        "field": f"nodes.{switch.id}.config.rules.0.name",
        "message": "`error` is already a port on this step - rename it",
    } in excinfo.value.details["fields"]


async def test_a_merge_with_two_edges_from_the_same_branch_is_refused(
    mock_db_session, registered_node
):
    a = _echo_node()
    c = NodeInstance(
        id=uuid4(), definition_id="logic.merge", definition_version=1, config={}, layout=_pos()
    )
    edges = (_edge(a.id, "out", c.id, "in"), _edge(a.id, "out", c.id, "in"))
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, c), edges=edges)
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(
        f["field"] == f"nodes.{c.id}" and "same branch" in f["message"]
        for f in excinfo.value.details["fields"]
    )


async def test_a_merge_branch_reconverged_from_both_if_arms_is_refused(
    mock_db_session, registered_node
):
    """`a` is downstream of *both* `true` (via `t`) and `false` (via `e`)
    - it runs on either outcome, so it is not exclusive with `b`, which only
    runs on `true`. Neither of `logic.if`'s own children dominates `a` alone
    (`t` and `e` each dominate only their own leg), so `a`'s dominator set
    stops at `logic.if` itself and no single feeding port can be named for
    it - the gap a bare "do the sets overlap" check missed entirely."""
    entry = _echo_node()
    branch_node = NodeInstance(
        id=uuid4(),
        definition_id="logic.if",
        definition_version=1,
        config={"condition": "value"},
        layout=_pos(),
    )
    t, e, a, b = _leg(), _leg(), _leg(), _leg()
    merge_node = NodeInstance(
        id=uuid4(), definition_id="logic.merge", definition_version=1, config={}, layout=_pos()
    )
    edges = (
        _edge(entry.id, "out", branch_node.id, "in"),
        _edge(branch_node.id, "true", t.id, "in"),
        _edge(branch_node.id, "true", b.id, "in"),
        _edge(branch_node.id, "false", e.id, "in"),
        _edge(t.id, "out", a.id, "in"),
        _edge(e.id, "out", a.id, "in"),
        _edge(a.id, "out", merge_node.id, "in"),
        _edge(b.id, "out", merge_node.id, "in"),
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id, nodes=(entry, branch_node, t, e, a, b, merge_node), edges=edges
    )
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(
        f["field"] == f"nodes.{merge_node.id}"
        and "Several branches reach this merge together" in f["message"]
        for f in excinfo.value.details["fields"]
    )


# Rule 6 - nested scope boundaries


def _loop_definition() -> NodeDefinition:
    return NodeDefinition(
        id="control.synthetic_loop",
        version=1,
        name="For each",
        category="control",
        description="iterates a body",
        kind="control",
        config_schema=None,
        input_schema=None,
        output_schema=None,
        ports=(
            Port(id="in", label="In", kind="input"),
            Port(id="body", label="Body", kind="output"),
            Port(id="done", label="Done", kind="output"),
        ),
        effect_kind="pure",
        retry_guarantee="idempotent",
    )


async def test_an_edge_reaching_into_a_scope_body_from_outside_it_is_refused(
    mock_db_session, registered_node
):
    """The only sanctioned way into a body is the loop's own entry edge.

    An edge from some other top-level node directly into a body member -
    skipping `loop_node`'s `body` port entirely - is a crossing rule 6
    refuses, even though the target node is legitimately part of the body
    when reached the sanctioned way.
    """
    loop_def = registered_node(_loop_definition())
    entry = _echo_node()
    loop_node = NodeInstance(
        id=uuid4(), definition_id=loop_def.id, definition_version=1, config={}, layout=_pos()
    )
    body_node = _echo_node()
    intruder = _echo_node()
    edges = (
        _edge(entry.id, "out", loop_node.id, "in"),
        _edge(loop_node.id, "body", body_node.id, "in"),
        _edge(loop_node.id, "done", intruder.id, "in"),
        # Forbidden: reaches a body member directly, not through `body`.
        _edge(intruder.id, "out", body_node.id, "in"),
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id, nodes=(entry, loop_node, body_node, intruder), edges=edges
    )
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any("crosses a scope boundary" in f["message"] for f in excinfo.value.details["fields"])


async def test_the_two_declared_boundary_edges_are_sanctioned(mock_db_session, registered_node):
    loop_def = registered_node(_loop_definition())
    entry = _echo_node()
    loop_node = NodeInstance(
        id=uuid4(), definition_id=loop_def.id, definition_version=1, config={}, layout=_pos()
    )
    body_node = _echo_node()
    after = _echo_node()
    edges = (
        _edge(entry.id, "out", loop_node.id, "in"),
        _edge(loop_node.id, "body", body_node.id, "in"),
        _edge(loop_node.id, "done", after.id, "in"),
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id, nodes=(entry, loop_node, body_node, after), edges=edges
    )
    validated = await validate_graph(mock_db_session, _owner_ctx(), graph)
    scope = next(s for s in validated.scopes if s.scope_node_id == loop_node.id)
    assert scope.body_node_ids == frozenset({body_node.id})


def _yield_definition() -> NodeDefinition:
    """`loop.yield`, per #1790: `kind="control"` but not `control.*`-namespaced,
    so `_owns_a_scope` never treats it as a scope owner - it is the body's
    own exit point instead, per the settled `ScopeBoundary.exit_node_id`
    reading `1786-node-contracts.md` and `1790-error-foreach.md` agree on.
    """
    return NodeDefinition(
        id="loop.synthetic_yield",
        version=1,
        name="Yield",
        category="control",
        description="the body's exit point",
        kind="control",
        config_schema=None,
        input_schema=None,
        output_schema=None,
        ports=(
            Port(id="in", label="In", kind="input"),
            Port(id="out", label="Out", kind="output"),
        ),
        effect_kind="pure",
        retry_guarantee="idempotent",
    )


async def test_a_scope_exit_owned_by_a_body_interior_node_publishes(
    mock_db_session, registered_node, monkeypatch
):
    """A scope whose exit is a body-interior node's own outgoing edge.

    `control.foreach` exits through its own `done` port, so `derive_scopes`
    never produces this shape; `ScopeBoundary` still allows it, and this
    hand-built boundary confirms every rule that reads `exit_port` honors
    `exit_node_id` naming a body-interior node, not only `scope_node_id`.
    """
    loop_def = registered_node(_loop_definition())
    yield_def = registered_node(_yield_definition())
    entry = _echo_node()
    loop_node = NodeInstance(
        id=uuid4(), definition_id=loop_def.id, definition_version=1, config={}, layout=_pos()
    )
    body_node = _echo_node()
    yield_node = NodeInstance(
        id=uuid4(), definition_id=yield_def.id, definition_version=1, config={}, layout=_pos()
    )
    after = _echo_node()
    edges = (
        _edge(entry.id, "out", loop_node.id, "in"),
        _edge(loop_node.id, "body", body_node.id, "in"),
        _edge(body_node.id, "out", yield_node.id, "in"),
        # The real exit edge: sourced at `yield_node`, not `loop_node`.
        _edge(yield_node.id, "out", after.id, "in"),
    )
    scope = ScopeBoundary(
        scope_node_id=loop_node.id,
        body_node_ids=frozenset({body_node.id, yield_node.id}),
        entry_port="body",
        exit_node_id=yield_node.id,
        exit_port="out",
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, loop_node, body_node, yield_node, after),
        edges=edges,
        scopes=(scope,),
    )
    monkeypatch.setattr("app.workflows.graph.validate.derive_scopes", lambda g: g)
    validated = await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert validated.entry_node_id == entry.id
    assert validated.scopes[0].exit_node_id == yield_node.id


async def test_a_body_member_other_than_the_designated_exit_node_still_cannot_leave_the_scope(
    mock_db_session, registered_node, monkeypatch
):
    """Designating `yield_node` as the exit does not also sanction some other
    body member leaving directly - only the edge sourced at `exit_node_id`
    with `source_port == exit_port` is the scope's declared exit."""
    loop_def = registered_node(_loop_definition())
    yield_def = registered_node(_yield_definition())
    entry = _echo_node()
    loop_node = NodeInstance(
        id=uuid4(), definition_id=loop_def.id, definition_version=1, config={}, layout=_pos()
    )
    body_node = _echo_node()
    yield_node = NodeInstance(
        id=uuid4(), definition_id=yield_def.id, definition_version=1, config={}, layout=_pos()
    )
    after = _echo_node()
    edges = (
        _edge(entry.id, "out", loop_node.id, "in"),
        _edge(loop_node.id, "body", body_node.id, "in"),
        # Forbidden: `body_node` is a body member but not `exit_node_id`.
        _edge(body_node.id, "out", after.id, "in"),
    )
    scope = ScopeBoundary(
        scope_node_id=loop_node.id,
        body_node_ids=frozenset({body_node.id, yield_node.id}),
        entry_port="body",
        exit_node_id=yield_node.id,
        exit_port="out",
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, loop_node, body_node, yield_node, after),
        edges=edges,
        scopes=(scope,),
    )
    monkeypatch.setattr("app.workflows.graph.validate.derive_scopes", lambda g: g)
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any("crosses a scope boundary" in f["message"] for f in excinfo.value.details["fields"])


def test_derive_scopes_does_not_absorb_what_is_downstream_of_the_loop(registered_node):
    """The regression the design doc's round 2 fix caught: a plain forward
    walk from `entry_port` also reaches whatever is downstream of `done`,
    since in a linear diagram the only path there is *through* the loop."""
    loop_def = registered_node(_loop_definition())
    entry = _echo_node()
    loop_node = NodeInstance(
        id=uuid4(), definition_id=loop_def.id, definition_version=1, config={}, layout=_pos()
    )
    body_node = _echo_node()
    after_the_loop = _echo_node()
    edges = (
        _edge(entry.id, "out", loop_node.id, "in"),
        _edge(loop_node.id, "body", body_node.id, "in"),
        _edge(loop_node.id, "done", after_the_loop.id, "in"),
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id, nodes=(entry, loop_node, body_node, after_the_loop), edges=edges
    )
    derived = derive_scopes(graph)
    scope = next(s for s in derived.scopes if s.scope_node_id == loop_node.id)
    assert after_the_loop.id not in scope.body_node_ids
    assert scope.body_node_ids == frozenset({body_node.id})


# Rule 7 - no cycles


async def test_a_two_node_cycle_is_refused(mock_db_session):
    a, b = _echo_node(), _echo_node()
    edges = (_edge(a.id, "out", b.id, "in"), _edge(b.id, "out", a.id, "in"))
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=edges)
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any("cycle" in f["message"] for f in excinfo.value.details["fields"])


# Rule 8 - no parallel fan-out (v1)


async def test_a_non_control_node_sending_through_two_ports_is_refused(
    mock_db_session, registered_node
):
    two_ported = registered_node(
        NodeDefinition(
            id="test.two_output_ports",
            version=1,
            name="Two ports",
            category="test",
            description="a non-control node with two declared output ports",
            kind="action",
            config_schema=None,
            input_schema=None,
            output_schema=None,
            ports=(
                Port(id="in", label="In", kind="input"),
                Port(id="out_a", label="Out A", kind="output"),
                Port(id="out_b", label="Out B", kind="output"),
            ),
            effect_kind="pure",
            retry_guarantee="idempotent",
        )
    )
    entry = _echo_node()
    a = NodeInstance(
        id=uuid4(), definition_id=two_ported.id, definition_version=1, config={}, layout=_pos()
    )
    b, c = _echo_node(), _echo_node()
    edges = (
        _edge(entry.id, "out", a.id, "in"),
        _edge(a.id, "out_a", b.id, "in"),
        _edge(a.id, "out_b", c.id, "in"),
    )
    graph = WorkflowGraph(entry_node_id=entry.id, nodes=(entry, a, b, c), edges=edges)
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(
        f["field"] == f"nodes.{a.id}" and "one port" in f["message"]
        for f in excinfo.value.details["fields"]
    )


async def test_a_control_node_fanning_out_two_branches_is_allowed(mock_db_session, registered_node):
    branch_if = registered_node(
        NodeDefinition(
            id="test.logic_if",
            version=1,
            name="If",
            category="logic",
            description="branches",
            kind="control",
            config_schema=None,
            input_schema=None,
            output_schema=None,
            ports=(
                Port(id="in", label="In", kind="input"),
                Port(id="then", label="Then", kind="output"),
                Port(id="otherwise", label="Otherwise", kind="output"),
            ),
            effect_kind="pure",
            retry_guarantee="idempotent",
        )
    )
    entry = _echo_node()
    branch_node = NodeInstance(
        id=uuid4(), definition_id=branch_if.id, definition_version=1, config={}, layout=_pos()
    )
    then_leg, else_leg = _echo_node(), _echo_node()
    edges = (
        _edge(entry.id, "out", branch_node.id, "in"),
        _edge(branch_node.id, "then", then_leg.id, "in"),
        _edge(branch_node.id, "otherwise", else_leg.id, "in"),
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id, nodes=(entry, branch_node, then_leg, else_leg), edges=edges
    )
    validated = await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert validated.entry_node_id == entry.id


# Rule 9 - every required input bound exactly once


async def test_an_unbound_required_input_is_refused(mock_db_session, registered_node):
    consumer = registered_node(_action_definition("test.needs_value"))
    a = _echo_node()
    b = NodeInstance(
        id=uuid4(), definition_id=consumer.id, definition_version=1, config={}, layout=_pos()
    )
    edge = _edge(a.id, "out", b.id, "in")
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=(edge,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any("not bound" in f["message"] for f in excinfo.value.details["fields"])


async def test_a_required_input_bound_twice_is_refused(mock_db_session, registered_node):
    consumer = registered_node(_action_definition("test.needs_value_twice"))
    a = _echo_node()
    b = NodeInstance(
        id=uuid4(), definition_id=consumer.id, definition_version=1, config={}, layout=_pos()
    )
    edge = _edge(a.id, "out", b.id, "in")
    bindings = (
        Binding(target_node_id=b.id, target_field="value", source=LiteralValue(value="one")),
        Binding(target_node_id=b.id, target_field="value", source=LiteralValue(value="two")),
    )
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=(edge,), bindings=bindings)
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any("more than once" in f["message"] for f in excinfo.value.details["fields"])


async def test_a_required_input_bound_exactly_once_publishes(mock_db_session, registered_node):
    consumer = registered_node(_action_definition("test.needs_value_once"))
    a = _echo_node()
    b = NodeInstance(
        id=uuid4(), definition_id=consumer.id, definition_version=1, config={}, layout=_pos()
    )
    edge = _edge(a.id, "out", b.id, "in")
    binding = Binding(target_node_id=b.id, target_field="value", source=LiteralValue(value="one"))
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=(edge,), bindings=(binding,))
    validated = await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert validated.bindings == (binding,)


_DECISION_MESSAGE = "This step decides on `value` - bind what it should look at"


def _decision_graph(
    definition_id: str, config: dict, *bindings: Binding
) -> tuple[NodeInstance, WorkflowGraph]:
    entry = _echo_node()
    step = NodeInstance(
        id=uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config,
        layout=_pos(),
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, step),
        edges=(_edge(entry.id, "out", step.id, "in"),),
        bindings=bindings,
    )
    return step, graph


_DECISIONS = [
    ("logic.if", {"condition": "value"}),
    ("logic.switch", {"rules": [{"name": "big", "condition": "value"}]}),
]


@pytest.mark.parametrize(("definition_id", "config"), _DECISIONS, ids=["if", "switch"])
async def test_a_step_that_decides_on_nothing_bound_is_refused(
    mock_db_session, definition_id, config
):
    step, graph = _decision_graph(definition_id, config)
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert excinfo.value.details is not None
    assert {"field": f"nodes.{step.id}.value", "message": _DECISION_MESSAGE} in (
        excinfo.value.details["fields"]
    )


@pytest.mark.parametrize(("definition_id", "config"), _DECISIONS, ids=["if", "switch"])
@pytest.mark.parametrize("target", ["value", "value/x"], ids=["whole", "by-key"])
async def test_a_decision_with_a_value_bound_is_not_refused_for_it(
    mock_db_session, definition_id, config, target
):
    step, graph = _decision_graph(definition_id, config)
    binding = Binding(target_node_id=step.id, target_field=target, source=LiteralValue(value=True))
    graph = graph.model_copy(update={"bindings": (binding,)})
    try:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    except GraphValidationError as exc:
        assert exc.details is not None
        assert all(f["field"] != f"nodes.{step.id}.value" for f in exc.details["fields"])


async def test_an_optional_input_bound_twice_is_refused(mock_db_session, registered_node):
    """`field.is_required()` is false for `value` here, so only a check that
    covers every bound field - not only a required one - catches two
    competing sources for it."""
    consumer = registered_node(
        NodeDefinition(
            id="test.optional_twice",
            version=1,
            name="Optional twice",
            category="test",
            description="an optional field with two sources",
            kind="action",
            config_schema=None,
            input_schema=_OptionalInput,
            output_schema=_PlainOutput,
            ports=(
                Port(id="in", label="In", kind="input"),
                Port(id="out", label="Out", kind="output", schema=_PlainOutput),
            ),
            effect_kind="pure",
            retry_guarantee="idempotent",
        )
    )
    a = _echo_node()
    b = NodeInstance(
        id=uuid4(), definition_id=consumer.id, definition_version=1, config={}, layout=_pos()
    )
    edge = _edge(a.id, "out", b.id, "in")
    bindings = (
        Binding(target_node_id=b.id, target_field="value", source=LiteralValue(value="one")),
        Binding(target_node_id=b.id, target_field="value", source=LiteralValue(value="two")),
    )
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=(edge,), bindings=bindings)
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any("more than once" in f["message"] for f in excinfo.value.details["fields"])


async def test_a_literal_value_of_the_wrong_type_is_refused(mock_db_session, registered_node):
    """The type check on a `NodeOutputRef` binding never reaches a literal -
    a concrete value, not a schema - so an int bound to a `str` field passed
    unnoticed until execution constructed the handler's input."""
    consumer = registered_node(_action_definition("test.needs_str_value"))
    a = _echo_node()
    b = NodeInstance(
        id=uuid4(), definition_id=consumer.id, definition_version=1, config={}, layout=_pos()
    )
    edge = _edge(a.id, "out", b.id, "in")
    binding = Binding(target_node_id=b.id, target_field="value", source=LiteralValue(value=123))
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=(edge,), bindings=(binding,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(f["field"] == "bindings.0" for f in excinfo.value.details["fields"])


async def test_a_literal_value_of_the_right_type_publishes(mock_db_session, registered_node):
    consumer = registered_node(_action_definition("test.needs_str_value_ok"))
    a = _echo_node()
    b = NodeInstance(
        id=uuid4(), definition_id=consumer.id, definition_version=1, config={}, layout=_pos()
    )
    edge = _edge(a.id, "out", b.id, "in")
    binding = Binding(target_node_id=b.id, target_field="value", source=LiteralValue(value="hi"))
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=(edge,), bindings=(binding,))
    validated = await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert validated.bindings == (binding,)


# Multiple problems collected together


async def test_every_violated_rule_is_reported_in_one_refusal(mock_db_session):
    """`validate_graph` collects every problem before refusing, not the first."""
    node = _echo_node().model_copy(update={"definition_version": 99})
    graph = WorkflowGraph(entry_node_id=uuid4(), nodes=(node,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    fields = {f["field"] for f in excinfo.value.details["fields"]}
    assert "entry_node_id" in fields
    assert any(field.startswith("nodes.") for field in fields)


def test_a_file_ref_and_a_literal_binding_need_no_table_lookup():
    """A quick sanity check that binding sources other than `TableIORef` do
    not need a database at all - exercised as part of the happy-path tests
    above, and pinned here so a future change to `_table_binding_problems`
    cannot start dispatching on the wrong source kind without a test noticing."""
    file_binding = Binding(
        target_node_id=uuid4(),
        target_field="f",
        source=FileRef(file_id=uuid4(), content_type="text/plain", byte_size=0),
    )
    literal_binding = Binding(
        target_node_id=uuid4(), target_field="f", source=LiteralValue(value=1)
    )
    assert isinstance(file_binding.source, FileRef)
    assert isinstance(literal_binding.source, LiteralValue)


# An open object bound one key at a time


class _OpenInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    arguments: dict[str, Any]
    extra: dict[str, Any] | None = None
    counts: dict[str, int] | None = None
    tags: list[str] | None = None


def _open_consumer(registered_node, node_id: str) -> NodeInstance:
    registered_node(
        NodeDefinition(
            id=node_id,
            version=1,
            name=node_id,
            category="test",
            description="takes an open object",
            kind="action",
            config_schema=None,
            input_schema=_OpenInput,
            output_schema=_PlainOutput,
            ports=(
                Port(id="in", label="In", kind="input"),
                Port(id="out", label="Out", kind="output", schema=_PlainOutput),
            ),
            effect_kind="pure",
            retry_guarantee="idempotent",
        )
    )
    return NodeInstance(
        id=uuid4(), definition_id=node_id, definition_version=1, config={}, layout=_pos()
    )


def _open_graph(consumer: NodeInstance, *fields: str) -> WorkflowGraph:
    a = _echo_node()
    return WorkflowGraph(
        entry_node_id=a.id,
        nodes=(a, consumer),
        edges=(_edge(a.id, "out", consumer.id, "in"),),
        bindings=tuple(
            Binding(target_node_id=consumer.id, target_field=field, source=LiteralValue(value="x"))
            for field in fields
        ),
    )


async def test_an_open_object_bound_key_by_key_counts_as_bound(mock_db_session, registered_node):
    consumer = _open_consumer(registered_node, "test.open_keys")
    graph = _open_graph(consumer, "arguments/email", "arguments/a~1b", "extra/note")

    validated = await validate_graph(mock_db_session, _owner_ctx(), graph)

    assert len(validated.bindings) == 3


async def test_an_open_object_bound_whole_and_by_key_is_refused(mock_db_session, registered_node):
    consumer = _open_consumer(registered_node, "test.open_both")
    graph = _open_graph(consumer, "arguments", "arguments/email")

    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)

    assert any("whole and by key" in f["message"] for f in excinfo.value.details["fields"])


@pytest.mark.parametrize(
    "field", ["counts/a", "tags/0", "arguments/a/b", "arguments/", "missing/a"]
)
async def test_only_one_key_of_an_open_object_can_be_bound(mock_db_session, registered_node, field):
    consumer = _open_consumer(registered_node, "test.open_refused")
    graph = _open_graph(consumer, "arguments/email", field)

    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)

    assert any("does not exist" in f["message"] for f in excinfo.value.details["fields"])


# Parallel branches


def _named(
    label: str, definition_id: str, config: dict | None = None, **extra: Any
) -> NodeInstance:
    return NodeInstance(
        id=uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=_pos(),
        label=label,
        **extra,
    )


def _split_node(label: str, *branches: str) -> NodeInstance:
    return _named(label, "logic.split", {"branches": [{"name": b} for b in branches]})


def _if_node(label: str) -> NodeInstance:
    return _named(label, "logic.if", {"condition": "value"})


def _step(label: str, **extra: Any) -> NodeInstance:
    return _named(
        label, "data.map", {"mappings": [{"target_field": "a", "source_path": "'x'"}]}, **extra
    )


def _graph(*nodes: NodeInstance, edges: list[tuple[NodeInstance, str, NodeInstance]], bindings=()):
    return WorkflowGraph(
        entry_node_id=nodes[0].id,
        nodes=nodes,
        edges=tuple(_edge(s.id, p, t.id, "in") for s, p, t in edges),
        bindings=tuple(bindings),
    )


async def _fields(graph: WorkflowGraph, db) -> list[dict]:
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(db, _owner_ctx(), graph)
    return excinfo.value.details["fields"]


def _has(fields: list[dict], field: str, text: str) -> bool:
    return any(f["field"] == field and text in f["message"] for f in fields)


def _two_ins(registered_node) -> NodeDefinition:
    class _Two(BaseModel):
        model_config = ConfigDict(frozen=True, extra="forbid")

        a: str
        b: str

    return registered_node(
        NodeDefinition(
            id="test.two_inputs",
            version=1,
            name="Two inputs",
            category="test",
            description="test",
            kind="action",
            config_schema=None,
            input_schema=_Two,
            output_schema=_PlainOutput,
            ports=(
                Port(id="in", label="In", kind="input"),
                Port(id="out", label="Out", kind="output", schema=_PlainOutput),
            ),
            effect_kind="pure",
            retry_guarantee="idempotent",
        )
    )


def _fork_graph(*, joined: bool = True) -> tuple[WorkflowGraph, dict[str, NodeInstance]]:
    entry, split = _echo_node(), _split_node("S", "a", "b")
    a, b = _step("A"), _step("B")
    nodes = {"entry": entry, "S": split, "A": a, "B": b}
    edges = [(entry, "out", split), (split, "a", a), (split, "b", b)]
    if joined:
        join = _step("J")
        nodes["J"] = join
        edges += [(a, "out", join), (b, "out", join)]
    return _graph(*nodes.values(), edges=edges), nodes


class TestParallelBranches:
    async def test_a_step_may_send_one_port_to_several_steps(self, mock_db_session):
        entry, a, b = _echo_node(), _step("A"), _step("B")
        graph = _graph(entry, a, b, edges=[(entry, "out", a), (entry, "out", b)])
        assert await validate_graph(mock_db_session, _owner_ctx(), graph)

    async def test_an_error_port_may_feed_several_steps(self, mock_db_session):
        entry = _echo_node()
        routed = _step("R", policy=NodePolicy(on_error="route"))
        first, second = _step("E1"), _step("E2")
        graph = _graph(
            entry,
            routed,
            first,
            second,
            edges=[(entry, "out", routed), (routed, "error", first), (routed, "error", second)],
        )
        assert await validate_graph(mock_db_session, _owner_ctx(), graph)

    async def test_a_split_publishes_without_becoming_a_scope(self, mock_db_session):
        graph, nodes = _fork_graph()
        validated = await validate_graph(mock_db_session, _owner_ctx(), graph)
        assert validated.scopes == ()
        assert nodes["S"].id in {node.id for node in validated.nodes}

    async def test_a_join_may_bind_to_every_parallel_leg(self, mock_db_session, registered_node):
        both = _two_ins(registered_node)
        leg = registered_node(_action_definition("test.leg", requires_input=False))
        entry, split = _echo_node(), _split_node("S", "a", "b")
        a, b, join = _named("A", leg.id), _named("B", leg.id), _named("J", both.id)
        graph = _graph(
            entry,
            split,
            a,
            b,
            join,
            edges=[
                (entry, "out", split),
                (split, "a", a),
                (split, "b", b),
                (a, "out", join),
                (b, "out", join),
            ],
            bindings=[
                Binding(
                    target_node_id=join.id,
                    target_field=field,
                    source=NodeOutputRef(node_id=source.id, port="out", field_path=("value",)),
                )
                for field, source in (("a", a), ("b", b))
            ],
        )
        assert await validate_graph(mock_db_session, _owner_ctx(), graph)

    async def test_a_join_may_not_bind_to_one_exclusive_branch(
        self, mock_db_session, registered_node
    ):
        both = _two_ins(registered_node)
        entry, branch = _echo_node(), _if_node("I")
        a, b, join = _step("A"), _step("B"), _named("J", both.id)
        graph = _graph(
            entry,
            branch,
            a,
            b,
            join,
            edges=[
                (entry, "out", branch),
                (branch, "true", a),
                (branch, "false", b),
                (a, "out", join),
                (b, "out", join),
            ],
            bindings=[
                _decides_on(branch.id),
                Binding(
                    target_node_id=join.id,
                    target_field="a",
                    source=NodeOutputRef(node_id=a.id, port="out", field_path=("value",)),
                ),
                Binding(target_node_id=join.id, target_field="b", source=LiteralValue(value="x")),
            ],
        )
        fields = await _fields(graph, mock_db_session)
        assert _has(fields, "bindings.1", "has not necessarily run")

    async def test_a_step_fed_by_legs_one_of_which_may_turn_away_publishes(self, mock_db_session):
        """An implicit join runs when any wire is live: partial liveness is not refused."""
        entry = _echo_node()
        switch = _named("W", "logic.switch", {"rules": [{"name": "r", "condition": "value"}]})
        a, b, join = _step("A"), _if_node("B"), _step("J")
        graph = _graph(
            entry,
            switch,
            a,
            b,
            join,
            edges=[
                (entry, "out", switch),
                (switch, "r", a),
                (switch, "r", b),
                (a, "out", join),
                (b, "true", join),
            ],
            bindings=[_decides_on(switch.id), _decides_on(b.id)],
        )
        assert await validate_graph(mock_db_session, _owner_ctx(), graph)

    async def test_an_action_fed_from_both_outcomes_of_an_if_without_a_merge_publishes(
        self, mock_db_session
    ):
        entry, branch = _echo_node(), _if_node("I")
        a, b, join = _step("A"), _step("B"), _step("J")
        graph = _graph(
            entry,
            branch,
            a,
            b,
            join,
            edges=[
                (entry, "out", branch),
                (branch, "true", a),
                (branch, "false", b),
                (a, "out", join),
                (b, "out", join),
            ],
            bindings=[_decides_on(branch.id)],
        )
        assert await validate_graph(mock_db_session, _owner_ctx(), graph)

    async def test_two_parallel_error_routes_into_one_handler_are_refused(self, mock_db_session):
        entry, split = _echo_node(), _split_node("S", "a", "b")
        a = _step("A", policy=NodePolicy(on_error="route"))
        b = _step("B", policy=NodePolicy(on_error="route"))
        handler, after = _named("H", "error.handle"), _step("After")
        graph = _graph(
            entry,
            split,
            a,
            b,
            handler,
            after,
            edges=[
                (entry, "out", split),
                (split, "a", a),
                (split, "b", b),
                (a, "error", handler),
                (b, "error", handler),
                (handler, "default", after),
            ],
        )
        fields = await _fields(graph, mock_db_session)
        assert _has(fields, f"nodes.{handler.id}", "give each branch its own error handler")

    async def test_one_handler_per_branch_publishes(self, mock_db_session):
        entry, split = _echo_node(), _split_node("S", "a", "b")
        a = _step("A", policy=NodePolicy(on_error="route"))
        b = _step("B", policy=NodePolicy(on_error="route"))
        first, second = _named("H1", "error.handle"), _named("H2", "error.handle")
        after_a, after_b = _step("AfterA"), _step("AfterB")
        graph = _graph(
            entry,
            split,
            a,
            b,
            first,
            second,
            after_a,
            after_b,
            edges=[
                (entry, "out", split),
                (split, "a", a),
                (split, "b", b),
                (a, "error", first),
                (b, "error", second),
                (first, "default", after_a),
                (second, "default", after_b),
            ],
        )
        assert await validate_graph(mock_db_session, _owner_ctx(), graph)

    @pytest.mark.parametrize(
        ("definition_id", "config", "text"),
        [
            ("core.output", {}, "a run answers once"),
            ("webhook.respond", {}, "a webhook is answered once"),
        ],
    )
    async def test_two_answering_steps_that_can_both_run_are_refused(
        self, mock_db_session, definition_id, config, text
    ):
        entry, split = _echo_node(), _split_node("S", "a", "b")
        first, second = _named("O1", definition_id, config), _named("O2", definition_id, config)
        graph = _graph(
            entry,
            split,
            first,
            second,
            edges=[(entry, "out", split), (split, "a", first), (split, "b", second)],
        )
        fields = await _fields(graph, mock_db_session)
        assert _has(fields, f"nodes.{second.id}", text)
        assert not any(f["field"] == f"nodes.{first.id}" for f in fields)

    @pytest.mark.parametrize("definition_id", ["core.output", "webhook.respond"])
    async def test_two_answering_steps_on_the_two_sides_of_an_if_publish(
        self, mock_db_session, definition_id
    ):
        entry, branch = _echo_node(), _if_node("I")
        first, second = _named("O1", definition_id), _named("O2", definition_id)
        graph = _graph(
            entry,
            branch,
            first,
            second,
            edges=[(entry, "out", branch), (branch, "true", first), (branch, "false", second)],
            bindings=[_decides_on(branch.id)],
        )
        assert await validate_graph(mock_db_session, _owner_ctx(), graph)

    async def test_a_binding_beside_a_parallel_leg_reads_it_after_the_join_only(
        self, mock_db_session
    ):
        """A leg is not available to its sibling: only to what follows the join."""
        graph, nodes = _fork_graph(joined=False)
        graph = graph.model_copy(
            update={
                "bindings": (
                    Binding(
                        target_node_id=nodes["B"].id,
                        target_field="mappings",
                        source=NodeOutputRef(node_id=nodes["A"].id, port="out"),
                    ),
                )
            }
        )
        fields = await _fields(graph, mock_db_session)
        assert _has(fields, "bindings.0", "has not necessarily run")


def _merged_fork(*, wait_for: str | None, config: dict | None = None):
    """`S.a -> A -> M`, `S.b -> B -> M`, then `After`; `wait_for` set on the merge."""
    entry, split = _echo_node(), _split_node("S", "a", "b")
    a, b, after = _step("A"), _step("B"), _step("After")
    merge_config = dict(config or {})
    if wait_for is not None:
        merge_config["wait_for"] = wait_for
    merge = _named("M", "logic.merge", merge_config)
    graph = _graph(
        entry,
        split,
        a,
        b,
        merge,
        after,
        edges=[
            (entry, "out", split),
            (split, "a", a),
            (split, "b", b),
            (a, "out", merge),
            (b, "out", merge),
            (merge, "out", after),
        ],
    )
    return graph, merge, (a, b, after)


class TestSplitAndMerge:
    async def test_a_split_that_routes_its_errors_is_refused(self, mock_db_session):
        graph, nodes = _fork_graph()
        split = nodes["S"].model_copy(update={"policy": NodePolicy(on_error="route")})
        graph = graph.model_copy(
            update={"nodes": tuple(split if n.id == split.id else n for n in graph.nodes)}
        )
        fields = await _fields(graph, mock_db_session)
        assert _has(fields, f"nodes.{split.id}.policy", "A Split cannot route its errors")

    @pytest.mark.parametrize(
        ("field", "value"),
        [("wait_for", "all"), ("branch_keys", []), ("branch_keys/a", "x")],
    )
    async def test_a_merge_setting_cannot_be_bound(self, mock_db_session, field: str, value):
        """The executor reads these from the stored config, so a binding would be
        applied to the handler's call but not to when the merge runs."""
        graph, merge, _ = _merged_fork(wait_for="all")
        bound = Binding(
            target_node_id=merge.id, target_field=field, source=LiteralValue(value=value)
        )
        graph = graph.model_copy(update={"bindings": (bound,)})
        fields = await _fields(graph, mock_db_session)
        assert _has(fields, f"nodes.{merge.id}.{field}", "cannot be bound")

    async def test_a_merge_waiting_for_one_behind_a_split_is_refused(self, mock_db_session):
        graph, merge, _ = _merged_fork(wait_for=None)
        fields = await _fields(graph, mock_db_session)
        assert _has(fields, f"nodes.{merge.id}", "set Wait for to All branches")
        assert len([f for f in fields if f["field"] == f"nodes.{merge.id}"]) == 1

    async def test_a_merge_waiting_for_all_behind_a_split_publishes(self, mock_db_session):
        graph, _merge, _ = _merged_fork(wait_for="all")
        assert await validate_graph(mock_db_session, _owner_ctx(), graph)

    async def test_a_merge_waiting_for_all_behind_an_if_is_refused(self, mock_db_session):
        entry, branch = _echo_node(), _if_node("I")
        a, b = _step("A"), _step("B")
        merge = _named("M", "logic.merge", {"wait_for": "all"})
        graph = _graph(
            entry,
            branch,
            a,
            b,
            merge,
            edges=[
                (entry, "out", branch),
                (branch, "true", a),
                (branch, "false", b),
                (a, "out", merge),
                (b, "out", merge),
            ],
            bindings=[_decides_on(branch.id)],
        )
        fields = await _fields(graph, mock_db_session)
        assert _has(fields, f"nodes.{merge.id}", "set Wait for to The branch that ran")

    async def test_a_merge_waiting_for_one_behind_an_if_still_publishes(self, mock_db_session):
        entry, branch = _echo_node(), _if_node("I")
        a, b = _step("A"), _step("B")
        merge = _named("M", "logic.merge")
        graph = _graph(
            entry,
            branch,
            a,
            b,
            merge,
            edges=[
                (entry, "out", branch),
                (branch, "true", a),
                (branch, "false", b),
                (a, "out", merge),
                (b, "out", merge),
            ],
            bindings=[_decides_on(branch.id)],
        )
        assert await validate_graph(mock_db_session, _owner_ctx(), graph)

    async def test_a_stored_merge_with_empty_config_still_publishes(self, mock_db_session):
        entry = _echo_node()
        merge = _named("M", "logic.merge", {})
        graph = _graph(entry, merge, edges=[(entry, "out", merge)])
        assert await validate_graph(mock_db_session, _owner_ctx(), graph)

    async def test_a_merge_waiting_for_all_with_one_input_is_not_judged(self, mock_db_session):
        entry = _echo_node()
        merge = _named("M", "logic.merge", {"wait_for": "all"})
        graph = _graph(entry, merge, edges=[(entry, "out", merge)])
        assert await validate_graph(mock_db_session, _owner_ctx(), graph)

    async def test_two_merge_branches_with_one_key_are_refused(self, mock_db_session):
        graph, merge, (a, b, _after) = _merged_fork(wait_for="all")
        keys = [
            {"source_node_id": str(a.id), "source_port": "out", "key": "same"},
            {"source_node_id": str(b.id), "source_port": "out", "key": "same"},
        ]
        merge = merge.model_copy(update={"config": {"wait_for": "all", "branch_keys": keys}})
        graph = graph.model_copy(
            update={"nodes": tuple(merge if n.id == merge.id else n for n in graph.nodes)}
        )
        fields = await _fields(graph, mock_db_session)
        assert _has(fields, f"nodes.{merge.id}.config.branch_keys", "a name of its own")

    async def test_a_merge_branch_with_no_usable_name_is_refused(self, mock_db_session):
        graph, merge, (a, _b, _after) = _merged_fork(wait_for="all")
        a_named = a.model_copy(update={"label": "!!!"})
        graph = graph.model_copy(
            update={"nodes": tuple(a_named if n.id == a.id else n for n in graph.nodes)}
        )
        fields = await _fields(graph, mock_db_session)
        assert _has(fields, f"nodes.{merge.id}.config.branch_keys", "a name of its own")

    async def test_reading_an_unknown_merge_branch_is_refused(
        self, mock_db_session, registered_node
    ):
        consumer = registered_node(_action_definition("test.reads_branch"))
        graph, merge, _ = _merged_fork(wait_for="all")
        reader = _named("Reader", consumer.id)

        def reading(key: str) -> WorkflowGraph:
            binding = Binding(
                target_node_id=reader.id,
                target_field="value",
                source=NodeOutputRef(
                    node_id=merge.id, port="out", field_path=("branches", key, "value")
                ),
            )
            return graph.model_copy(
                update={
                    "nodes": (*graph.nodes, reader),
                    "edges": (*graph.edges, _edge(merge.id, "out", reader.id, "in")),
                    "bindings": (binding,),
                }
            )

        assert await validate_graph(mock_db_session, _owner_ctx(), reading("a"))
        fields = await _fields(reading("nope"), mock_db_session)
        assert _has(fields, "bindings.0", "This merge has no branch called 'nope'")


class TestStepsReachedFromSeveralPorts:
    """A step that hangs from one port by dominance may still be reached from another."""

    async def test_two_outputs_after_a_step_reached_from_both_ports_are_refused(
        self, mock_db_session
    ):
        """`X.true -> P -> {O1, T}`, `X.false -> T -> O2`: with X true both outputs run."""
        entry, branch = _echo_node(), _if_node("X")
        p, t = _step("P"), _step("T")
        first, second = _named("O1", "core.output"), _named("O2", "core.output")
        graph = _graph(
            entry,
            branch,
            p,
            t,
            first,
            second,
            edges=[
                (entry, "out", branch),
                (branch, "true", p),
                (p, "out", first),
                (p, "out", t),
                (branch, "false", t),
                (t, "out", second),
            ],
            bindings=[_decides_on(branch.id)],
        )
        fields = await _fields(graph, mock_db_session)
        assert _has(fields, f"nodes.{second.id}", "a run answers once")

    async def test_a_merge_waiting_for_one_beside_a_step_reached_from_both_ports_is_refused(
        self, mock_db_session
    ):
        """`X.true -> P -> T`, `X.false -> T`, `T -> M`, `P -> M`: with X true both reach M."""
        entry, branch = _echo_node(), _if_node("X")
        p, t, merge = _step("P"), _step("T"), _named("M", "logic.merge")
        graph = _graph(
            entry,
            branch,
            p,
            t,
            merge,
            edges=[
                (entry, "out", branch),
                (branch, "true", p),
                (p, "out", t),
                (branch, "false", t),
                (t, "out", merge),
                (p, "out", merge),
            ],
            bindings=[_decides_on(branch.id)],
        )
        fields = await _fields(graph, mock_db_session)
        assert _has(fields, f"nodes.{merge.id}", "Several branches reach this merge together")

    async def test_a_join_may_not_read_a_leg_that_one_port_of_an_if_skips(
        self, mock_db_session, registered_node
    ):
        """`X.true -> t`, `X.false -> Y -> t`, `t -> T`, `X.true -> A`; `A, T -> J`: A can be dead."""
        leg = registered_node(_action_definition("test.leg", requires_input=False))
        consumer = registered_node(_action_definition("test.joined"))
        entry, branch = _echo_node(), _if_node("X")
        t0, y, t = _step("t0"), _step("Y"), _step("T")
        a, join = _named("A", leg.id), _named("J", consumer.id)
        graph = _graph(
            entry,
            branch,
            t0,
            y,
            t,
            a,
            join,
            edges=[
                (entry, "out", branch),
                (branch, "true", t0),
                (branch, "false", y),
                (y, "out", t0),
                (t0, "out", t),
                (branch, "true", a),
                (a, "out", join),
                (t, "out", join),
            ],
            bindings=[
                _decides_on(branch.id),
                Binding(
                    target_node_id=join.id,
                    target_field="value",
                    source=NodeOutputRef(node_id=a.id, port="out", field_path=("value",)),
                ),
            ],
        )
        fields = await _fields(graph, mock_db_session)
        assert _has(fields, "bindings.1", "has not necessarily run")


class TestMergeEdgeCases:
    async def test_a_merge_waiting_for_all_still_refuses_two_edges_from_one_branch(
        self, mock_db_session
    ):
        graph, merge, (a, _b, _after) = _merged_fork(wait_for="all")
        graph = graph.model_copy(
            update={"edges": (*graph.edges, _edge(a.id, "out", merge.id, "in"))}
        )
        fields = await _fields(graph, mock_db_session)
        assert _has(fields, f"nodes.{merge.id}", "more than one edge from the same branch")

    async def test_a_merge_fed_by_parallel_branches_still_refuses_two_edges_from_one_branch(
        self, mock_db_session
    ):
        graph, merge, (a, _b, _after) = _merged_fork(wait_for=None)
        graph = graph.model_copy(
            update={"edges": (*graph.edges, _edge(a.id, "out", merge.id, "in"))}
        )
        fields = await _fields(graph, mock_db_session)
        assert _has(fields, f"nodes.{merge.id}", "more than one edge from the same branch")
        assert _has(fields, f"nodes.{merge.id}", "Several branches reach this merge together")

    async def test_the_wait_for_hint_is_not_offered_for_an_unreachable_branch(
        self, mock_db_session
    ):
        entry, a, unreachable = _echo_node(), _step("A"), _step("Z")
        merge = _named("M", "logic.merge")
        graph = _graph(
            entry,
            a,
            unreachable,
            merge,
            edges=[(entry, "out", a), (a, "out", merge), (unreachable, "out", merge)],
        )
        fields = await _fields(graph, mock_db_session)
        assert any(f["field"] == f"nodes.{unreachable.id}" for f in fields)
        assert not any("Wait for" in f["message"] for f in fields)


class TestMergeJudgedByRunConditions:
    async def test_a_merge_after_a_nested_if_with_a_shared_else_publishes(self, mock_db_session):
        """`X.true -> Y`, `Y.true -> A`, `Y.false -> T`, `X.false -> T`: A and T never run together."""
        entry, x, y = _echo_node(), _if_node("X"), _if_node("Y")
        a, t, merge = _step("A"), _step("T"), _named("M", "logic.merge")
        graph = _graph(
            entry,
            x,
            y,
            a,
            t,
            merge,
            edges=[
                (entry, "out", x),
                (x, "true", y),
                (y, "true", a),
                (y, "false", t),
                (x, "false", t),
                (a, "out", merge),
                (t, "out", merge),
            ],
            bindings=[_decides_on(x.id), _decides_on(y.id)],
        )
        assert await validate_graph(mock_db_session, _owner_ctx(), graph)

    async def test_a_merge_after_a_switch_whose_cases_share_a_step_publishes(self, mock_db_session):
        entry = _echo_node()
        switch = _named(
            "S",
            "logic.switch",
            {"rules": [{"name": "a", "condition": "value"}, {"name": "b", "condition": "value"}]},
        )
        shared, other, merge = _step("Shared"), _step("C"), _named("M", "logic.merge")
        graph = _graph(
            entry,
            switch,
            shared,
            other,
            merge,
            edges=[
                (entry, "out", switch),
                (switch, "a", shared),
                (switch, "b", shared),
                (switch, "otherwise", other),
                (shared, "out", merge),
                (other, "out", merge),
            ],
            bindings=[_decides_on(switch.id)],
        )
        assert await validate_graph(mock_db_session, _owner_ctx(), graph)

    async def test_a_merge_waiting_for_all_names_a_branch_that_may_not_arrive(
        self, mock_db_session
    ):
        """An unwired `otherwise` can be taken and reach nothing: neither branch is certain."""
        entry = _echo_node()
        switch = _named(
            "S",
            "logic.switch",
            {"rules": [{"name": "r1", "condition": "value"}, {"name": "r2", "condition": "value"}]},
        )
        a, b = _step("A"), _step("B")
        d = _step("D")
        split = _split_node("P", "x", "y")
        merge = _named("M", "logic.merge", {"wait_for": "all"})
        graph = _graph(
            entry,
            split,
            switch,
            d,
            a,
            b,
            merge,
            edges=[
                (entry, "out", split),
                (split, "x", switch),
                (split, "y", d),
                (switch, "r1", a),
                (switch, "r2", b),
                (a, "out", merge),
                (b, "out", merge),
                (d, "out", merge),
            ],
            bindings=[_decides_on(switch.id)],
        )
        fields = await _fields(graph, mock_db_session)
        assert _has(fields, f"nodes.{merge.id}", "'a' is not certain to reach this merge")
        assert _has(fields, f"nodes.{merge.id}", "'b' is not certain to reach this merge")
        assert not _has(fields, f"nodes.{merge.id}", "'d' is not certain")

    async def test_a_merge_waiting_for_one_names_a_branch_that_may_not_arrive(
        self, mock_db_session
    ):
        entry, split = _echo_node(), _split_node("S", "a", "b")
        branch = _if_node("I")
        a, b, merge = _step("A"), _step("B"), _named("M", "logic.merge")
        graph = _graph(
            entry,
            split,
            branch,
            a,
            b,
            merge,
            edges=[
                (entry, "out", split),
                (split, "a", branch),
                (split, "b", b),
                (branch, "true", a),
                (a, "out", merge),
                (b, "out", merge),
            ],
            bindings=[_decides_on(branch.id)],
        )
        fields = await _fields(graph, mock_db_session)
        assert _has(fields, f"nodes.{merge.id}", "Several branches reach this merge together")
        assert _has(fields, f"nodes.{merge.id}", "'a' is not certain to arrive")
        assert not _has(fields, f"nodes.{merge.id}", "set Wait for to All branches")

    async def test_a_merge_joining_a_routed_steps_out_and_its_handler_publishes(
        self, mock_db_session
    ):
        entry = _echo_node()
        routed = _step("R", policy=NodePolicy(on_error="route"))
        handler, merge = _named("H", "error.handle"), _named("M", "logic.merge")
        graph = _graph(
            entry,
            routed,
            handler,
            merge,
            edges=[
                (entry, "out", routed),
                (routed, "out", merge),
                (routed, "error", handler),
                (handler, "default", merge),
            ],
        )
        assert await validate_graph(mock_db_session, _owner_ctx(), graph)

    async def test_a_handler_fed_by_two_steps_that_cannot_both_fail_publishes(
        self, mock_db_session
    ):
        entry, branch = _echo_node(), _if_node("I")
        a = _step("A", policy=NodePolicy(on_error="route"))
        b = _step("B", policy=NodePolicy(on_error="route"))
        handler, after = _named("H", "error.handle"), _step("After")
        graph = _graph(
            entry,
            branch,
            a,
            b,
            handler,
            after,
            edges=[
                (entry, "out", branch),
                (branch, "true", a),
                (branch, "false", b),
                (a, "error", handler),
                (b, "error", handler),
                (handler, "default", after),
            ],
            bindings=[_decides_on(branch.id)],
        )
        assert await validate_graph(mock_db_session, _owner_ctx(), graph)
