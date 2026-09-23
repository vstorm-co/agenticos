"""`app.services.workflow_execution.dispatcher`: claim, begin, call, settle, advance.

The repository is mocked at the database edge (`test_workflow_registry_service.py`'s
bargain); the graph/definition/binding objects are real, since they are plain
pydantic/dataclass values with no I/O, and resolving them correctly is the
thing most worth proving wrong.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import ANY, AsyncMock, MagicMock, create_autospec, patch

import pytest
from pydantic import BaseModel

from app.db.models.workflow import WorkflowVersion
from app.db.models.workflow_run import (
    DispatchOutbox,
    DispatchOutboxStatus,
    NodeAttempt,
    NodeAttemptStatus,
    NodeRun,
    NodeRunStatus,
    RetryGuarantee,
    WaitingReason,
    WorkflowRun,
    WorkflowRunMode,
    WorkflowRunStatus,
)
from app.repositories import workflow_run as workflow_run_repo_module
from app.services.workflow_execution import context, dispatcher
from app.workflows._registry import REGISTRY, register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.contracts.io import Binding, FileRef, LiteralValue, NodeOutputRef, TableIORef
from app.workflows.contracts.results import (
    Completed,
    Failed,
    NodeResult,
    Uncertain,
    Waiting,
    WorkflowError,
)
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph

pytestmark = pytest.mark.anyio

DISPATCHER_PATH = "app.services.workflow_execution.dispatcher"


@pytest.fixture(autouse=True)
def _no_member_by_default():
    """Most tests here do not care about the acting member's role - only
    `TestAuthContextFor` does, and its own `with patch(...)` blocks override
    this for their duration."""
    with patch(f"{DISPATCHER_PATH}.member_repo.get_active", new=AsyncMock(return_value=None)):
        yield


class _EchoConfig(BaseModel):
    message: str = ""


class _EchoOutput(BaseModel):
    echoed: str


async def _pure_handler(config: object, node_input: object) -> NodeResult:
    message = getattr(node_input, "message", None) or getattr(config, "message", "")
    return Completed[_EchoOutput](output=_EchoOutput(echoed=message))


@pytest.fixture
def test_node() -> str:
    """A real, registered node definition with a controllable handler,
    cleaned up whether the test passes or not."""
    node_id = f"test.dispatcher-{uuid.uuid4().hex[:8]}"
    register(
        NodeDefinition(
            id=node_id,
            version=1,
            name="Test node",
            category="test",
            description="Registered only for dispatcher tests.",
            kind="action",
            config_schema=_EchoConfig,
            input_schema=_EchoConfig,
            output_schema=_EchoOutput,
            ports=(
                Port(id="in", label="In", kind="input", schema=_EchoConfig),
                Port(id="out", label="Out", kind="output", schema=_EchoOutput),
            ),
            effect_kind="pure",
            retry_guarantee="idempotent",
            handler=_pure_handler,
        )
    )
    yield node_id
    REGISTRY.pop(node_id, None)


def _node_instance(node_id: str, *, config: dict | None = None) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=node_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
    )


def _graph(
    *nodes: NodeInstance, edges: tuple[Edge, ...] = (), bindings: tuple[Binding, ...] = ()
) -> WorkflowGraph:
    return WorkflowGraph(entry_node_id=nodes[0].id, nodes=nodes, edges=edges, bindings=bindings)


def _org() -> uuid.UUID:
    return uuid.uuid4()


def _run(**overrides: object) -> WorkflowRun:
    org_id = overrides.pop("organization_id", _org())
    run_id = overrides.pop("id", uuid.uuid4())
    defaults: dict[str, object] = {
        "id": run_id,
        "organization_id": org_id,
        "workflow_id": uuid.uuid4(),
        "workflow_version_id": uuid.uuid4(),
        "draft_graph_snapshot": None,
        "mode": WorkflowRunMode.REAL.value,
        "status": WorkflowRunStatus.RUNNING.value,
        "triggered_by": "api",
        "execution_principal_user_id": uuid.uuid4(),
        "budget_limit": None,
        "spent_cost": Decimal("0"),
        "cost_is_partial": False,
        "deadline_at": None,
        "next_event_seq": 0,
        "paused_reason": None,
        "error": None,
        "root_run_id": run_id,
        "causation_run_id": None,
        "visited_trigger_ids": [],
        "depth": 0,
        "started_at": datetime.now(UTC),
        "ended_at": None,
    }
    defaults.update(overrides)
    return WorkflowRun(**defaults)


def _node_run(
    *, workflow_run_id: uuid.UUID, node_instance_id: uuid.UUID, **overrides: object
) -> NodeRun:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "workflow_run_id": workflow_run_id,
        "node_instance_id": node_instance_id,
        "scope_path": [],
        "status": NodeRunStatus.PENDING.value,
        "waiting_reason": None,
        "resume_token": None,
        "waiting_agent_run_id": None,
        "started_at": None,
        "ended_at": None,
    }
    defaults.update(overrides)
    return NodeRun(**defaults)


def _attempt(*, node_run_id: uuid.UUID, **overrides: object) -> NodeAttempt:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "node_run_id": node_run_id,
        "attempt_no": 1,
        "idempotency_key": "key",
        "retry_guarantee": RetryGuarantee.IDEMPOTENT.value,
        "status": NodeAttemptStatus.IN_FLIGHT.value,
        "result": None,
        "cost": Decimal("0"),
        "cost_is_partial": False,
        "started_at": datetime.now(UTC),
        "ended_at": None,
    }
    defaults.update(overrides)
    return NodeAttempt(**defaults)


def _outbox(*, node_run_id: uuid.UUID, **overrides: object) -> DispatchOutbox:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "workflow_run_id": uuid.uuid4(),
        "node_run_id": node_run_id,
        "available_at": datetime.now(UTC),
        "claimed_by": uuid.uuid4(),
        "lease_expires_at": datetime.now(UTC) + timedelta(seconds=60),
        "status": DispatchOutboxStatus.CLAIMED.value,
    }
    defaults.update(overrides)
    return DispatchOutbox(**defaults)


class TestIdempotencyKey:
    def test_is_stable_for_the_same_inputs(self):
        org, run, node = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        first = dispatcher.idempotency_key(
            organization_id=org, workflow_run_id=run, node_instance_id=node, scope_path=[]
        )
        second = dispatcher.idempotency_key(
            organization_id=org, workflow_run_id=run, node_instance_id=node, scope_path=[]
        )
        assert first == second

    def test_differs_across_scope_paths(self):
        org, run, node = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        a = dispatcher.idempotency_key(
            organization_id=org,
            workflow_run_id=run,
            node_instance_id=node,
            scope_path=[{"loop_node_id": "x", "index": 0}],
        )
        b = dispatcher.idempotency_key(
            organization_id=org,
            workflow_run_id=run,
            node_instance_id=node,
            scope_path=[{"loop_node_id": "x", "index": 1}],
        )
        assert a != b


class TestFieldOwner:
    def test_a_field_on_the_input_schema_is_input(self, test_node: str):
        definition = REGISTRY[test_node][1]
        assert dispatcher._field_owner(definition, "message") == "input"

    def test_an_unknown_field_owns_nothing(self, test_node: str):
        definition = REGISTRY[test_node][1]
        assert dispatcher._field_owner(definition, "nonexistent") is None


class TestResolveSource:
    def test_a_literal_resolves_to_its_own_value(self):
        assert dispatcher._resolve_source(LiteralValue(value="hi"), {}) == "hi"

    def test_a_node_output_ref_walks_its_field_path(self):
        source_id = uuid.uuid4()
        outputs = {source_id: {"echoed": "hi", "nested": {"deep": "value"}}}
        ref = NodeOutputRef(node_id=source_id, port="out", field_path=("nested", "deep"))
        assert dispatcher._resolve_source(ref, outputs) == "value"

    def test_a_node_output_ref_to_a_source_with_no_output_yet_is_none(self):
        ref = NodeOutputRef(node_id=uuid.uuid4(), port="out")
        assert dispatcher._resolve_source(ref, {}) is None

    def test_a_file_ref_resolves_to_its_own_dict_form(self):
        file_id = uuid.uuid4()
        ref = FileRef(file_id=file_id, content_type="text/plain", byte_size=10)
        resolved = dispatcher._resolve_source(ref, {})
        assert resolved == {
            "kind": "file",
            "file_id": str(file_id),
            "content_type": "text/plain",
            "byte_size": 10,
        }

    def test_a_table_ref_resolves_to_its_own_dict_form(self):
        table_id = uuid.uuid4()
        ref = TableIORef(table_id=table_id, schema_version=1)
        resolved = dispatcher._resolve_source(ref, {})
        assert resolved["table_id"] == str(table_id)


class TestResolveIO:
    def test_no_bindings_means_no_input_object_at_all(self, test_node: str):
        definition = REGISTRY[test_node][1]
        node = _node_instance(test_node, config={"message": "configured"})
        graph = _graph(node)
        config_obj, input_obj = dispatcher._resolve_io(graph, node, definition, outputs={})
        assert config_obj.message == "configured"
        assert input_obj is None

    def test_an_input_binding_produces_an_input_object(self, test_node: str):
        definition = REGISTRY[test_node][1]
        node = _node_instance(test_node)
        binding = Binding(
            target_node_id=node.id, target_field="message", source=LiteralValue(value="bound")
        )
        graph = _graph(node, bindings=(binding,))
        _config_obj, input_obj = dispatcher._resolve_io(graph, node, definition, outputs={})
        assert input_obj.message == "bound"

    def test_a_config_binding_overrides_the_nodes_own_config(self, test_node: str):
        definition = REGISTRY[test_node][1]
        node = _node_instance(test_node, config={"message": "original"})
        # `message` exists on both schemas here; input is checked first by
        # `_field_owner`'s own precedence, so bind a *second*, config-only
        # scenario is not representable with this fixture's shared schema -
        # this instead proves the base config survives when nothing binds it.
        graph = _graph(node)
        config_obj, _input_obj = dispatcher._resolve_io(graph, node, definition, outputs={})
        assert config_obj.message == "original"


class TestResolveGraph:
    async def test_real_mode_reads_the_published_version(self, test_node: str):
        node = _node_instance(test_node)
        graph = _graph(node)
        run = _run(mode=WorkflowRunMode.REAL.value, workflow_version_id=uuid.uuid4())
        version = WorkflowVersion(
            id=run.workflow_version_id,
            workflow_id=run.workflow_id,
            organization_id=run.organization_id,
            version=1,
            graph=graph.model_dump(mode="json"),
        )
        with patch(
            f"{DISPATCHER_PATH}.workflow_repo.get_version", new=AsyncMock(return_value=version)
        ):
            resolved = await dispatcher.resolve_graph(object(), run)
        assert resolved.entry_node_id == graph.entry_node_id

    async def test_real_mode_with_a_version_that_no_longer_resolves_raises(self):
        run = _run(mode=WorkflowRunMode.REAL.value, workflow_version_id=uuid.uuid4())
        with (
            patch(f"{DISPATCHER_PATH}.workflow_repo.get_version", new=AsyncMock(return_value=None)),
            pytest.raises(RuntimeError),
        ):
            await dispatcher.resolve_graph(object(), run)

    async def test_test_mode_reads_the_draft_snapshot(self, test_node: str):
        node = _node_instance(test_node)
        graph = _graph(node)
        run = _run(
            mode=WorkflowRunMode.TEST.value,
            workflow_version_id=None,
            draft_graph_snapshot=graph.model_dump(mode="json"),
        )
        resolved = await dispatcher.resolve_graph(object(), run)
        assert resolved.entry_node_id == graph.entry_node_id

    async def test_test_mode_with_neither_snapshot_raises(self):
        run = _run(
            mode=WorkflowRunMode.TEST.value, workflow_version_id=None, draft_graph_snapshot=None
        )
        with pytest.raises(RuntimeError):
            await dispatcher.resolve_graph(object(), run)


class TestAuthContextFor:
    async def test_no_principal_gets_no_subject(self):
        run = _run(execution_principal_user_id=None)
        auth = await dispatcher._auth_context_for(object(), run)
        assert auth.user_id is None
        assert auth.role == ""

    async def test_an_active_member_gets_their_current_role(self):
        run = _run()
        member = MagicMock(role="admin")
        with patch(f"{DISPATCHER_PATH}.member_repo.get_active", new=AsyncMock(return_value=member)):
            auth = await dispatcher._auth_context_for(object(), run)
        assert auth.role == "admin"
        assert auth.user_id == run.execution_principal_user_id

    async def test_a_principal_no_longer_an_active_member_gets_no_role(self):
        run = _run()
        with patch(f"{DISPATCHER_PATH}.member_repo.get_active", new=AsyncMock(return_value=None)):
            auth = await dispatcher._auth_context_for(object(), run)
        assert auth.role == ""
        assert auth.user_id == run.execution_principal_user_id


class TestClaim:
    async def test_delegates_to_the_repository_claim(self):
        node_run_id = uuid.uuid4()
        outbox = _outbox(node_run_id=node_run_id)
        with patch(
            f"{DISPATCHER_PATH}.workflow_run_repo.claim_outbox", new=AsyncMock(return_value=outbox)
        ) as claim_outbox:
            result = await dispatcher.claim(object(), node_run_id=node_run_id)
        assert result is outbox
        claim_outbox.assert_awaited_once()
        assert claim_outbox.await_args.kwargs["node_run_id"] == node_run_id

    async def test_nothing_claimable_is_none(self):
        with patch(
            f"{DISPATCHER_PATH}.workflow_run_repo.claim_outbox", new=AsyncMock(return_value=None)
        ):
            result = await dispatcher.claim(object(), node_run_id=uuid.uuid4())
        assert result is None


@pytest.fixture
def repo():
    """`workflow_run_repo`, autospecced so every function is the right kind of
    mock (async where the real one is) and a typo'd attribute fails loudly."""
    mocked = create_autospec(workflow_run_repo_module, instance=False)
    with patch(f"{DISPATCHER_PATH}.workflow_run_repo", new=mocked):
        yield mocked


