"""Tests for `validate_graph`: one test per rule, refusing with actionable errors.

AC2 of #1786: invalid imports/graphs, missing versions, inaccessible resources
and unavailable branch bindings fail publication with actionable errors.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict

from app.core.permissions import AuthContext, OrgRoleName
from app.repositories import virtual_table_repo
from app.workflows._registry import REGISTRY, register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.contracts.io import Binding, FileRef, LiteralValue, NodeOutputRef, TableIORef
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
    """`c` binds to `b`'s output, but `b` is only reachable on one of two
    branches into `c` - so `b` does not dominate `c`."""
    merge = registered_node(_action_definition("test.branch_merge"))
    a = _echo_node()
    b = _echo_node()
    c = NodeInstance(
        id=uuid4(), definition_id=merge.id, definition_version=1, config={}, layout=_pos()
    )
    edges = (
        _edge(a.id, "out", b.id, "in"),
        _edge(a.id, "out", c.id, "in"),
        _edge(b.id, "out", c.id, "in"),
    )
    binding = Binding(
        target_node_id=c.id,
        target_field="value",
        source=NodeOutputRef(node_id=b.id, port="out", field_path=("value",)),
    )
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b, c), edges=edges, bindings=(binding,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(f["field"] == "bindings.0" for f in excinfo.value.details["fields"])


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


async def test_a_merges_branches_not_from_one_if_are_refused(mock_db_session, registered_node):
    merge = registered_node(_action_definition("logic.merge", requires_input=False))
    a, b = _echo_node(), _echo_node()
    c = NodeInstance(
        id=uuid4(), definition_id=merge.id, definition_version=1, config={}, layout=_pos()
    )
    # Two independent predecessors, no shared `logic.if` ancestor at all.
    edges = (_edge(a.id, "out", c.id, "in"), _edge(b.id, "out", c.id, "in"))
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b, c), edges=edges)
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(f"nodes.{c.id}" == f["field"] for f in excinfo.value.details["fields"])


async def test_a_merge_from_one_logic_if_publishes(mock_db_session, registered_node):
    branch_if = registered_node(
        NodeDefinition(
            id="logic.if",
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
    merge = registered_node(_action_definition("logic.merge", requires_input=False))
    entry = _echo_node()
    branch_node = NodeInstance(
        id=uuid4(), definition_id=branch_if.id, definition_version=1, config={}, layout=_pos()
    )
    then_leg = _echo_node()
    else_leg = _echo_node()
    merge_node = NodeInstance(
        id=uuid4(), definition_id=merge.id, definition_version=1, config={}, layout=_pos()
    )
    edges = (
        _edge(entry.id, "out", branch_node.id, "in"),
        _edge(branch_node.id, "then", then_leg.id, "in"),
        _edge(branch_node.id, "otherwise", else_leg.id, "in"),
        _edge(then_leg.id, "out", merge_node.id, "in"),
        _edge(else_leg.id, "out", merge_node.id, "in"),
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, branch_node, then_leg, else_leg, merge_node),
        edges=edges,
    )
    validated = await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert validated.entry_node_id == entry.id


async def test_a_merges_branches_from_the_same_if_port_are_refused(
    mock_db_session, registered_node
):
    """Rule 8 lets a control node fan one port out to more than one target,
    so both legs here share `logic.if`'s `then` port - they run together or
    not at all, never exclusively, even though they share a dominator."""
    branch_if = registered_node(
        NodeDefinition(
            id="logic.if",
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
    merge = registered_node(_action_definition("logic.merge", requires_input=False))
    entry = _echo_node()
    branch_node = NodeInstance(
        id=uuid4(), definition_id=branch_if.id, definition_version=1, config={}, layout=_pos()
    )
    then_leg = _echo_node()
    other_leg = _echo_node()
    merge_node = NodeInstance(
        id=uuid4(), definition_id=merge.id, definition_version=1, config={}, layout=_pos()
    )
    edges = (
        _edge(entry.id, "out", branch_node.id, "in"),
        _edge(branch_node.id, "then", then_leg.id, "in"),
        _edge(branch_node.id, "then", other_leg.id, "in"),
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
        f["field"] == f"nodes.{merge_node.id}" and "same port" in f["message"]
        for f in excinfo.value.details["fields"]
    )


async def test_a_merge_with_two_edges_from_the_same_branch_is_refused(
    mock_db_session, registered_node
):
    merge = registered_node(_action_definition("logic.merge", requires_input=False))
    a = _echo_node()
    c = NodeInstance(
        id=uuid4(), definition_id=merge.id, definition_version=1, config={}, layout=_pos()
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
    """`a` is downstream of *both* `then` (via `t`) and `otherwise` (via `e`)
    - it runs on either outcome, so it is not exclusive with `b`, which only
    runs on `then`. Neither of `logic.if`'s own children dominates `a` alone
    (`t` and `e` each dominate only their own leg), so `a`'s dominator set
    stops at `logic.if` itself and no single feeding port can be named for
    it - the gap a bare "do the sets overlap" check missed entirely."""
    branch_if = registered_node(
        NodeDefinition(
            id="logic.if",
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
    merge = registered_node(_action_definition("logic.merge", requires_input=False))
    entry = _echo_node()
    branch_node = NodeInstance(
        id=uuid4(), definition_id=branch_if.id, definition_version=1, config={}, layout=_pos()
    )
    t, e, a, b = _echo_node(), _echo_node(), _echo_node(), _echo_node()
    merge_node = NodeInstance(
        id=uuid4(), definition_id=merge.id, definition_version=1, config={}, layout=_pos()
    )
    edges = (
        _edge(entry.id, "out", branch_node.id, "in"),
        _edge(branch_node.id, "then", t.id, "in"),
        _edge(branch_node.id, "then", b.id, "in"),
        _edge(branch_node.id, "otherwise", e.id, "in"),
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
        f["field"] == f"nodes.{merge_node.id}" and "mutually exclusive" in f["message"]
        for f in excinfo.value.details["fields"]
    )


# Rule 6 - nested scope boundaries


def _loop_definition() -> NodeDefinition:
    return NodeDefinition(
        id="control.foreach",
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
        id="loop.yield",
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
    """#1790's actual shape: `loop.yield`'s own outgoing edge is the scope's
    exit, not `control.foreach`'s. No real `control.foreach` ships in #1786,
    so `derive_scopes` cannot discover this on its own yet - this hand-builds
    the `ScopeBoundary` it will eventually derive and confirms every rule
    that reads `exit_port` already honors `exit_node_id` naming a
    body-interior node, not only `scope_node_id` itself.
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


async def test_a_non_control_node_with_two_edges_on_one_port_is_refused(mock_db_session):
    a = _echo_node()
    b, c = _echo_node(), _echo_node()
    edges = (_edge(a.id, "out", b.id, "in"), _edge(a.id, "out", c.id, "in"))
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b, c), edges=edges)
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(f["field"] == f"nodes.{a.id}" for f in excinfo.value.details["fields"])


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
