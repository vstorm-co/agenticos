"""The core, data and logic nodes' handlers and the expression language, unit by unit.

`tests/integration/test_workflow_core_nodes.py` runs whole graphs of them through
the dispatcher; what is left here is each refusal a graph could only reach by
bypassing validation, and the expression checks themselves.
"""

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.permissions import AuthContext
from app.services.workflow_execution import context
from app.workflows import _registry
from app.workflows.contracts.io import WorkflowOutputPayload
from app.workflows.contracts.results import Completed, Failed
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import _is_dynamic
from app.workflows.nodes import _expr
from app.workflows.nodes.core_input._handler import handle as core_input
from app.workflows.nodes.core_output._handler import handle as core_output
from app.workflows.nodes.data_map import DataMapConfig, DataMapInput, FieldMapping, coerce
from app.workflows.nodes.data_map._handler import handle as data_map
from app.workflows.nodes.logic_if import LogicIfConfig, LogicIfInput
from app.workflows.nodes.logic_if._handler import handle as logic_if
from app.workflows.nodes.logic_if._handler import routes
from app.workflows.nodes.logic_merge._handler import (
    LogicMergeConfig,
    LogicMergeOutput,
    branch_keys,
)
from app.workflows.nodes.logic_merge._handler import handle as logic_merge
from app.workflows.nodes.logic_split._handler import LogicSplitConfig, ports_for
from app.workflows.nodes.logic_split._handler import handle as logic_split

pytestmark = pytest.mark.anyio


def _dispatch(**overrides: Any) -> context.DispatchContext:
    values: dict[str, Any] = {
        "organization_id": uuid.uuid4(),
        "workflow_run_id": uuid.uuid4(),
        "node_run_id": uuid.uuid4(),
        "node_instance_id": uuid.uuid4(),
        "attempt_no": 1,
        "auth": AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner"),
        "resumed_agent_run_id": None,
    }
    values.update(overrides)
    return context.DispatchContext(**values)


class TestExpressions:
    def test_a_selection_with_allowed_functions_is_accepted(self):
        assert _expr.check("length(value.items) > `2`") == "length(value.items) > `2`"

    def test_an_expression_longer_than_the_limit_is_refused(self):
        with pytest.raises(_expr.ExpressionError, match="at most"):
            _expr.check("a" * (_expr.MAX_EXPRESSION_LENGTH + 1))

    def test_a_malformed_expression_is_refused_on_one_line(self):
        with pytest.raises(_expr.ExpressionError, match="does not parse") as refused:
            _expr.check("value.[")
        assert "\n" not in str(refused.value)

    @pytest.mark.parametrize("expression", ["map(&a, value)", "sort_by(value, &a)"])
    def test_a_function_taking_an_expression_reference_is_refused(self, expression: str):
        with pytest.raises(_expr.ExpressionError, match="not allowed"):
            _expr.check(expression)

    def test_a_function_handed_the_wrong_type_fails_evaluation(self):
        with pytest.raises(_expr.ExpressionError, match="could not be evaluated"):
            _expr.evaluate("length(value)", {"value": 42})

    @pytest.mark.parametrize("value", [None, False, "", [], {}])
    def test_empty_and_absent_values_are_false(self, value: Any):
        assert _expr.truthy(value) is False

    @pytest.mark.parametrize("value", [0, "no", [0], {"a": None}, True])
    def test_everything_else_is_true(self, value: Any):
        assert _expr.truthy(value) is True


class TestLogicIf:
    async def test_a_condition_that_fails_on_its_data_fails_the_node(self):
        result = await logic_if(LogicIfConfig(condition="length(value)"), LogicIfInput(value=42))
        assert isinstance(result, Failed) and result.error.code == "CONDITION_FAILED"

    async def test_an_unbound_value_is_read_as_null(self):
        result = await logic_if(LogicIfConfig(condition="value"), None)
        assert isinstance(result, Completed) and result.output.branch == "false"

    async def test_without_a_condition_the_node_fails_rather_than_choosing(self):
        result = await logic_if(None, None)
        assert isinstance(result, Failed) and result.error.code == "CONDITION_MISSING"

    def test_a_condition_is_checked_when_the_config_is_validated(self):
        with pytest.raises(ValidationError):
            LogicIfConfig(condition="map(&a, value)")

    @pytest.mark.parametrize("output", [None, {}, {"branch": "maybe"}])
    def test_an_output_naming_no_branch_routes_nowhere(self, output: dict[str, Any] | None):
        assert routes(output) == frozenset()

    def test_the_stored_branch_is_the_port_followed(self):
        assert routes({"branch": "true", "value": None}) == frozenset({"true"})