@pytest.fixture
def event_log():
    with patch(f"{DISPATCHER_PATH}.events.append", new=AsyncMock()) as appended:
        yield appended


def _test_mode_run(node_id: str, **overrides: object) -> tuple[WorkflowRun, NodeInstance]:
    node = _node_instance(node_id, config={"message": "hi"})
    graph = _graph(node)
    run = _run(
        mode=WorkflowRunMode.TEST.value,
        workflow_version_id=None,
        draft_graph_snapshot=graph.model_dump(mode="json"),
        **overrides,
    )
    return run, node


class TestBeginAttemptShortCircuits:
    async def test_a_missing_run_or_node_run_returns_none_and_does_nothing_else(
        self, repo, event_log
    ):
        repo.get_run_by_id_for_update.return_value = None
        repo.get_node_run_by_id_for_update.return_value = None
        result = await dispatcher.begin_attempt(
            object(), workflow_run_id=uuid.uuid4(), node_run_id=uuid.uuid4()
        )
        assert result is None
        repo.create_attempt.assert_not_called()
        event_log.assert_not_called()

    async def test_a_terminal_run_closes_the_outbox_row_and_creates_nothing(
        self, repo, event_log, test_node
    ):
        run, node = _test_mode_run(test_node, status=WorkflowRunStatus.SUCCEEDED.value)
        node_run = _node_run(workflow_run_id=run.id, node_instance_id=node.id)
        outbox = _outbox(node_run_id=node_run.id)
        repo.get_run_by_id_for_update.return_value = run
        repo.get_node_run_by_id_for_update.return_value = node_run
        repo.get_outbox_for_node_run.return_value = outbox

        result = await dispatcher.begin_attempt(
            object(), workflow_run_id=run.id, node_run_id=node_run.id
        )

        assert result is None
        repo.mark_outbox_done.assert_awaited_once_with(ANY, outbox=outbox)
        repo.create_attempt.assert_not_called()

    async def test_a_cancelled_node_run_closes_the_outbox_row_and_creates_nothing(
        self, repo, event_log, test_node
    ):
        run, node = _test_mode_run(test_node)
        node_run = _node_run(
            workflow_run_id=run.id, node_instance_id=node.id, status=NodeRunStatus.CANCELLED.value
        )
        repo.get_run_by_id_for_update.return_value = run
        repo.get_node_run_by_id_for_update.return_value = node_run
        repo.get_outbox_for_node_run.return_value = None

        result = await dispatcher.begin_attempt(
            object(), workflow_run_id=run.id, node_run_id=node_run.id
        )

        assert result is None
        repo.create_attempt.assert_not_called()

    async def test_past_deadline_fails_the_run_and_creates_no_attempt(
        self, repo, event_log, test_node
    ):
        run, node = _test_mode_run(test_node, deadline_at=datetime.now(UTC) - timedelta(hours=1))
        node_run = _node_run(workflow_run_id=run.id, node_instance_id=node.id)
        outbox = _outbox(node_run_id=node_run.id)
        repo.get_run_by_id_for_update.return_value = run
        repo.get_node_run_by_id_for_update.return_value = node_run
        repo.get_outbox_for_node_run.return_value = outbox
        repo.update_run.side_effect = lambda _db, *, run, update_data: _apply(run, update_data)

        result = await dispatcher.begin_attempt(
            object(), workflow_run_id=run.id, node_run_id=node_run.id
        )

        assert result is None
        assert run.status == WorkflowRunStatus.FAILED.value
        assert run.error is not None and run.error["code"] == "DEADLINE_EXCEEDED"
        repo.mark_outbox_done.assert_awaited_once_with(ANY, outbox=outbox)
        repo.cancel_live_outbox_for_run.assert_awaited_once()
        repo.create_attempt.assert_not_called()

    @pytest.mark.security
    async def test_over_budget_marks_the_run_and_creates_no_attempt(
        self, repo, event_log, test_node
    ):
        run, node = _test_mode_run(test_node, budget_limit=Decimal("1"), spent_cost=Decimal("1"))
        node_run = _node_run(workflow_run_id=run.id, node_instance_id=node.id)
        outbox = _outbox(node_run_id=node_run.id)
        repo.get_run_by_id_for_update.return_value = run
        repo.get_node_run_by_id_for_update.return_value = node_run
        repo.get_outbox_for_node_run.return_value = outbox
        repo.update_run.side_effect = lambda _db, *, run, update_data: _apply(run, update_data)

        result = await dispatcher.begin_attempt(
            object(), workflow_run_id=run.id, node_run_id=node_run.id
        )

        assert result is None
        assert run.status == WorkflowRunStatus.BUDGET_EXCEEDED.value
        repo.mark_outbox_done.assert_awaited_once_with(ANY, outbox=outbox)
        repo.create_attempt.assert_not_called()

    async def test_an_orphaned_in_flight_attempt_is_resolved_instead_of_duplicated(
        self, repo, event_log, test_node
    ):
        run, node = _test_mode_run(test_node)
        node_run = _node_run(workflow_run_id=run.id, node_instance_id=node.id)
        orphan = _attempt(node_run_id=node_run.id, status=NodeAttemptStatus.IN_FLIGHT.value)
        outbox = _outbox(node_run_id=node_run.id)
        repo.get_run_by_id_for_update.return_value = run
        repo.get_node_run_by_id_for_update.return_value = node_run
        repo.get_outbox_for_node_run.return_value = outbox
        repo.get_latest_attempt.return_value = orphan
        repo.settle_attempt.side_effect = _settle_effect
        repo.update_run.side_effect = lambda _db, *, run, update_data: _apply(run, update_data)
        repo.update_node_run.side_effect = lambda _db, *, node_run, update_data: _apply(
            node_run, update_data
        )

        result = await dispatcher.begin_attempt(
            object(), workflow_run_id=run.id, node_run_id=node_run.id
        )

        assert result is None
        # idempotent guarantee => auto-retried, not left in needs_attention
        assert orphan.status == NodeAttemptStatus.UNCERTAIN.value
        repo.create_outbox.assert_awaited_once()
        repo.create_attempt.assert_not_called()


