"""Error routing and loop nodes, their policies and the rules that publish them (#1790).

What runs is `tests/integration/test_workflow_error_foreach.py`; this is what
needs no database: each node's handler on its own, the retry schedule, which
failures no fallback may bypass, a timeout's verdict, and every refusal
publishing makes before a graph with a loop or an error route can run.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.core.exceptions import AuthorizationError, NotFoundError, PaymentRequiredError
from app.core.permissions import AuthContext, OrgRoleName
from app.services.workflow_execution import context, dispatcher
from app.services.workflow_execution.errors import workflow_error
from app.workflows import _registry
from app.workflows.contracts.definition import RetryGuarantee
from app.workflows.contracts.io import Binding, NodeOutputRef
from app.workflows.contracts.policy import NodePolicy, RetryPolicy
from app.workflows.contracts.results import Completed, Failed, Uncertain
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import validate_graph
from app.workflows.nodes.control_foreach import ForeachInput, ForeachManifest
from app.workflows.nodes.control_foreach._handler import handle as foreach_handle
from app.workflows.nodes.control_foreach._handler import routes as foreach_routes
from app.workflows.nodes.error_handle import ErrorHandleConfig, HandledError
from app.workflows.nodes.error_handle._handler import handle as error_handle
from app.workflows.nodes.error_handle._handler import ports_for, routes
from app.workflows.nodes.error_raise import ErrorRaiseConfig
from app.workflows.nodes.error_raise._handler import handle as error_raise
from app.workflows.nodes.loop_yield import LoopYieldInput, LoopYieldOutput
from app.workflows.nodes.loop_yield._handler import handle as loop_yield

pytestmark = pytest.mark.anyio


def _dispatching(arrived: dict[str, Any] | None) -> context.DispatchContext:
    return context.DispatchContext(
        organization_id=uuid.uuid4(),
        workflow_run_id=uuid.uuid4(),
        node_run_id=uuid.uuid4(),
        node_instance_id=uuid.uuid4(),
        attempt_no=1,
        auth=MagicMock(),
        resumed_agent_run_id=None,
        arrived_output=arrived,
    )


# error.raise


async def test_error_raise_fails_with_exactly_the_configured_error():
    config = ErrorRaiseConfig(code="ORDER_REJECTED", message="Too big", details={"id": 1})
    result = await error_raise(config, None)
    assert isinstance(result, Failed)
    assert result.error.model_dump() == {
        "code": "ORDER_REJECTED",
        "message": "Too big",
        "details": {"id": 1},
        "retryable": False,
        "bypassable": True,
    }


async def test_error_raise_without_a_config_names_that_it_has_none():
    result = await error_raise(None, None)
    assert isinstance(result, Failed) and result.error.code == "ERROR_NOT_CONFIGURED"


@pytest.mark.parametrize(
    "config",
    [
        {"code": "lower_case", "message": "x"},
        {"code": "OK", "message": ""},
        {"code": "OK", "message": "x", "details": {"blob": "x" * 20_000}},
    ],
    ids=["code-pattern", "empty-message", "oversized-details"],
)
def test_error_raise_refuses_an_error_it_could_not_state_safely(config: dict[str, Any]):
    with pytest.raises(ValidationError):
        ErrorRaiseConfig.model_validate(config)


# error.handle


_CONFIG = ErrorHandleConfig.model_validate(
    {
        "branches": [
            {"name": "missing", "code": "NOT_FOUND"},
            {"name": "transient", "retryable": True},
            {"name": "both", "code": "X", "retryable": False},
        ]
    }
)


@pytest.mark.parametrize(
    ("error", "branch"),
    [
        ({"code": "NOT_FOUND", "message": "m"}, "missing"),
        ({"code": "TIMEOUT", "message": "m", "retryable": True}, "transient"),
        ({"code": "X", "message": "m"}, "both"),
        ({"code": "OTHER", "message": "m"}, "default"),
    ],
)
async def test_error_handle_takes_the_first_branch_the_error_matches(
    error: dict[str, Any], branch: str
):
    with context.dispatching_as(_dispatching(error)):
        result = await error_handle(_CONFIG, None)
    assert isinstance(result, Completed)
    assert isinstance(result.output, HandledError)
    assert result.output.branch == branch and result.output.code == error["code"]
    assert routes(result.output.model_dump()) == frozenset({branch})


async def test_error_handle_reached_without_an_error_fails_saying_so():
    with context.dispatching_as(_dispatching({"value": 1})):
        result = await error_handle(ErrorHandleConfig(), None)
    assert isinstance(result, Failed) and result.error.code == "NO_ERROR_TO_HANDLE"


def test_error_handle_ports_are_its_branches_and_default():
    assert [port.id for port in ports_for(_CONFIG)] == [
        "in",
        "default",
        "missing",
        "transient",
        "both",
    ]
    assert [port.id for port in ports_for(None)] == ["in", "default"]
    assert routes(None) == frozenset()


@pytest.mark.parametrize(
    "branches",
    [[{"name": "a"}, {"name": "a"}], [{"name": "default"}]],
    ids=["duplicate", "reserved"],
)
def test_error_handle_refuses_branch_names_that_would_collide(branches: list[dict[str, Any]]):
    with pytest.raises(ValidationError):
        ErrorHandleConfig.model_validate({"branches": branches})


# control.foreach and loop.yield


async def test_foreach_freezes_the_list_it_is_given():
    result = await foreach_handle(None, ForeachInput(items=[1, {"a": 2}]))
    assert isinstance(result, Completed)
    assert result.output == ForeachManifest(items=[1, {"a": 2}])
    assert foreach_routes(None) == frozenset({"done"})


async def test_foreach_with_nothing_bound_iterates_nothing():
    result = await foreach_handle(None, None)
    assert isinstance(result, Completed) and result.output == ForeachManifest(items=[])


async def test_foreach_refuses_a_list_over_its_size_ceiling(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.core.config.settings.WORKFLOW_FOREACH_MAX_MANIFEST_BYTES", 10)
    result = await foreach_handle(None, ForeachInput(items=["a long string"]))
    assert isinstance(result, Failed) and result.error.code == "FOREACH_LIST_TOO_LARGE"
    assert result.error.details["limit"] == 10


async def test_loop_yield_hands_back_its_bound_value():
    result = await loop_yield(None, LoopYieldInput(value={"a": 1}))
    assert isinstance(result, Completed) and result.output == LoopYieldOutput(value={"a": 1})
    unbound = await loop_yield(None, None)
    assert isinstance(unbound, Completed) and unbound.output == LoopYieldOutput(value=None)


# Retry schedule, bypassability, timeouts


def test_a_retry_schedule_is_fixed_or_doubles_up_to_its_ceiling():
    fixed = RetryPolicy(max_attempts=3, backoff="fixed", base_delay_seconds=4)
    doubling = RetryPolicy(max_attempts=5, base_delay_seconds=2, max_delay_seconds=5)
    assert [fixed.delay_seconds(n) for n in (1, 2, 3)] == [4, 4, 4]
    assert [doubling.delay_seconds(n) for n in (0, 1, 2, 3)] == [2, 2, 4, 5]


def test_a_retry_ceiling_below_its_base_is_refused():
    with pytest.raises(ValidationError, match="max_delay_seconds"):
        RetryPolicy(max_attempts=2, base_delay_seconds=10, max_delay_seconds=1)


@pytest.mark.security
@pytest.mark.parametrize(
    ("exc", "bypassable"),
    [
        (AuthorizationError(message="No"), False),
        (PaymentRequiredError(message="Spent"), False),
        (NotFoundError(message="Gone"), True),
    ],
)
def test_revoked_access_and_spent_budgets_cannot_be_routed_around(exc, bypassable: bool):
    error = workflow_error(exc, retryable=True)
    assert error.bypassable is bypassable
    assert error.retryable is True and error.code == exc.code


def _begun(effect: str, guarantee: RetryGuarantee) -> dispatcher.BegunAttempt:
    definition = MagicMock(effect_kind=effect)
    return dispatcher.BegunAttempt(
        workflow_run_id=uuid.uuid4(),
        node_run_id=uuid.uuid4(),
        node_instance_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        attempt_id=uuid.uuid4(),
        attempt_no=1,
        handler_config=None,
        handler_input=None,
        definition=definition,
        handler=MagicMock(),
        dispatch_context=_dispatching(None),
        timeout_seconds=1.5,
        retry_guarantee=guarantee,
        dispatch_token=uuid.uuid4(),
    )


@pytest.mark.parametrize(
    ("effect", "guarantee", "verdict"),
    [
        ("read", "at_least_once", Failed),
        ("write", "idempotent", Failed),
        ("write", "at_least_once", Uncertain),
    ],
)
def test_a_timeout_is_a_retryable_failure_unless_a_write_may_have_landed(
    effect: str, guarantee: RetryGuarantee, verdict: type
):
    result = dispatcher._timed_out(_begun(effect, guarantee))
    assert isinstance(result, verdict)
    if isinstance(result, Failed):
        assert result.error.code == "NODE_TIMEOUT" and result.error.retryable


# Publishing


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)


def _node(definition_id: str, config: dict[str, Any] | None = None, **extra: Any) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
        **extra,
    )


def _edge(source: NodeInstance, target: NodeInstance, port: str = "out") -> Edge:
    return Edge(
        id=uuid.uuid4(),
        source_node_id=source.id,
        source_port=port,
        target_node_id=target.id,
        target_port="in",
    )


def _bind(target: NodeInstance, field: str, source: NodeInstance, port: str, *path: str) -> Binding:
    return Binding(
        target_node_id=target.id,
        target_field=field,
        source=NodeOutputRef(node_id=source.id, port=port, field_path=path),
    )


_MAP = {"mappings": [{"target_field": "n", "source_path": "source", "coerce_to": "number"}]}
ROUTE = NodePolicy(on_error="route")


async def _problems(graph: WorkflowGraph) -> list[str]:
    try:
        await validate_graph(MagicMock(), _ctx(), graph)
    except GraphValidationError as exc:
        return [problem["message"] for problem in exc.details["fields"]]
    return []


class _LoopGraph:
    """entry -> loop -body-> item -> yield ; loop -done-> out, and extras."""

    def __init__(self) -> None:
        self.entry = _node("core.input")
        self.loop = _node("control.foreach")
        self.item = _node("loop.item")
        self.yield_ = _node("loop.yield")
        self.out = _node("core.output")

    def graph(
        self,
        *,
        nodes: tuple[NodeInstance, ...] = (),
        edges: tuple[Edge, ...] | None = None,
        bindings: tuple[Binding, ...] = (),
    ) -> WorkflowGraph:
        return WorkflowGraph(
            entry_node_id=self.entry.id,
            nodes=(self.entry, self.loop, self.item, self.yield_, self.out, *nodes),
            edges=edges
            if edges is not None
            else (
                _edge(self.entry, self.loop),
                _edge(self.loop, self.item, "body"),
                _edge(self.item, self.yield_),
                _edge(self.loop, self.out, "done"),
            ),
            bindings=(_bind(self.loop, "items", self.entry, "out", "payload", "xs"), *bindings),
        )


async def test_a_well_formed_loop_publishes_and_its_body_may_read_what_ran_before_it():
    shape = _LoopGraph()
    graph = shape.graph(bindings=(_bind(shape.yield_, "value", shape.entry, "out", "payload"),))
    assert await _problems(graph) == []


async def test_a_body_that_reads_the_loop_it_runs_inside_is_refused():
    shape = _LoopGraph()
    graph = shape.graph(bindings=(_bind(shape.yield_, "value", shape.loop, "done", "results"),))
    assert any("reads the loop it runs inside" in p for p in await _problems(graph))


async def test_a_step_after_the_loop_cannot_read_into_its_body():
    shape = _LoopGraph()
    graph = shape.graph(bindings=(_bind(shape.out, "text", shape.item, "out", "item"),))
    assert any("crosses a scope boundary" in p for p in await _problems(graph))


async def test_loop_steps_outside_a_loop_are_refused():
    entry, item = _node("core.input"), _node("loop.item")
    graph = WorkflowGraph(entry_node_id=entry.id, nodes=(entry, item), edges=(_edge(entry, item),))
    assert any("only works inside a for-each" in p for p in await _problems(graph))


async def test_a_loop_body_needs_one_item_step_and_one_result_step():
    shape = _LoopGraph()
    other = _node("data.map", _MAP)
    no_item = shape.graph(
        nodes=(other,),
        edges=(
            _edge(shape.entry, shape.loop),
            _edge(shape.loop, other, "body"),
            _edge(other, shape.yield_),
            _edge(shape.loop, shape.out, "done"),
        ),
    )
    problems = await _problems(no_item)
    assert any("start at exactly one loop item" in p for p in problems)

    second_yield = _node("loop.yield")
    graph = WorkflowGraph(
        entry_node_id=shape.entry.id,
        nodes=(shape.entry, shape.loop, shape.item, shape.out, second_yield),
        edges=(
            _edge(shape.entry, shape.loop),
            _edge(shape.loop, shape.item, "body"),
            _edge(shape.loop, shape.out, "done"),
        ),
        bindings=(_bind(shape.loop, "items", shape.entry, "out", "payload", "xs"),),
    )
    assert any("end at exactly one loop result" in p for p in await _problems(graph))


async def test_a_loop_cannot_continue_into_its_own_body():
    shape = _LoopGraph()
    after = _node("data.map", _MAP)
    graph = shape.graph(
        nodes=(after,),
        edges=(
            _edge(shape.entry, shape.loop),
            _edge(shape.loop, shape.item, "body"),
            _edge(shape.item, after),
            _edge(after, shape.yield_),
            _edge(shape.loop, after, "done"),
        ),
    )
    assert any("continues through done" in p for p in await _problems(graph))


async def test_loops_nest_only_as_deep_as_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.core.config.settings.WORKFLOW_FOREACH_MAX_DEPTH", 1)
    shape = _LoopGraph()
    inner, inner_item, inner_yield = (
        _node("control.foreach"),
        _node("loop.item"),
        _node("loop.yield"),
    )
    graph = shape.graph(
        nodes=(inner, inner_item, inner_yield),
        edges=(
            _edge(shape.entry, shape.loop),
            _edge(shape.loop, shape.item, "body"),
            _edge(shape.item, inner),
            _edge(inner, inner_item, "body"),
            _edge(inner_item, inner_yield),
            _edge(inner, shape.yield_, "done"),
            _edge(shape.loop, shape.out, "done"),
        ),
        bindings=(_bind(inner, "items", shape.item, "out", "item"),),
    )
    assert any("nest at most 1 deep" in p for p in await _problems(graph))


def _routed_graph(
    *,
    handle_default: bool = True,
    error_edge: bool = True,
    bindings: Callable[[dict[str, NodeInstance]], tuple[Binding, ...]] = lambda _: (),
) -> WorkflowGraph:
    entry = _node("core.input")
    parse = _node("data.map", _MAP, policy=ROUTE)
    ok, handle, fallback = _node("core.output"), _node("error.handle"), _node("core.output")
    edges = [_edge(entry, parse), _edge(parse, ok)]
    if error_edge:
        edges.append(_edge(parse, handle, "error"))
    if handle_default:
        edges.append(_edge(handle, fallback, "default"))
    nodes = {"entry": entry, "parse": parse, "ok": ok, "handle": handle, "fallback": fallback}
    return WorkflowGraph(
        entry_node_id=entry.id,
        nodes=tuple(nodes.values()),
        edges=tuple(edges),
        bindings=(_bind(parse, "source", entry, "out", "payload"), *bindings(nodes)),
    )


async def test_a_routed_step_with_a_handled_error_publishes():
    assert await _problems(_routed_graph()) == []


async def test_an_error_handler_whose_default_leads_nowhere_is_refused():
    problems = await _problems(_routed_graph(handle_default=False))
    assert any("default branch must lead somewhere" in p for p in problems)


async def test_a_step_routing_errors_to_nowhere_is_refused():
    problems = await _problems(_routed_graph(error_edge=False))
    assert any("error port leads nowhere" in p for p in problems)


async def test_an_error_port_exists_only_on_a_step_that_routes_its_errors():
    entry, plain, handle, out = (
        _node("core.input"),
        _node("data.map", _MAP),
        _node("error.handle"),
        _node("core.output"),
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, plain, handle, out),
        edges=(_edge(entry, plain), _edge(plain, handle, "error"), _edge(handle, out, "default")),
        bindings=(_bind(plain, "source", entry, "out", "payload"),),
    )
    assert any("source port does not exist" in p for p in await _problems(graph))


async def test_the_error_path_cannot_read_the_output_and_the_success_path_cannot_read_the_error():
    graph = _routed_graph(
        bindings=lambda nodes: (
            _bind(nodes["fallback"], "text", nodes["parse"], "out", "values"),
            _bind(nodes["ok"], "text", nodes["parse"], "error", "code"),
        )
    )
    problems = await _problems(graph)
    assert any("on its error path, where there is none" in p for p in problems)
    assert any("error on a path where it may have succeeded" in p for p in problems)


async def test_a_step_whose_call_is_not_safe_to_repeat_cannot_retry():
    entry = _node("core.input")
    agent = _node(
        "agent.run",
        {"agent": {"agent_id": str(uuid.uuid4()), "version_id": str(uuid.uuid4())}},
        policy=NodePolicy(retry=RetryPolicy(max_attempts=3)),
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id, nodes=(entry, agent), edges=(_edge(entry, agent),)
    )
    # The pinned agent itself is the author's to run; only the policy is at issue.
    with patch("app.workflows.nodes.agent_run._handler.AgentRegistryService") as registry:
        registry.return_value.get_pinned_spec = AsyncMock()
        problems = await _problems(graph)
    assert any("cannot retry" in p for p in problems)


async def test_a_step_that_never_runs_takes_no_policy():
    shape = _LoopGraph()
    item = _node("loop.item", policy=NodePolicy(timeout_seconds=1))
    graph = shape.graph(
        nodes=(item,),
        edges=(
            _edge(shape.entry, shape.loop),
            _edge(shape.loop, item, "body"),
            _edge(item, shape.yield_),
            _edge(shape.loop, shape.out, "done"),
        ),
    )
    graph = graph.model_copy(
        update={"nodes": tuple(node for node in graph.nodes if node.id != shape.item.id)}
    )
    assert any("takes no policy" in p for p in await _problems(graph))


def test_the_catalog_marks_the_steps_that_exist_only_inside_a_loop():
    only_in_loops = {
        definition.id
        for definition in _registry.all_node_definitions()
        if definition.loop_body_only
    }
    assert only_in_loops == {"loop.item", "loop.yield"}