class TestDataMap:
    async def test_a_value_the_expression_does_not_find_takes_the_default(self):
        config = DataMapConfig(
            mappings=(
                FieldMapping(
                    target_field="n", source_path="source.n", coerce_to="integer", default="7"
                ),
                FieldMapping(target_field="none", source_path="source.missing"),
            )
        )
        result = await data_map(config, DataMapInput(source={}))
        assert isinstance(result, Completed)
        assert result.output.values == {"n": 7, "none": None}

    async def test_an_expression_that_fails_on_its_data_names_the_field(self):
        config = DataMapConfig(
            mappings=(FieldMapping(target_field="size", source_path="length(source)"),)
        )
        result = await data_map(config, DataMapInput(source=3))
        assert isinstance(result, Failed)
        assert result.error.code == "MAPPING_FAILED"
        assert result.error.details == {"target_field": "size"}

    async def test_without_mappings_the_node_fails(self):
        result = await data_map(None, None)
        assert isinstance(result, Failed) and result.error.code == "MAPPING_MISSING"

    def test_two_mappings_to_one_field_are_refused(self):
        with pytest.raises(ValidationError, match="own target field"):
            DataMapConfig(
                mappings=(
                    FieldMapping(target_field="a", source_path="source.x"),
                    FieldMapping(target_field="a", source_path="source.y"),
                )
            )

    @pytest.mark.parametrize(
        ("value", "to", "expected"),
        [
            (42, "string", "42"),
            ({"a": [1, "é"]}, "string", '{"a":[1,"é"]}'),
            ("12.5", "number", 12.5),
            ("true", "boolean", True),
            ({"x": 1}, "json", {"x": 1}),
        ],
    )
    def test_coercion_is_lax_like_a_form_field(self, value: Any, to: Any, expected: Any):
        assert coerce(value, to) == expected

    def test_a_reference_is_validated_as_one(self):
        file_id = uuid.uuid4()
        ref = {"kind": "file", "file_id": str(file_id), "content_type": "text/csv", "byte_size": 3}
        assert coerce(ref, "file_ref") == ref
        with pytest.raises(ValueError, match="table_ref"):
            coerce({"kind": "table"}, "table_ref")


class TestBoundaryNodes:
    async def test_input_hands_the_graph_the_frozen_payload_and_its_surface(self):
        with context.dispatching_as(_dispatch(run_input={"q": "hi"}, triggered_by="chat")):
            result = await core_input(None, None)
        assert isinstance(result, Completed)
        assert result.output.model_dump() == {"payload": {"q": "hi"}, "triggered_by": "chat"}

    async def test_output_with_nothing_bound_answers_with_nothing(self):
        with context.dispatching_as(_dispatch()) as scope:
            result = await core_output(None, None)
        assert isinstance(result, Completed)
        assert scope.run_output == WorkflowOutputPayload().model_dump(mode="json")

    async def test_output_records_what_it_was_given(self):
        with context.dispatching_as(_dispatch()) as scope:
            await core_output(None, WorkflowOutputPayload(text="done"))
        assert scope.run_output is not None and scope.run_output["text"] == "done"

    async def test_merge_passes_on_what_the_arriving_branch_produced(self):
        with context.dispatching_as(_dispatch(arrived_output={"values": {"a": 1}})):
            result = await logic_merge(None, None)
        assert isinstance(result, Completed)
        assert result.output.value == {"values": {"a": 1}}

    async def test_a_merge_with_no_config_passes_on_the_branch_that_ran(self):
        config = LogicMergeConfig.model_validate({})
        with context.dispatching_as(_dispatch(arrived_output={"x": 1})):
            result = await logic_merge(config, None)
        assert isinstance(result, Completed)
        assert result.output.model_dump() == {"value": {"x": 1}, "branches": None}

    async def test_a_merge_waiting_for_all_hands_on_every_branch_by_key(self):
        config = LogicMergeConfig(wait_for="all")
        arrived = {"a": {"text": "x"}, "b": None}
        with context.dispatching_as(
            _dispatch(arrived_output={"ignored": 1}, arrived_branches=arrived)
        ):
            result = await logic_merge(config, None)
        assert isinstance(result, Completed)
        assert result.output.model_dump() == {"value": None, "branches": arrived}

    def test_a_stored_merge_output_without_branches_still_parses(self):
        assert LogicMergeOutput.model_validate({"value": {"x": 1}}).branches is None

    async def test_a_split_leaves_by_every_branch(self):
        definition = _registry.get("logic.split", 1)
        config = LogicSplitConfig.model_validate({"branches": [{"name": "a"}, {"name": "b"}]})
        assert definition.routes is None
        assert [(p.id, p.kind) for p in ports_for(config)] == [
            ("in", "input"),
            ("a", "output"),
            ("b", "output"),
        ]
        assert [p.id for p in ports_for(None)] == ["in"]
        result = await logic_split(config, None)
        assert isinstance(result, Completed)
        assert result.output.model_dump() == {}

    def test_a_split_branch_may_not_be_called_in(self):
        with pytest.raises(ValidationError, match="already a port"):
            LogicSplitConfig.model_validate({"branches": [{"name": "in"}, {"name": "b"}]})

    @pytest.mark.parametrize(
        "branches",
        [[{"name": "a"}], [{"name": "a"}, {"name": "a"}], [{"name": "A"}, {"name": "b"}]],
    )
    def test_a_split_needs_two_distinct_branches(self, branches):
        with pytest.raises(ValidationError):
            LogicSplitConfig.model_validate({"branches": branches})

    def test_reporting_an_output_outside_a_dispatch_is_harmless(self):
        context.report_run_output({"text": "nobody is listening"})