def _apply(obj: object, update_data: dict[str, object]) -> object:
    for field, value in update_data.items():
        setattr(obj, field, value)
    return obj


async def _settle_effect(
    _db: object,
    *,
    attempt: NodeAttempt,
    status: str,
    result: object,
    cost: Decimal,
    cost_is_partial: bool,
    ended_at: object,
) -> NodeAttempt:
    attempt.status = status
    attempt.result = result
    attempt.cost = cost
    attempt.cost_is_partial = cost_is_partial
    attempt.ended_at = ended_at
    return attempt


class TestBeginAttemptHappyPath:
    async def test_creates_an_in_flight_attempt_and_returns_the_resolved_call(
        self, repo, event_log, test_node
    ):
        run, node = _test_mode_run(test_node, execution_principal_user_id=None)
        node_run = _node_run(workflow_run_id=run.id, node_instance_id=node.id)
        repo.get_run_by_id_for_update.return_value = run
        repo.get_node_run_by_id_for_update.return_value = node_run
        repo.get_outbox_for_node_run.return_value = _outbox(node_run_id=node_run.id)
        repo.get_latest_attempt.return_value = None
        created_attempt = _attempt(node_run_id=node_run.id, attempt_no=1)
        repo.create_attempt.return_value = created_attempt
        repo.update_node_run.side_effect = lambda _db, *, node_run, update_data: _apply(
            node_run, update_data
        )

        begun = await dispatcher.begin_attempt(
            object(), workflow_run_id=run.id, node_run_id=node_run.id
        )

        assert begun is not None
        assert begun.attempt_id == created_attempt.id
        assert begun.attempt_no == 1
        assert begun.definition.id == test_node
        assert begun.handler_config.message == "hi"
        assert begun.handler_input is None
        assert node_run.status == NodeRunStatus.RUNNING.value
        repo.create_attempt.assert_awaited_once()
        assert repo.create_attempt.await_args.kwargs["retry_guarantee"] == "idempotent"

    async def test_a_second_attempt_numbers_itself_after_the_first(
        self, repo, event_log, test_node
    ):
        run, node = _test_mode_run(test_node)
        node_run = _node_run(workflow_run_id=run.id, node_instance_id=node.id)
        repo.get_run_by_id_for_update.return_value = run
        repo.get_node_run_by_id_for_update.return_value = node_run
        repo.get_outbox_for_node_run.return_value = None
        repo.get_latest_attempt.return_value = _attempt(
            node_run_id=node_run.id, attempt_no=1, status=NodeAttemptStatus.FAILED.value
        )
        repo.create_attempt.return_value = _attempt(node_run_id=node_run.id, attempt_no=2)
        repo.update_node_run.side_effect = lambda _db, *, node_run, update_data: _apply(
            node_run, update_data
        )

        begun = await dispatcher.begin_attempt(
            object(), workflow_run_id=run.id, node_run_id=node_run.id
        )

        assert begun is not None
        assert begun.attempt_no == 2
        assert repo.create_attempt.await_args.kwargs["attempt_no"] == 2

    async def test_resolves_a_node_output_ref_from_a_completed_predecessor(
        self, repo, event_log, test_node
    ):
        source = _node_instance(test_node, config={"message": "from-source"})
        target = _node_instance(test_node)
        binding = Binding(
            target_node_id=target.id,
            target_field="message",
            source=NodeOutputRef(node_id=source.id, port="out", field_path=("echoed",)),
        )
        graph = WorkflowGraph(entry_node_id=source.id, nodes=(source, target), bindings=(binding,))
        run = _run(
            mode=WorkflowRunMode.TEST.value,
            workflow_version_id=None,
            draft_graph_snapshot=graph.model_dump(mode="json"),
        )
        target_node_run = _node_run(workflow_run_id=run.id, node_instance_id=target.id)
        source_node_run = _node_run(
            workflow_run_id=run.id, node_instance_id=source.id, status=NodeRunStatus.SUCCEEDED.value
        )
        completed_attempt = _attempt(
            node_run_id=source_node_run.id,
            status=NodeAttemptStatus.COMPLETED.value,
            result={"status": "completed", "output": {"echoed": "carried-over"}},
        )

        repo.get_run_by_id_for_update.return_value = run
        repo.get_node_run_by_id_for_update.return_value = target_node_run

        async def _by_identity(_db, *, workflow_run_id, node_instance_id, scope_path):
            if node_instance_id == source.id:
                return source_node_run
            return None

        repo.get_node_run_by_identity.side_effect = _by_identity

        async def _latest_attempt(_db, *, node_run_id):
            if node_run_id == source_node_run.id:
                return completed_attempt
            return None

        repo.get_latest_attempt.side_effect = _latest_attempt
        repo.get_outbox_for_node_run.return_value = None
        repo.create_attempt.return_value = _attempt(node_run_id=target_node_run.id)
        repo.update_node_run.side_effect = lambda _db, *, node_run, update_data: _apply(
            node_run, update_data
        )

        begun = await dispatcher.begin_attempt(
            object(), workflow_run_id=run.id, node_run_id=target_node_run.id
        )

        assert begun is not None
        assert begun.handler_input.message == "carried-over"


