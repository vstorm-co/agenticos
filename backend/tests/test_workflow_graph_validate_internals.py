"""Edge cases of `validate_graph` and its pure helpers not reached by the
one-problem-at-a-time tests in `test_workflow_graph_validation.py`: multiple
converging paths inside a scope body, dominance edge cases, and a couple of
the module's private helpers exercised directly where building a full graph
to reach them would be more contrived than informative.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict

from app.core.permissions import AuthContext, OrgRoleName
from app.repositories import virtual_table_repo
from app.workflows._registry import REGISTRY, register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.contracts.io import Binding, LiteralValue, NodeOutputRef, TableIORef
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import (
    _kahn,
    _nearest_common_dominator,
    derive_scopes,
    validate_graph,
)

pytestmark = pytest.mark.anyio


def _owner_ctx() -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER.value)


def _pos() -> NodePosition:
    return NodePosition(x=0, y=0)


def _echo_node(**overrides: object) -> NodeInstance:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "definition_id": "debug.echo",
        "definition_version": 1,
        "config": {"message": "hi"},
        "layout": _pos(),
    }
    defaults.update(overrides)
    return NodeInstance(**defaults)  # type: ignore[arg-type]


def _edge(source, source_port: str, target, target_port: str) -> Edge:
    return Edge(
        id=uuid4(),
        source_node_id=source,
        source_port=source_port,
        target_node_id=target,
        target_port=target_port,
    )


@pytest.fixture
def registered_node():
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


def test_a_control_node_with_only_one_output_port_gets_no_derived_scope(registered_node):
    definition = registered_node(
        NodeDefinition(
            id="control.single_port",
            version=1,
            name="Single port control",
            category="control",
            description="only one output port, so it owns no scope",
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
    )
    entry = _echo_node()
    control_node = NodeInstance(
        id=uuid4(), definition_id=definition.id, definition_version=1, config={}, layout=_pos()
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, control_node),
        edges=(_edge(entry.id, "out", control_node.id, "in"),),
    )
    derived = derive_scopes(graph)
    assert derived.scopes == ()


def test_a_scope_body_with_a_diamond_and_a_loop_back_edge_is_derived_once_each(registered_node):
    """Two paths converging on one body node, and a `continue`-style edge
    back into the loop node, are exactly the shapes a real `control.foreach`
    body has: `_body_reachable_from` must visit each body node once and never
    re-enter `scope_node_id`."""
    loop_def = registered_node(
        NodeDefinition(
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
    )
    entry = _echo_node()
    loop_node = NodeInstance(
        id=uuid4(), definition_id=loop_def.id, definition_version=1, config={}, layout=_pos()
    )
    b1, b2, b3 = _echo_node(), _echo_node(), _echo_node()
    edges = (
        _edge(entry.id, "out", loop_node.id, "in"),
        _edge(loop_node.id, "body", b1.id, "in"),
        _edge(loop_node.id, "body", b2.id, "in"),
        _edge(b1.id, "out", b3.id, "in"),
        _edge(b2.id, "out", b3.id, "in"),
        # Closes the iteration: leads back into the loop node itself, not
        # further into the body.
        _edge(b3.id, "out", loop_node.id, "in"),
        # A second edge out of `b3`, back to `b1` - already visited by the
        # time `b3` is processed, so this is the walk's "do not re-enqueue an
        # already-seen node" branch, distinct from "never re-enter the scope
        # node" above.
        _edge(b3.id, "out", b1.id, "in"),
    )
    graph = WorkflowGraph(entry_node_id=entry.id, nodes=(entry, loop_node, b1, b2, b3), edges=edges)
    derived = derive_scopes(graph)
    scope = next(s for s in derived.scopes if s.scope_node_id == loop_node.id)
    assert scope.body_node_ids == frozenset({b1.id, b2.id, b3.id})


async def test_a_table_binding_with_no_named_columns_means_every_live_column(
    mock_db_session, monkeypatch
):
    ctx = _owner_ctx()
    table = SimpleNamespace(
        id=uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=None,
        visibility="org",
        schema_version=1,
    )
    monkeypatch.setattr(virtual_table_repo, "get_table", AsyncMock(return_value=table))
    entry = _echo_node()
    graph = WorkflowGraph(entry_node_id=entry.id, nodes=(entry,))
    binding = Binding(
        target_node_id=entry.id,
        target_field="message",
        source=TableIORef(table_id=table.id, column_ids=None, schema_version=1),
    )
    graph = graph.model_copy(update={"bindings": (binding,)})
    validated = await validate_graph(mock_db_session, ctx, graph)
    assert validated.bindings == (binding,)


async def test_an_edge_naming_a_port_the_definition_does_not_declare_is_refused(
    mock_db_session,
):
    """An unknown port name is not "unknown shape, skip it" - the edge does
    not connect to anything real, and rule 3 refuses it rather than the
    silent no-op an unresolvable *definition* still gets."""
    a, b = _echo_node(), _echo_node()
    edge = _edge(a.id, "no_such_port", b.id, "in")
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=(edge,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(f["field"] == f"edges.{edge.id}" for f in excinfo.value.details["fields"])


async def test_an_edge_naming_a_target_port_the_definition_does_not_declare_is_refused(
    mock_db_session,
):
    a, b = _echo_node(), _echo_node()
    edge = _edge(a.id, "out", b.id, "no_such_port")
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=(edge,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(f["field"] == f"edges.{edge.id}" for f in excinfo.value.details["fields"])


async def test_a_binding_naming_a_node_not_in_the_graph_is_refused(mock_db_session):
    a, b = _echo_node(), _echo_node()
    edge = _edge(a.id, "out", b.id, "in")
    binding = Binding(
        target_node_id=b.id,
        target_field="message",
        source=NodeOutputRef(node_id=uuid4(), port="out"),
    )
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=(edge,), bindings=(binding,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(f["field"] == "bindings.0" for f in excinfo.value.details["fields"])


async def test_an_edge_from_a_node_id_that_does_not_exist_is_refused_as_a_dangling_reference(
    mock_db_session,
):
    b = _echo_node()
    edge = _edge(uuid4(), "out", b.id, "in")
    graph = WorkflowGraph(entry_node_id=b.id, nodes=(b,), edges=(edge,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(
        f["field"] == f"edges.{edge.id}" and "source node" in f["message"]
        for f in excinfo.value.details["fields"]
    )


async def test_a_binding_targeting_a_node_id_that_does_not_exist_is_refused(mock_db_session):
    a = _echo_node()
    binding = Binding(
        target_node_id=uuid4(), target_field="message", source=LiteralValue(value="x")
    )
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a,), bindings=(binding,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(
        f["field"] == "bindings.0" and "target node" in f["message"]
        for f in excinfo.value.details["fields"]
    )


async def test_a_binding_whose_source_node_exists_but_has_no_resolvable_definition_skips_rule_3(
    mock_db_session,
):
    """`a` is a real member of the graph (no dangling reference), but its own
    `definition_id` does not resolve - rule 3's binding half must fall back
    cleanly rather than dereferencing a `None` definition."""
    a = _echo_node().model_copy(update={"definition_id": "no.such.node"})
    b = _echo_node()
    binding = Binding(
        target_node_id=b.id,
        target_field="message",
        source=NodeOutputRef(node_id=a.id, port="out"),
    )
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), bindings=(binding,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    fields = {f["field"] for f in excinfo.value.details["fields"]}
    assert f"nodes.{a.id}" in fields
    assert not any(field == "bindings.0" for field in fields)


async def test_an_edge_touching_a_node_whose_own_definition_is_unresolvable_is_refused(
    mock_db_session,
):
    """The node is a real member of the graph (so this is not a dangling
    reference) but its own `(definition_id, definition_version)` does not
    resolve - rule 3 must fall back cleanly rather than raising when it asks
    `_port_schema` about a node with no definition at all."""
    a = _echo_node().model_copy(update={"definition_id": "no.such.node"})
    b = _echo_node()
    edge = _edge(a.id, "out", b.id, "in")
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=(edge,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(f["field"] == f"nodes.{a.id}" for f in excinfo.value.details["fields"])


class _Letter(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    letter: str


class _Number(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    letter: int


async def test_an_edge_between_two_ports_of_the_identical_schema_class_publishes(
    mock_db_session, registered_node
):
    sink = registered_node(
        NodeDefinition(
            id="test.identical_shape_sink",
            version=1,
            name="Sink",
            category="test",
            description="accepts exactly the source's shape",
            kind="action",
            config_schema=None,
            input_schema=None,
            output_schema=None,
            ports=(
                Port(id="in", label="In", kind="input", schema=_Letter),
                Port(id="out", label="Out", kind="output", schema=_Letter),
            ),
            effect_kind="pure",
            retry_guarantee="idempotent",
        )
    )
    source = registered_node(
        NodeDefinition(
            id="test.identical_shape_source",
            version=1,
            name="Source",
            category="test",
            description="produces the sink's exact shape",
            kind="action",
            config_schema=None,
            input_schema=None,
            output_schema=_Letter,
            ports=(Port(id="out", label="Out", kind="output", schema=_Letter),),
            effect_kind="pure",
            retry_guarantee="idempotent",
        )
    )
    a = NodeInstance(
        id=uuid4(), definition_id=source.id, definition_version=1, config={}, layout=_pos()
    )
    b = NodeInstance(
        id=uuid4(), definition_id=sink.id, definition_version=1, config={}, layout=_pos()
    )
    edge = _edge(a.id, "out", b.id, "in")
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=(edge,))
    validated = await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert validated.edges == (edge,)


async def test_a_binding_field_path_resolving_to_an_incompatible_field_is_refused(
    mock_db_session, registered_node
):
    consumer = registered_node(
        NodeDefinition(
            id="test.wants_a_number",
            version=1,
            name="Wants a number",
            category="test",
            description="its input schema has an int field",
            kind="action",
            config_schema=None,
            input_schema=_Number,
            output_schema=None,
            ports=(Port(id="in", label="In", kind="input"),),
            effect_kind="pure",
            retry_guarantee="idempotent",
        )
    )
    a = _echo_node()
    b = NodeInstance(
        id=uuid4(), definition_id=consumer.id, definition_version=1, config={}, layout=_pos()
    )
    edge = _edge(a.id, "out", b.id, "in")
    binding = Binding(
        target_node_id=b.id,
        target_field="letter",
        source=NodeOutputRef(node_id=a.id, port="out", field_path=("echoed",)),
    )
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=(edge,), bindings=(binding,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any("not compatible" in f["message"] for f in excinfo.value.details["fields"])


async def test_a_node_unreachable_because_it_is_in_a_cycle_gets_no_dominator_verdict(
    mock_db_session, registered_node
):
    """A binding into a node the cycle left out of the topological order is
    left to rule 7's own refusal - rule 4 has no dominator set to check it
    against and says nothing extra."""
    consumer = registered_node(
        NodeDefinition(
            id="test.cyclic_consumer",
            version=1,
            name="Cyclic consumer",
            category="test",
            description="test",
            kind="action",
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
    )
    a = _echo_node()
    b = NodeInstance(
        id=uuid4(), definition_id=consumer.id, definition_version=1, config={}, layout=_pos()
    )
    c = NodeInstance(
        id=uuid4(), definition_id=consumer.id, definition_version=1, config={}, layout=_pos()
    )
    edges = (
        _edge(a.id, "out", b.id, "in"),
        _edge(b.id, "out", c.id, "in"),
        _edge(c.id, "out", b.id, "in"),
    )
    binding = Binding(
        target_node_id=c.id, target_field="x", source=NodeOutputRef(node_id=b.id, port="out")
    )
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b, c), edges=edges, bindings=(binding,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any("cycle" in f["message"] for f in excinfo.value.details["fields"])


async def test_a_merge_with_a_single_predecessor_is_not_a_merge_rule_5_cares_about(
    mock_db_session, registered_node
):
    merge = registered_node(
        NodeDefinition(
            id="logic.merge",
            version=1,
            name="Merge",
            category="logic",
            description="test",
            kind="action",
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
    )
    a = _echo_node()
    b = NodeInstance(
        id=uuid4(), definition_id=merge.id, definition_version=1, config={}, layout=_pos()
    )
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=(_edge(a.id, "out", b.id, "in"),))
    validated = await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert validated.entry_node_id == a.id


async def test_a_binding_crossing_out_of_a_scope_body_is_refused(mock_db_session, registered_node):
    loop_def = registered_node(
        NodeDefinition(
            id="control.foreach",
            version=1,
            name="For each",
            category="control",
            description="test",
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
    )
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
    binding = Binding(
        target_node_id=after.id,
        target_field="message",
        source=NodeOutputRef(node_id=body_node.id, port="out", field_path=("echoed",)),
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, loop_node, body_node, after),
        edges=edges,
        bindings=(binding,),
    )
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(f["field"] == "bindings.0" for f in excinfo.value.details["fields"])


async def test_a_non_control_node_with_two_edges_on_one_port_is_refused(mock_db_session):
    a = _echo_node()
    b, c = _echo_node(), _echo_node()
    edges = (_edge(a.id, "out", b.id, "in"), _edge(a.id, "out", c.id, "in"))
    # Both edges use the same source port, so this exercises the "more than
    # one edge on one port" branch rather than the "more than one port" one.
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b, c), edges=edges)
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any("more than one edge" in f["message"] for f in excinfo.value.details["fields"])


def test_nearest_common_dominator_with_no_intersection_returns_none():
    x, y = uuid4(), uuid4()
    dominators = {x: frozenset({x}), y: frozenset({y})}
    assert _nearest_common_dominator([x, y], dominators) is None


def test_nearest_common_dominator_with_no_single_nearest_candidate_returns_none():
    """A hand-built, deliberately non-tree-shaped dominators map: `common` is
    non-empty but no member of it dominates every other member, which a real
    dominator tree (nested chains from the root) never produces but the
    function must still answer safely rather than raising."""
    p, q, x, y = uuid4(), uuid4(), uuid4(), uuid4()
    dominators = {
        x: frozenset({p, q, x}),
        y: frozenset({p, q, y}),
    }
    assert _nearest_common_dominator([x, y], dominators) is None


async def test_an_edge_to_a_node_id_that_does_not_exist_is_refused_as_a_dangling_reference(
    mock_db_session,
):
    a = _echo_node()
    edge = _edge(a.id, "out", uuid4(), "in")
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a,), edges=(edge,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any("not in this graph" in f["message"] for f in excinfo.value.details["fields"])


async def test_a_field_path_stepping_into_a_scalar_field_is_refused(mock_db_session):
    """`echoed` is a `str`; walking a further step past it (`echoed.x`) must
    refuse rather than crash, since a `str` has no `model_fields`."""
    a, b = _echo_node(), _echo_node()
    edge = _edge(a.id, "out", b.id, "in")
    binding = Binding(
        target_node_id=b.id,
        target_field="message",
        source=NodeOutputRef(node_id=a.id, port="out", field_path=("echoed", "x")),
    )
    graph = WorkflowGraph(entry_node_id=a.id, nodes=(a, b), edges=(edge,), bindings=(binding,))
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any("field path" in f["message"] for f in excinfo.value.details["fields"])


async def test_a_scope_with_a_cyclic_body_gets_no_dominators_for_its_members(
    mock_db_session, registered_node
):
    """Rule 7 already refuses the cycle; rule 4 must not also try to compute
    dominators over a body that has none, which would raise rather than
    simply contributing no verdict for that binding."""
    loop_def = registered_node(
        NodeDefinition(
            id="control.foreach",
            version=1,
            name="For each",
            category="control",
            description="test",
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
    )
    entry = _echo_node()
    loop_node = NodeInstance(
        id=uuid4(), definition_id=loop_def.id, definition_version=1, config={}, layout=_pos()
    )
    x, y = _echo_node(), _echo_node()
    edges = (
        _edge(entry.id, "out", loop_node.id, "in"),
        _edge(loop_node.id, "body", x.id, "in"),
        # A cycle entirely within the body, independent of the loop-back to
        # `loop_node` itself.
        _edge(x.id, "out", y.id, "in"),
        _edge(y.id, "out", x.id, "in"),
    )
    binding = Binding(
        target_node_id=y.id, target_field="message", source=NodeOutputRef(node_id=x.id, port="out")
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id, nodes=(entry, loop_node, x, y), edges=edges, bindings=(binding,)
    )
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any("cycle" in f["message"] for f in excinfo.value.details["fields"])


async def test_a_merges_common_dominator_that_is_not_logic_if_is_refused(
    mock_db_session, registered_node
):
    """A real common dominator is found (unlike the "share no common
    dominator" case), but it is some other control node, not `logic.if`."""
    switch = registered_node(
        NodeDefinition(
            id="logic.switch",
            version=1,
            name="Switch",
            category="logic",
            description="a control node that is not logic.if",
            kind="control",
            config_schema=None,
            input_schema=None,
            output_schema=None,
            ports=(
                Port(id="in", label="In", kind="input"),
                Port(id="a", label="A", kind="output"),
                Port(id="b", label="B", kind="output"),
            ),
            effect_kind="pure",
            retry_guarantee="idempotent",
        )
    )
    merge = registered_node(
        NodeDefinition(
            id="logic.merge",
            version=1,
            name="Merge",
            category="logic",
            description="test",
            kind="action",
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
    )
    entry = _echo_node()
    switch_node = NodeInstance(
        id=uuid4(), definition_id=switch.id, definition_version=1, config={}, layout=_pos()
    )
    branch_a, branch_b = _echo_node(), _echo_node()
    merge_node = NodeInstance(
        id=uuid4(), definition_id=merge.id, definition_version=1, config={}, layout=_pos()
    )
    edges = (
        _edge(entry.id, "out", switch_node.id, "in"),
        _edge(switch_node.id, "a", branch_a.id, "in"),
        _edge(switch_node.id, "b", branch_b.id, "in"),
        _edge(branch_a.id, "out", merge_node.id, "in"),
        _edge(branch_b.id, "out", merge_node.id, "in"),
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, switch_node, branch_a, branch_b, merge_node),
        edges=edges,
    )
    with pytest.raises(GraphValidationError) as excinfo:
        await validate_graph(mock_db_session, _owner_ctx(), graph)
    assert any(
        f["field"] == f"nodes.{merge_node.id}" and "logic.if" in f["message"]
        for f in excinfo.value.details["fields"]
    )


def test_kahn_ignores_an_edge_whose_endpoint_is_outside_the_given_node_set():
    """`_kahn` is called with a pre-filtered node set (top-level nodes, or one
    scope's body); an edge reaching outside that set must not corrupt its
    in-degree bookkeeping for the nodes actually being ordered."""
    a, b, stray = uuid4(), uuid4(), uuid4()
    edges = [_edge(a, "out", b, "in"), _edge(a, "out", stray, "in")]
    predecessors, order, cyclic = _kahn([a, b], edges)
    assert order == [a, b]
    assert cyclic == set()
    assert predecessors[b] == {a}