def test_every_core_node_is_in_the_catalog():
    ids = {definition.id for definition in _registry.all_node_definitions()}
    assert {"core.input", "core.output", "data.map", "logic.if", "logic.merge"} <= ids


@pytest.mark.parametrize(
    ("annotation", "dynamic"),
    [
        (Any, True),
        (dict[str, Any], True),
        (dict[str, Any] | None, True),
        (dict[str, dict[str, Any] | None] | None, True),
        (dict[str, str], False),
        (dict, False),
        (str | int | None, False),
        (str, False),
    ],
)
def test_only_free_form_values_resolve_to_any_along_a_path(annotation: Any, dynamic: bool):
    assert _is_dynamic(annotation) is dynamic


def _graph_into_merge(
    *sources: tuple[str, str, str | None, str], config: dict[str, Any] | None = None
):
    """Nodes `(definition_id, label, ..)` each wired by a port into one merge."""
    nodes = [
        NodeInstance(
            id=uuid.uuid4(),
            definition_id=definition_id,
            definition_version=1,
            config={"branches": [{"name": "a"}, {"name": "b"}]}
            if definition_id == "logic.split"
            else {},
            layout=NodePosition(x=0, y=0),
            label=label,
        )
        for definition_id, label, _unused, _port in sources
    ]
    merge = NodeInstance(
        id=uuid.uuid4(),
        definition_id="logic.merge",
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
    )
    edges = tuple(
        Edge(
            id=uuid.uuid4(),
            source_node_id=node.id,
            source_port=port,
            target_node_id=merge.id,
            target_port="in",
        )
        for node, (_d, _l, _u, port) in zip(nodes, sources, strict=True)
    )
    return (
        WorkflowGraph(entry_node_id=nodes[0].id, nodes=(*nodes, merge), edges=edges),
        nodes,
        merge,
    )


def test_branch_keys_default_to_the_split_branch_then_the_step_name():
    graph, nodes, merge = _graph_into_merge(
        ("logic.split", "Splitter", None, "a"),
        ("logic.split", "Splitter 2", None, "b"),
        ("debug.echo", "Fetch the data", None, "out"),
        ("debug.echo", "2nd try", None, "out"),
        ("debug.echo", None, None, "out"),
        ("debug.echo", "x" * 40, None, "out"),
        ("no.such.step", None, None, "out"),
    )
    keys = branch_keys(graph, merge)
    assert list(keys.values()) == [
        "a",
        "b",
        "fetch_the_data",
        "b_2nd_try",
        "echo",
        "x" * 32,
        "no_such_step",
    ]


def test_a_stored_branch_key_wins_and_a_malformed_one_is_ignored():
    graph, nodes, merge = _graph_into_merge(
        ("debug.echo", "First", None, "out"), ("debug.echo", "Second", None, "out")
    )
    stored = {
        "branch_keys": [
            {"source_node_id": str(nodes[0].id), "source_port": "out", "key": "mine"},
            "not a dict",
            {"source_node_id": str(nodes[1].id), "source_port": "out", "key": 3},
        ]
    }
    keyed = merge.model_copy(update={"config": stored})
    assert list(branch_keys(graph, keyed).values()) == ["mine", "second"]
    unreadable = merge.model_copy(update={"config": {"branch_keys": "nope"}})
    assert list(branch_keys(graph, unreadable).values()) == ["first", "second"]


def test_branch_keys_count_a_wire_once_and_skip_an_edge_from_nowhere():
    graph, nodes, merge = _graph_into_merge(("debug.echo", "First", None, "out"))
    again = graph.edges[0].model_copy(update={"id": uuid.uuid4()})
    ghost = graph.edges[0].model_copy(update={"id": uuid.uuid4(), "source_node_id": uuid.uuid4()})
    graph = graph.model_copy(update={"edges": (*graph.edges, again, ghost)})
    assert branch_keys(graph, merge) == {(nodes[0].id, "out"): "first"}