def _begun(
    node: NodeInstance,
    definition,
    *,
    handler_config=None,
    handler_input=None,
    attempt_id=None,
    attempt_no=1,
    node_run_id=None,
    workflow_run_id=None,
) -> dispatcher.BegunAttempt:
    org = uuid.uuid4()
    wf_run = workflow_run_id or uuid.uuid4()
    nr = node_run_id or uuid.uuid4()
    return dispatcher.BegunAttempt(
        workflow_run_id=wf_run,
        node_run_id=nr,
        node_instance_id=node.id,
        organization_id=org,
        attempt_id=attempt_id or uuid.uuid4(),
        attempt_no=attempt_no,
        handler_config=handler_config,
        handler_input=handler_input,
        definition=definition,
        dispatch_context=context.DispatchContext(
            organization_id=org,
            workflow_run_id=wf_run,
            node_run_id=nr,
            node_instance_id=node.id,
            attempt_no=attempt_no,
            auth=MagicMock(),
            resumed_agent_run_id=None,
        ),
    )


class TestCallHandler:
    async def test_calls_the_registered_handler_and_returns_its_result(self, test_node: str):
        node = _node_instance(test_node, config={"message": "hi"})
        definition = REGISTRY[test_node][1]
        begun = _begun(node, definition, handler_config=_EchoConfig(message="hi"))
        result, waiting_agent_run_id = await dispatcher.call_handler(begun)
        assert isinstance(result, Completed)
        assert result.output.echoed == "hi"
        assert waiting_agent_run_id is None

    async def test_a_handler_reporting_a_waiting_agent_run_is_surfaced(self, test_node: str):
        node = _node_instance(test_node)
        definition = REGISTRY[test_node][1]
        reported = uuid.uuid4()

        async def _parking_handler(_config: object, _input: object) -> NodeResult:
            context.report_waiting_agent_run(reported)
            return Waiting(reason="approval", resume_token=str(context.current().node_run_id))

        patched = definition.__class__(**{**definition.__dict__, "handler": _parking_handler})
        begun = _begun(node, patched)

        _result, waiting_agent_run_id = await dispatcher.call_handler(begun)
        assert waiting_agent_run_id == reported

    async def test_a_definition_with_no_handler_raises(self, test_node: str):
        node = _node_instance(test_node)
        definition = REGISTRY[test_node][1]
        patched = definition.__class__(**{**definition.__dict__, "handler": None})
        begun = _begun(node, patched)
        with pytest.raises(RuntimeError):
            await dispatcher.call_handler(begun)

    async def test_the_dispatch_context_is_cleared_after_the_call(self, test_node: str):
        node = _node_instance(test_node)
        definition = REGISTRY[test_node][1]
        begun = _begun(node, definition, handler_config=_EchoConfig())
        await dispatcher.call_handler(begun)
        with pytest.raises(RuntimeError):
            context.current()


class TestSettleCompleted:
    async def test_marks_the_attempt_and_node_run_succeeded_and_advances(
        self, repo, event_log, test_node
    ):
        node = _node_instance(test_node)
        definition = REGISTRY[test_node][1]
        run = _run(
            mode=WorkflowRunMode.TEST.value,
            workflow_version_id=None,
            draft_graph_snapshot=_graph(node).model_dump(mode="json"),
        )
        node_run = _node_run(
            workflow_run_id=run.id, node_instance_id=node.id, status=NodeRunStatus.RUNNING.value
        )
        attempt = _attempt(node_run_id=node_run.id)
        begun = _begun(
            node, definition, attempt_id=attempt.id, node_run_id=node_run.id, workflow_run_id=run.id
        )

        repo.get_run_by_id_for_update.return_value = run
        repo.get_node_run_by_id_for_update.return_value = node_run
        repo.get_attempt.return_value = attempt
        repo.get_outbox_for_node_run.return_value = _outbox(node_run_id=node_run.id)
        repo.settle_attempt.side_effect = _settle_effect
        repo.update_node_run.side_effect = lambda _db, *, node_run, update_data: _apply(
            node_run, update_data
        )
        repo.update_run.side_effect = lambda _db, *, run, update_data: _apply(run, update_data)
        repo.has_live_outbox.return_value = False

        result = Completed[_EchoOutput](output=_EchoOutput(echoed="done"))
        await dispatcher.settle(object(), begun=begun, result=result, waiting_agent_run_id=None)

        assert attempt.status == NodeAttemptStatus.COMPLETED.value
        assert node_run.status == NodeRunStatus.SUCCEEDED.value
        assert run.status == WorkflowRunStatus.SUCCEEDED.value
        repo.mark_outbox_done.assert_awaited_once()

    async def test_missing_rows_at_settle_time_are_a_no_op(self, repo, event_log, test_node):
        node = _node_instance(test_node)
        definition = REGISTRY[test_node][1]
        begun = _begun(node, definition)
        repo.get_run_by_id_for_update.return_value = None
        result = Completed[_EchoOutput](output=_EchoOutput(echoed="x"))
        await dispatcher.settle(object(), begun=begun, result=result, waiting_agent_run_id=None)
        repo.settle_attempt.assert_not_called()


class TestSettleWaiting:
    async def test_parks_the_node_run_and_sets_the_resume_token_to_its_own_id(
        self, repo, event_log, test_node
    ):
        node = _node_instance(test_node)
        definition = REGISTRY[test_node][1]
        run = _run(
            mode=WorkflowRunMode.TEST.value,
            workflow_version_id=None,
            draft_graph_snapshot=_graph(node).model_dump(mode="json"),
        )
        node_run = _node_run(
            workflow_run_id=run.id, node_instance_id=node.id, status=NodeRunStatus.RUNNING.value
        )
        attempt = _attempt(node_run_id=node_run.id)
        begun = _begun(
            node, definition, attempt_id=attempt.id, node_run_id=node_run.id, workflow_run_id=run.id
        )

        repo.get_run_by_id_for_update.return_value = run
        repo.get_node_run_by_id_for_update.return_value = node_run
        repo.get_attempt.return_value = attempt
        repo.get_outbox_for_node_run.return_value = _outbox(node_run_id=node_run.id)
        repo.settle_attempt.side_effect = _settle_effect
        repo.update_node_run.side_effect = lambda _db, *, node_run, update_data: _apply(
            node_run, update_data
        )
        repo.update_run.side_effect = lambda _db, *, run, update_data: _apply(run, update_data)

        agent_run_id = uuid.uuid4()
        result = Waiting(reason="approval", resume_token="whatever-the-handler-sent")
        await dispatcher.settle(
            object(), begun=begun, result=result, waiting_agent_run_id=agent_run_id
        )

        # The attempt itself succeeded - it started a real effect and parked.
        assert attempt.status == NodeAttemptStatus.COMPLETED.value
        assert node_run.status == NodeRunStatus.WAITING.value
        assert node_run.waiting_reason == "approval"
        # The resume token is a structural invariant: always the node run's own id.
        assert node_run.resume_token == str(node_run.id)
        assert node_run.waiting_agent_run_id == agent_run_id
        assert run.status == WorkflowRunStatus.WAITING_APPROVAL.value
        assert run.paused_reason == "approval"

    async def test_a_retry_backoff_wait_marks_the_run_waiting_retry(
        self, repo, event_log, test_node
    ):
        node = _node_instance(test_node)
        definition = REGISTRY[test_node][1]
        run = _run(
            mode=WorkflowRunMode.TEST.value,
            workflow_version_id=None,
            draft_graph_snapshot=_graph(node).model_dump(mode="json"),
        )
        node_run = _node_run(workflow_run_id=run.id, node_instance_id=node.id)
        attempt = _attempt(node_run_id=node_run.id)
        begun = _begun(
            node, definition, attempt_id=attempt.id, node_run_id=node_run.id, workflow_run_id=run.id
        )

        repo.get_run_by_id_for_update.return_value = run
        repo.get_node_run_by_id_for_update.return_value = node_run
        repo.get_attempt.return_value = attempt
        repo.get_outbox_for_node_run.return_value = None
        repo.settle_attempt.side_effect = _settle_effect
        repo.update_node_run.side_effect = lambda _db, *, node_run, update_data: _apply(
            node_run, update_data
        )
        repo.update_run.side_effect = lambda _db, *, run, update_data: _apply(run, update_data)

        result = Waiting(reason="external_event", resume_token="x")
        await dispatcher.settle(object(), begun=begun, result=result, waiting_agent_run_id=None)

        assert run.status == WorkflowRunStatus.WAITING_RETRY.value


class TestSettleFailed:
    async def test_a_retryable_failure_schedules_backoff_and_keeps_the_node_run_alive(
        self, repo, event_log, test_node
    ):
        node = _node_instance(test_node)
        definition = REGISTRY[test_node][1]
        run = _run(
            mode=WorkflowRunMode.TEST.value,
            workflow_version_id=None,
            draft_graph_snapshot=_graph(node).model_dump(mode="json"),
        )
        node_run = _node_run(workflow_run_id=run.id, node_instance_id=node.id)
        attempt = _attempt(
            node_run_id=node_run.id, attempt_no=1, retry_guarantee=RetryGuarantee.IDEMPOTENT.value
        )
        begun = _begun(
            node,
            definition,
            attempt_id=attempt.id,
            node_run_id=node_run.id,
            workflow_run_id=run.id,
            attempt_no=1,
        )

        repo.get_run_by_id_for_update.return_value = run
        repo.get_node_run_by_id_for_update.return_value = node_run
        repo.get_attempt.return_value = attempt
        repo.get_outbox_for_node_run.return_value = None
        repo.settle_attempt.side_effect = _settle_effect
        repo.update_node_run.side_effect = lambda _db, *, node_run, update_data: _apply(
            node_run, update_data
        )
        repo.update_run.side_effect = lambda _db, *, run, update_data: _apply(run, update_data)

        error = WorkflowError(code="TRANSIENT", message="try again", retryable=True)
        await dispatcher.settle(
            object(), begun=begun, result=Failed(error=error), waiting_agent_run_id=None
        )

        assert node_run.status == NodeRunStatus.WAITING.value
        assert node_run.waiting_reason == WaitingReason.RETRY_BACKOFF.value
        assert run.status == WorkflowRunStatus.WAITING_RETRY.value
        repo.create_outbox.assert_awaited_once()
        repo.cancel_live_outbox_for_run.assert_not_called()

    async def test_a_non_retryable_failure_fails_the_node_run_and_the_run(
        self, repo, event_log, test_node
    ):
        node = _node_instance(test_node)
        definition = REGISTRY[test_node][1]
        run = _run(
            mode=WorkflowRunMode.TEST.value,
            workflow_version_id=None,
            draft_graph_snapshot=_graph(node).model_dump(mode="json"),
        )
        node_run = _node_run(workflow_run_id=run.id, node_instance_id=node.id)
        attempt = _attempt(node_run_id=node_run.id, retry_guarantee=RetryGuarantee.NONE.value)
        begun = _begun(
            node, definition, attempt_id=attempt.id, node_run_id=node_run.id, workflow_run_id=run.id
        )

        repo.get_run_by_id_for_update.return_value = run
        repo.get_node_run_by_id_for_update.return_value = node_run
        repo.get_attempt.return_value = attempt
        repo.get_outbox_for_node_run.return_value = None
        repo.settle_attempt.side_effect = _settle_effect
        repo.update_node_run.side_effect = lambda _db, *, node_run, update_data: _apply(
            node_run, update_data
        )
        repo.update_run.side_effect = lambda _db, *, run, update_data: _apply(run, update_data)

        error = WorkflowError(code="BAD_INPUT", message="nope", retryable=False)
        await dispatcher.settle(
            object(), begun=begun, result=Failed(error=error), waiting_agent_run_id=None
        )

        assert node_run.status == NodeRunStatus.FAILED.value
        assert run.status == WorkflowRunStatus.FAILED.value
        assert run.error["code"] == "BAD_INPUT"
        repo.cancel_live_outbox_for_run.assert_awaited_once()
        repo.create_outbox.assert_not_called()

    async def test_retries_exhausted_at_the_ceiling_fails_outright(
        self, repo, event_log, test_node
    ):
        node = _node_instance(test_node)
        definition = REGISTRY[test_node][1]
        run = _run(
            mode=WorkflowRunMode.TEST.value,
            workflow_version_id=None,
            draft_graph_snapshot=_graph(node).model_dump(mode="json"),
        )
        node_run = _node_run(workflow_run_id=run.id, node_instance_id=node.id)
        from app.core.config import settings as app_settings

        attempt = _attempt(
            node_run_id=node_run.id,
            attempt_no=app_settings.WORKFLOW_RETRY_CEILING,
            retry_guarantee=RetryGuarantee.IDEMPOTENT.value,
        )
        begun = _begun(
            node,
            definition,
            attempt_id=attempt.id,
            node_run_id=node_run.id,
            workflow_run_id=run.id,
            attempt_no=app_settings.WORKFLOW_RETRY_CEILING,
        )

        repo.get_run_by_id_for_update.return_value = run
        repo.get_node_run_by_id_for_update.return_value = node_run
        repo.get_attempt.return_value = attempt
        repo.get_outbox_for_node_run.return_value = None
        repo.settle_attempt.side_effect = _settle_effect
        repo.update_node_run.side_effect = lambda _db, *, node_run, update_data: _apply(
            node_run, update_data
        )
        repo.update_run.side_effect = lambda _db, *, run, update_data: _apply(run, update_data)

        error = WorkflowError(code="TRANSIENT", message="try again", retryable=True)
        await dispatcher.settle(
            object(), begun=begun, result=Failed(error=error), waiting_agent_run_id=None
        )

        assert node_run.status == NodeRunStatus.FAILED.value
        assert run.status == WorkflowRunStatus.FAILED.value


class TestSettleUncertain:
    async def test_marks_the_node_run_and_run_needs_attention(self, repo, event_log, test_node):
        node = _node_instance(test_node)
        definition = REGISTRY[test_node][1]
        run = _run(
            mode=WorkflowRunMode.TEST.value,
            workflow_version_id=None,
            draft_graph_snapshot=_graph(node).model_dump(mode="json"),
        )
        node_run = _node_run(workflow_run_id=run.id, node_instance_id=node.id)
        attempt = _attempt(node_run_id=node_run.id)
        begun = _begun(
            node, definition, attempt_id=attempt.id, node_run_id=node_run.id, workflow_run_id=run.id
        )

        repo.get_run_by_id_for_update.return_value = run
        repo.get_node_run_by_id_for_update.return_value = node_run
        repo.get_attempt.return_value = attempt
        repo.get_outbox_for_node_run.return_value = None
        repo.settle_attempt.side_effect = _settle_effect
        repo.update_node_run.side_effect = lambda _db, *, node_run, update_data: _apply(
            node_run, update_data
        )
        repo.update_run.side_effect = lambda _db, *, run, update_data: _apply(run, update_data)

        await dispatcher.settle(
            object(),
            begun=begun,
            result=Uncertain(detail="timed out mid-call"),
            waiting_agent_run_id=None,
        )

        assert attempt.status == NodeAttemptStatus.UNCERTAIN.value
        assert node_run.status == NodeRunStatus.NEEDS_ATTENTION.value
        assert run.status == WorkflowRunStatus.NEEDS_ATTENTION.value


class _FakeNestedTxn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False  # never swallow - the caller's own try/except decides


def _nested_txn_db() -> MagicMock:
    """A `db` double whose `begin_nested()` behaves like a real savepoint
    context manager, for the `_advance` paths that create a `NodeRun`."""
    db = MagicMock()
    db.begin_nested = MagicMock(side_effect=lambda: _FakeNestedTxn())
    return db


class TestAdvance:
    async def test_a_ready_downstream_node_gets_a_fresh_node_run_and_outbox(self, repo, test_node):
        source = _node_instance(test_node)
        target = _node_instance(test_node)
        edge = Edge(
            id=uuid.uuid4(),
            source_node_id=source.id,
            source_port="out",
            target_node_id=target.id,
            target_port="in",
        )
        graph = WorkflowGraph(entry_node_id=source.id, nodes=(source, target), edges=(edge,))
        run = _run(
            mode=WorkflowRunMode.TEST.value,
            workflow_version_id=None,
            draft_graph_snapshot=graph.model_dump(mode="json"),
        )

        async def _by_identity(_db, *, workflow_run_id, node_instance_id, scope_path):
            if node_instance_id == target.id:
                return None  # not created yet
            return _node_run(
                workflow_run_id=run.id,
                node_instance_id=source.id,
                status=NodeRunStatus.SUCCEEDED.value,
            )

        repo.get_node_run_by_identity.side_effect = _by_identity
        created = _node_run(workflow_run_id=run.id, node_instance_id=target.id)
        repo.create_node_run.return_value = created

        await dispatcher._advance(_nested_txn_db(), run=run, completed_node_instance_id=source.id)

        repo.create_node_run.assert_awaited_once()
        assert repo.create_node_run.await_args.kwargs["node_instance_id"] == target.id
        repo.create_outbox.assert_awaited_once()
        assert repo.create_outbox.await_args.kwargs["node_run_id"] == created.id

    async def test_a_downstream_node_with_an_undone_predecessor_is_not_dispatched(
        self, repo, test_node
    ):
        source_a = _node_instance(test_node)
        source_b = _node_instance(test_node)
        target = _node_instance(test_node)
        edges = (
            Edge(
                id=uuid.uuid4(),
                source_node_id=source_a.id,
                source_port="out",
                target_node_id=target.id,
                target_port="in",
            ),
            Edge(
                id=uuid.uuid4(),
                source_node_id=source_b.id,
                source_port="out",
                target_node_id=target.id,
                target_port="in",
            ),
        )
        graph = WorkflowGraph(
            entry_node_id=source_a.id, nodes=(source_a, source_b, target), edges=edges
        )
        run = _run(
            mode=WorkflowRunMode.TEST.value,
            workflow_version_id=None,
            draft_graph_snapshot=graph.model_dump(mode="json"),
        )

        async def _by_identity(_db, *, workflow_run_id, node_instance_id, scope_path):
            if node_instance_id == target.id:
                return None
            if node_instance_id == source_b.id:
                return _node_run(
                    workflow_run_id=run.id,
                    node_instance_id=source_b.id,
                    status=NodeRunStatus.PENDING.value,
                )
            return None

        repo.get_node_run_by_identity.side_effect = _by_identity

        await dispatcher._advance(object(), run=run, completed_node_instance_id=source_a.id)

        repo.create_node_run.assert_not_called()

    async def test_a_node_reached_from_two_completed_predecessors_dispatches_once(
        self, repo, test_node
    ):
        source_a = _node_instance(test_node)
        source_b = _node_instance(test_node)
        target = _node_instance(test_node)
        edges = (
            Edge(
                id=uuid.uuid4(),
                source_node_id=source_a.id,
                source_port="out",
                target_node_id=target.id,
                target_port="in",
            ),
            Edge(
                id=uuid.uuid4(),
                source_node_id=source_b.id,
                source_port="out",
                target_node_id=target.id,
                target_port="in",
            ),
        )
        graph = WorkflowGraph(
            entry_node_id=source_a.id, nodes=(source_a, source_b, target), edges=edges
        )
        run = _run(
            mode=WorkflowRunMode.TEST.value,
            workflow_version_id=None,
            draft_graph_snapshot=graph.model_dump(mode="json"),
        )

        async def _by_identity(_db, *, workflow_run_id, node_instance_id, scope_path):
            if node_instance_id == target.id:
                return None
            return _node_run(
                workflow_run_id=run.id,
                node_instance_id=node_instance_id,
                status=NodeRunStatus.SUCCEEDED.value,
            )

        repo.get_node_run_by_identity.side_effect = _by_identity
        repo.create_node_run.return_value = _node_run(
            workflow_run_id=run.id, node_instance_id=target.id
        )

        await dispatcher._advance(_nested_txn_db(), run=run, completed_node_instance_id=source_a.id)

        repo.create_node_run.assert_awaited_once()

    async def test_a_sibling_race_losing_the_unique_index_is_swallowed(self, repo, test_node):
        from sqlalchemy.exc import IntegrityError

        source = _node_instance(test_node)
        target = _node_instance(test_node)
        edge = Edge(
            id=uuid.uuid4(),
            source_node_id=source.id,
            source_port="out",
            target_node_id=target.id,
            target_port="in",
        )
        graph = WorkflowGraph(entry_node_id=source.id, nodes=(source, target), edges=(edge,))
        run = _run(
            mode=WorkflowRunMode.TEST.value,
            workflow_version_id=None,
            draft_graph_snapshot=graph.model_dump(mode="json"),
        )

        async def _by_identity(_db, *, workflow_run_id, node_instance_id, scope_path):
            if node_instance_id == target.id:
                return None
            return _node_run(
                workflow_run_id=run.id,
                node_instance_id=source.id,
                status=NodeRunStatus.SUCCEEDED.value,
            )

        repo.get_node_run_by_identity.side_effect = _by_identity
        repo.create_node_run.side_effect = IntegrityError("insert", {}, Exception("dup"))

        await dispatcher._advance(_nested_txn_db(), run=run, completed_node_instance_id=source.id)

        repo.create_outbox.assert_not_called()

    async def test_no_downstream_and_no_live_outbox_succeeds_the_run(
        self, repo, event_log, test_node
    ):
        node = _node_instance(test_node)
        graph = _graph(node)
        run = _run(
            mode=WorkflowRunMode.TEST.value,
            workflow_version_id=None,
            draft_graph_snapshot=graph.model_dump(mode="json"),
        )
        repo.has_live_outbox.return_value = False
        repo.update_run.side_effect = lambda _db, *, run, update_data: _apply(run, update_data)

        await dispatcher._advance(object(), run=run, completed_node_instance_id=node.id)

        assert run.status == WorkflowRunStatus.SUCCEEDED.value

    async def test_no_downstream_but_a_live_outbox_remains_leaves_the_run_alone(
        self, repo, event_log, test_node
    ):
        node = _node_instance(test_node)
        graph = _graph(node)
        run = _run(
            mode=WorkflowRunMode.TEST.value,
            workflow_version_id=None,
            draft_graph_snapshot=graph.model_dump(mode="json"),
        )
        repo.has_live_outbox.return_value = True

        await dispatcher._advance(object(), run=run, completed_node_instance_id=node.id)

        repo.update_run.assert_not_called()


class TestResolveOrphanedAttempt:
    async def test_an_idempotent_orphan_is_marked_uncertain_and_gets_a_fresh_outbox_row(
        self, repo, event_log
    ):
        run = _run()
        node_run = _node_run(workflow_run_id=run.id, node_instance_id=uuid.uuid4())
        attempt = _attempt(node_run_id=node_run.id, retry_guarantee=RetryGuarantee.IDEMPOTENT.value)
        outbox = _outbox(node_run_id=node_run.id)
        repo.settle_attempt.side_effect = _settle_effect

        await dispatcher.resolve_orphaned_attempt(
            object(), run=run, node_run=node_run, attempt=attempt, outbox=outbox
        )

        assert attempt.status == NodeAttemptStatus.UNCERTAIN.value
        repo.mark_outbox_done.assert_awaited_once()
        repo.create_outbox.assert_awaited_once()
        repo.update_node_run.assert_not_called()

    async def test_an_at_least_once_orphan_lands_in_needs_attention_without_a_retry(
        self, repo, event_log
    ):
        run = _run()
        node_run = _node_run(workflow_run_id=run.id, node_instance_id=uuid.uuid4())
        attempt = _attempt(
            node_run_id=node_run.id, retry_guarantee=RetryGuarantee.AT_LEAST_ONCE.value
        )
        repo.settle_attempt.side_effect = _settle_effect
        repo.update_node_run.side_effect = lambda _db, *, node_run, update_data: _apply(
            node_run, update_data
        )
        repo.update_run.side_effect = lambda _db, *, run, update_data: _apply(run, update_data)

        await dispatcher.resolve_orphaned_attempt(
            object(), run=run, node_run=node_run, attempt=attempt, outbox=None
        )

        assert attempt.status == NodeAttemptStatus.UNCERTAIN.value
        assert node_run.status == NodeRunStatus.NEEDS_ATTENTION.value
        assert run.status == WorkflowRunStatus.NEEDS_ATTENTION.value
        repo.create_outbox.assert_not_called()

    async def test_a_none_guarantee_orphan_also_lands_in_needs_attention(self, repo, event_log):
        run = _run()
        node_run = _node_run(workflow_run_id=run.id, node_instance_id=uuid.uuid4())
        attempt = _attempt(node_run_id=node_run.id, retry_guarantee=RetryGuarantee.NONE.value)
        repo.settle_attempt.side_effect = _settle_effect
        repo.update_node_run.side_effect = lambda _db, *, node_run, update_data: _apply(
            node_run, update_data
        )
        repo.update_run.side_effect = lambda _db, *, run, update_data: _apply(run, update_data)

        await dispatcher.resolve_orphaned_attempt(
            object(), run=run, node_run=node_run, attempt=attempt, outbox=None
        )

        assert node_run.status == NodeRunStatus.NEEDS_ATTENTION.value
        repo.create_outbox.assert_not_called()


class _ConfigOnly(BaseModel):
    label: str = "x"


class _InputOnly(BaseModel):
    message: str = ""


@pytest.fixture
def split_schema_node() -> str:
    """A node whose config and input fields are disjoint, and which declares
    no config schema's sibling - for the branches `test_node`'s shared
    schema can never exercise."""
    node_id = f"test.split-{uuid.uuid4().hex[:8]}"
    register(
        NodeDefinition(
            id=node_id,
            version=1,
            name="Split schema node",
            category="test",
            description="config and input do not overlap.",
            kind="action",
            config_schema=_ConfigOnly,
            input_schema=_InputOnly,
            output_schema=_EchoOutput,
            ports=(
                Port(id="in", label="In", kind="input", schema=_InputOnly),
                Port(id="out", label="Out", kind="output", schema=_EchoOutput),
            ),
            effect_kind="pure",
            retry_guarantee="none",
            handler=_pure_handler,
        )
    )
    yield node_id
    REGISTRY.pop(node_id, None)


@pytest.fixture
def no_config_node() -> str:
    """A node with no config schema at all - a pure trigger with only an input."""
    node_id = f"test.noconfig-{uuid.uuid4().hex[:8]}"
    register(
        NodeDefinition(
            id=node_id,
            version=1,
            name="No config node",
            category="test",
            description="No config schema.",
            kind="action",
            config_schema=None,
            input_schema=_InputOnly,
            output_schema=_EchoOutput,
            ports=(Port(id="out", label="Out", kind="output", schema=_EchoOutput),),
            effect_kind="pure",
            retry_guarantee="none",
            handler=_pure_handler,
        )
    )
    yield node_id
    REGISTRY.pop(node_id, None)


class TestFieldOwnerMore:
    def test_a_config_only_field_owns_config(self, split_schema_node: str):
        definition = REGISTRY[split_schema_node][1]
        assert dispatcher._field_owner(definition, "label") == "config"

    def test_no_config_schema_never_claims_a_field(self, no_config_node: str):
        definition = REGISTRY[no_config_node][1]
        assert dispatcher._field_owner(definition, "anything") is None


class TestResolveSourceUnknown:
    def test_an_unrecognised_source_type_raises(self):
        with pytest.raises(TypeError):
            dispatcher._resolve_source(object(), {})  # type: ignore[arg-type]


class TestResolveIOMore:
    def test_a_binding_for_a_different_node_is_ignored(self, test_node: str):
        definition = REGISTRY[test_node][1]
        node = _node_instance(test_node, config={"message": "keep"})
        other_binding = Binding(
            target_node_id=uuid.uuid4(),
            target_field="message",
            source=LiteralValue(value="not-mine"),
        )
        graph = _graph(node, bindings=(other_binding,))
        config_obj, _input_obj = dispatcher._resolve_io(graph, node, definition, outputs={})
        assert config_obj.message == "keep"

    def test_a_binding_targeting_neither_schema_is_skipped(self, test_node: str):
        # Defensive: rule 9 (`_binding_target_field_problems`) already refuses
        # this at publish time, so a real dispatch never sees it - covered
        # here only to prove the loop does not raise on it.
        definition = REGISTRY[test_node][1]
        node = _node_instance(test_node, config={"message": "kept"})
        stray = Binding(
            target_node_id=node.id, target_field="nonexistent", source=LiteralValue(value="x")
        )
        graph = _graph(node, bindings=(stray,))
        config_obj, input_obj = dispatcher._resolve_io(graph, node, definition, outputs={})
        assert config_obj.message == "kept"
        assert input_obj is None

    def test_a_config_field_binding_overrides_the_base_config(self, split_schema_node: str):
        definition = REGISTRY[split_schema_node][1]
        node = _node_instance(split_schema_node, config={"label": "original"})
        binding = Binding(
            target_node_id=node.id, target_field="label", source=LiteralValue(value="overridden")
        )
        graph = _graph(node, bindings=(binding,))
        config_obj, _input_obj = dispatcher._resolve_io(graph, node, definition, outputs={})
        assert config_obj.label == "overridden"

    def test_no_config_schema_produces_no_config_object(self, no_config_node: str):
        definition = REGISTRY[no_config_node][1]
        node = _node_instance(no_config_node)
        graph = _graph(node)
        config_obj, _input_obj = dispatcher._resolve_io(graph, node, definition, outputs={})
        assert config_obj is None


class TestCompletedOutputsMore:
    async def test_a_source_with_no_node_run_yet_reports_no_output(self, repo):
        repo.get_node_run_by_identity.return_value = None
        outputs = await dispatcher._completed_outputs(
            object(), workflow_run_id=uuid.uuid4(), node_ids={uuid.uuid4()}
        )
        assert list(outputs.values()) == [None]

    async def test_a_source_with_no_completed_attempt_reports_no_output(self, repo):
        source_run = _node_run(workflow_run_id=uuid.uuid4(), node_instance_id=uuid.uuid4())
        repo.get_node_run_by_identity.return_value = source_run
        repo.get_latest_attempt.return_value = None
        outputs = await dispatcher._completed_outputs(
            object(), workflow_run_id=uuid.uuid4(), node_ids={source_run.node_instance_id}
        )
        assert outputs[source_run.node_instance_id] is None

    async def test_a_still_in_flight_attempt_reports_no_output(self, repo):
        source_run = _node_run(workflow_run_id=uuid.uuid4(), node_instance_id=uuid.uuid4())
        repo.get_node_run_by_identity.return_value = source_run
        repo.get_latest_attempt.return_value = _attempt(
            node_run_id=source_run.id, status=NodeAttemptStatus.IN_FLIGHT.value
        )
        outputs = await dispatcher._completed_outputs(
            object(), workflow_run_id=uuid.uuid4(), node_ids={source_run.node_instance_id}
        )
        assert outputs[source_run.node_instance_id] is None


class TestBeginAttemptMoreBranches:
    async def test_over_budget_with_no_outbox_row_skips_marking_one_done(
        self, repo, event_log, test_node
    ):
        run, node = _test_mode_run(test_node, budget_limit=Decimal("1"), spent_cost=Decimal("1"))
        node_run = _node_run(workflow_run_id=run.id, node_instance_id=node.id)
        repo.get_run_by_id_for_update.return_value = run
        repo.get_node_run_by_id_for_update.return_value = node_run
        repo.get_outbox_for_node_run.return_value = None
        repo.update_run.side_effect = lambda _db, *, run, update_data: _apply(run, update_data)

        result = await dispatcher.begin_attempt(
            object(), workflow_run_id=run.id, node_run_id=node_run.id
        )

        assert result is None
        repo.mark_outbox_done.assert_not_called()

    async def test_past_deadline_with_no_outbox_row_skips_marking_one_done(
        self, repo, event_log, test_node
    ):
        run, node = _test_mode_run(test_node, deadline_at=datetime.now(UTC) - timedelta(hours=1))
        node_run = _node_run(workflow_run_id=run.id, node_instance_id=node.id)
        repo.get_run_by_id_for_update.return_value = run
        repo.get_node_run_by_id_for_update.return_value = node_run
        repo.get_outbox_for_node_run.return_value = None
        repo.update_run.side_effect = lambda _db, *, run, update_data: _apply(run, update_data)

        result = await dispatcher.begin_attempt(
            object(), workflow_run_id=run.id, node_run_id=node_run.id
        )

        assert result is None
        repo.mark_outbox_done.assert_not_called()


class TestAdvanceMoreBranches:
    async def test_a_dangling_edge_target_is_skipped(self, repo, test_node):
        source = _node_instance(test_node)
        graph = _graph(source)  # only one real node
        dangling_edge = Edge(
            id=uuid.uuid4(),
            source_node_id=source.id,
            source_port="out",
            target_node_id=uuid.uuid4(),
            target_port="in",
        )
        graph_with_dangling_edge = graph.model_copy(update={"edges": (dangling_edge,)})
        run = _run(
            mode=WorkflowRunMode.TEST.value,
            workflow_version_id=None,
            draft_graph_snapshot=graph_with_dangling_edge.model_dump(mode="json"),
        )

        await dispatcher._advance(object(), run=run, completed_node_instance_id=source.id)

        repo.create_node_run.assert_not_called()

    async def test_a_target_that_already_has_a_node_run_is_not_recreated(self, repo, test_node):
        source = _node_instance(test_node)
        target = _node_instance(test_node)
        edge = Edge(
            id=uuid.uuid4(),
            source_node_id=source.id,
            source_port="out",
            target_node_id=target.id,
            target_port="in",
        )
        graph = WorkflowGraph(entry_node_id=source.id, nodes=(source, target), edges=(edge,))
        run = _run(
            mode=WorkflowRunMode.TEST.value,
            workflow_version_id=None,
            draft_graph_snapshot=graph.model_dump(mode="json"),
        )

        repo.get_node_run_by_identity.return_value = _node_run(
            workflow_run_id=run.id, node_instance_id=target.id
        )

        await dispatcher._advance(object(), run=run, completed_node_instance_id=source.id)

        repo.create_node_run.assert_not_called()
