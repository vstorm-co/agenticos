"""`app.services.workflow_execution.facade.WorkflowExecutionService`.

The repository and `resolve_access`/`visible_resource_ids` are mocked at the
database edge, matching `test_workflow_registry_service.py`'s bargain for the
sibling service. `dispatch_queue.queue_dispatch` (the entry node's outbox row
and job) is patched to a no-op: its own mechanics belong to
`test_workflow_dispatch_queue.py` and the integration suite.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.audit import set_impersonator
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.resource_grant import Visibility
from app.db.models.workflow import WorkflowStatus
from app.db.models.workflow_run import (
    NodeAttempt,
    NodeRun,
    WorkflowRunMode,
    WorkflowRunStatus,
    WorkflowRunTrigger,
)
from app.schemas.workflow_run import WorkflowStepResolve
from app.services.workflow_execution.exceptions import (
    WorkflowAdmissionQuotaError,
    WorkflowArchivedError,
    WorkflowBudgetHeldError,
    WorkflowNotRunnableError,
    WorkflowRunAlreadyTerminalError,
    WorkflowRunInputInvalidError,
    WorkflowRunInputTooLargeError,
    WorkflowRunNotFoundError,
    WorkflowStepNotFoundError,
    WorkflowStepNotResolvableError,
    WorkflowTriggerMismatchError,
)
from app.services.workflow_execution.facade import (
    Causation,
    WorkflowExecutionService,
    node_run_read,
)
from app.workflows.contracts.io import Binding, FileRef, LiteralValue, TableIORef
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph

pytestmark = pytest.mark.anyio

FACADE_PATH = "app.services.workflow_execution.facade"

_ORGANIZATION_ID = uuid.uuid4()


@pytest.fixture(autouse=True)
def _storage_lock_at_database_edge() -> Iterator[None]:
    with (
        patch(f"{FACADE_PATH}.hold_subject", new=AsyncMock()),
        patch(f"{FACADE_PATH}.admission.inline_storage_scope", new=AsyncMock(return_value=None)),
    ):
        yield


def _ctx(role: str = OrgRoleName.OWNER.value) -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=_ORGANIZATION_ID, role=role)


def _graph() -> WorkflowGraph:
    entry = NodeInstance(
        id=uuid.uuid4(),
        definition_id="debug.echo",
        definition_version=1,
        config={},
        layout=NodePosition(x=0, y=0),
    )
    return WorkflowGraph(entry_node_id=entry.id, nodes=(entry,))


def _workflow(**overrides: object) -> MagicMock:
    workflow = MagicMock()
    workflow.id = uuid.uuid4()
    workflow.organization_id = _ORGANIZATION_ID
    workflow.owner_user_id = uuid.uuid4()
    workflow.visibility = Visibility.PRIVATE.value
    workflow.status = WorkflowStatus.PUBLISHED.value
    workflow.current_version_id = uuid.uuid4()
    workflow.live_trigger = "core.input"
    workflow.settings = {}
    workflow.draft_graph = _graph().model_dump(mode="json")
    for field, value in overrides.items():
        setattr(workflow, field, value)
    return workflow


def _version(**overrides: object) -> MagicMock:
    version = MagicMock()
    version.id = uuid.uuid4()
    version.graph = _graph().model_dump(mode="json")
    version.budget_limit = None
    for field, value in overrides.items():
        setattr(version, field, value)
    return version


def _run_row(**overrides: object) -> MagicMock:
    run = MagicMock()
    run.id = uuid.uuid4()
    run.workflow_id = uuid.uuid4()
    run.workflow_version_id = uuid.uuid4()
    run.mode = WorkflowRunMode.REAL.value
    run.status = WorkflowRunStatus.RUNNING.value
    run.triggered_by = "api"
    run.budget_limit = None
    run.spent_cost = Decimal("0")
    run.cost_is_partial = False
    run.deadline_at = None
    run.paused_reason = None
    run.error = None
    run.output = None
    run.root_run_id = run.id
    run.causation_run_id = None
    run.retry_of_run_id = None
    run.depth = 0
    run.started_at = datetime.now(UTC)
    run.ended_at = None
    run.created_at = datetime.now(UTC)
    run.updated_at = None
    run.organization_id = _ORGANIZATION_ID
    for field, value in overrides.items():
        setattr(run, field, value)
    return run


@pytest.fixture
def _no_dispatch_trigger():
    with patch(f"{FACADE_PATH}.dispatch_queue.queue_dispatch", new=AsyncMock()):
        yield


@pytest.mark.usefixtures("_no_dispatch_trigger")
class TestStart:
    @pytest.mark.security
    async def test_an_input_over_the_limit_is_refused_before_anything_is_read(self, monkeypatch):
        monkeypatch.setattr(settings, "WORKFLOW_RUN_MAX_INPUT_BYTES", 10)
        service = WorkflowExecutionService(MagicMock())
        get = AsyncMock()
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=get),
            pytest.raises(WorkflowRunInputTooLargeError) as refused,
        ):
            await service.start(_ctx(), uuid.uuid4(), run_input={"text": "eleven bytes"})
        assert refused.value.details == {"limit_bytes": 10, "size_bytes": 23}
        get.assert_not_awaited()

    @pytest.mark.security
    async def test_starting_an_unreachable_workflow_is_not_found(self):
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError),
        ):
            await service.start(_ctx(), uuid.uuid4())

    @pytest.mark.security
    async def test_a_workflow_this_caller_cannot_reach_is_not_found(self):
        workflow = _workflow()
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=False)),
            pytest.raises(NotFoundError),
        ):
            await service.start(_ctx(), workflow.id)

    async def test_a_real_run_of_an_archived_workflow_is_refused(self):
        """`ARCHIVED` keeps a workflow's history and its past runs but

        refuses new ones - an archived workflow retains its
        `current_version_id`, so without this check a real run of that
        version would still be admitted, defeating archiving as a stop
        switch.
        """
        workflow = _workflow(status=WorkflowStatus.ARCHIVED.value)
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            pytest.raises(WorkflowArchivedError),
        ):
            await service.start(_ctx(), workflow.id)

    async def test_a_test_run_of_an_archived_workflow_is_refused(self):
        """The archived check applies before the `test`-mode draft-graph

        branch too - an archived workflow's draft can still parse and
        validate, so without this check a test run of it would still be
        admitted.
        """
        workflow = _workflow(status=WorkflowStatus.ARCHIVED.value)
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            pytest.raises(WorkflowArchivedError),
        ):
            await service.start(_ctx(), workflow.id, mode=WorkflowRunMode.TEST)

    async def test_a_real_run_with_no_published_version_is_refused(self):
        workflow = _workflow(current_version_id=None, status=WorkflowStatus.DRAFT.value)
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            pytest.raises(WorkflowNotRunnableError),
        ):
            await service.start(_ctx(), workflow.id)

    async def test_a_real_run_whose_published_version_no_longer_resolves_is_refused(self):
        workflow = _workflow()
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{FACADE_PATH}.workflow_repo.get_version", new=AsyncMock(return_value=None)),
            pytest.raises(WorkflowNotRunnableError),
        ):
            await service.start(_ctx(), workflow.id)

    async def test_a_test_run_with_no_valid_draft_graph_is_refused(self):
        workflow = _workflow(draft_graph={})
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            pytest.raises(WorkflowNotRunnableError),
        ):
            await service.start(_ctx(), workflow.id, mode=WorkflowRunMode.TEST)

    async def test_a_real_run_reads_the_published_versions_graph_and_budget(self):
        workflow = _workflow()
        version = _version(budget_limit=Decimal("5.00"))
        created = _run_row(workflow_id=workflow.id, budget_limit=version.budget_limit)
        entry_node_run = MagicMock(id=uuid.uuid4())

        db = MagicMock()
        service = WorkflowExecutionService(db)
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{FACADE_PATH}.workflow_repo.get_version", new=AsyncMock(return_value=version)),
            patch(f"{FACADE_PATH}.workflow_run_repo.lock_admission", new=AsyncMock()),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.sum_reserved_node_work",
                new=AsyncMock(return_value=0),
            ),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.create_run", new=AsyncMock(return_value=created)
            ) as create_run,
            patch(
                f"{FACADE_PATH}.workflow_run_repo.create_node_run",
                new=AsyncMock(return_value=entry_node_run),
            ),
            patch(f"{FACADE_PATH}.dispatch_queue.queue_dispatch", new=AsyncMock()) as queued,
            patch(
                f"{FACADE_PATH}.workflow_run_repo.update_run", new=AsyncMock(return_value=created)
            ),
            patch(f"{FACADE_PATH}.events.append", new=AsyncMock()),
        ):
            result = await service.start(_ctx(), workflow.id)

        assert result.id == created.id
        # The entry node's dispatch is queued in the admitting transaction.
        queued.assert_awaited_once_with(db, run=created, node_run_id=entry_node_run.id)
        assert create_run.await_args.kwargs["workflow_version_id"] == version.id
        assert create_run.await_args.kwargs["budget_limit"] == version.budget_limit

    async def test_a_test_run_snapshots_the_current_draft_and_has_no_version(self):
        workflow = _workflow()
        created = _run_row(
            workflow_id=workflow.id, mode=WorkflowRunMode.TEST.value, workflow_version_id=None
        )
        entry_node_run = MagicMock(id=uuid.uuid4())

        db = MagicMock()
        service = WorkflowExecutionService(db)
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{FACADE_PATH}.workflow_run_repo.lock_admission", new=AsyncMock()),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.sum_reserved_node_work",
                new=AsyncMock(return_value=0),
            ),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.create_run", new=AsyncMock(return_value=created)
            ) as create_run,
            patch(
                f"{FACADE_PATH}.workflow_run_repo.create_node_run",
                new=AsyncMock(return_value=entry_node_run),
            ),
            patch(f"{FACADE_PATH}.dispatch_queue.queue_dispatch", new=AsyncMock()),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.update_run", new=AsyncMock(return_value=created)
            ),
            patch(f"{FACADE_PATH}.events.append", new=AsyncMock()),
        ):
            result = await service.start(_ctx(), workflow.id, mode=WorkflowRunMode.TEST)

        assert result.mode == WorkflowRunMode.TEST.value
        assert create_run.await_args.kwargs["workflow_version_id"] is None
        assert create_run.await_args.kwargs["draft_graph_snapshot"] is not None

    async def test_a_test_run_from_a_second_trigger_snapshots_only_that_branch(self):
        def _step(definition_id: str) -> NodeInstance:
            return NodeInstance(
                id=uuid.uuid4(),
                definition_id=definition_id,
                definition_version=1,
                config={},
                layout=NodePosition(x=0, y=0),
            )

        manual, webhook, after_manual, after_webhook = (
            _step("trigger.manual"),
            _step("trigger.webhook"),
            _step("core.output"),
            _step("core.output"),
        )
        draft = WorkflowGraph(
            entry_node_id=manual.id,
            nodes=(manual, webhook, after_manual, after_webhook),
            edges=(
                Edge(
                    id=uuid.uuid4(),
                    source_node_id=manual.id,
                    source_port="out",
                    target_node_id=after_manual.id,
                    target_port="in",
                ),
                Edge(
                    id=uuid.uuid4(),
                    source_node_id=webhook.id,
                    source_port="out",
                    target_node_id=after_webhook.id,
                    target_port="in",
                ),
            ),
        )
        workflow = _workflow(draft_graph=draft.model_dump(mode="json"))
        created = _run_row(
            workflow_id=workflow.id, mode=WorkflowRunMode.TEST.value, workflow_version_id=None
        )

        db = MagicMock()
        service = WorkflowExecutionService(db)
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{FACADE_PATH}.workflow_run_repo.lock_admission", new=AsyncMock()),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.sum_reserved_node_work",
                new=AsyncMock(return_value=0),
            ),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.create_run", new=AsyncMock(return_value=created)
            ) as create_run,
            patch(
                f"{FACADE_PATH}.workflow_run_repo.create_node_run",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ),
            patch(f"{FACADE_PATH}.dispatch_queue.queue_dispatch", new=AsyncMock()),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.update_run", new=AsyncMock(return_value=created)
            ),
            patch(f"{FACADE_PATH}.events.append", new=AsyncMock()),
        ):
            await service.start(
                _ctx(), workflow.id, mode=WorkflowRunMode.TEST, entry_node_id=webhook.id
            )

        snapshot = WorkflowGraph.model_validate(
            create_run.await_args.kwargs["draft_graph_snapshot"]
        )
        assert snapshot.entry_node_id == webhook.id
        assert {node.id for node in snapshot.nodes} == {webhook.id, after_webhook.id}

    async def test_a_start_over_the_admission_quota_writes_nothing(self):
        # The quota is charged after the graph resolves but before any row is
        # written, so a refused start leaves no run, node run or outbox behind.
        workflow = _workflow()
        version = _version()

        db = MagicMock()
        service = WorkflowExecutionService(db)
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{FACADE_PATH}.workflow_repo.get_version", new=AsyncMock(return_value=version)),
            patch(f"{FACADE_PATH}.workflow_run_repo.lock_admission", new=AsyncMock()),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.sum_reserved_node_work",
                new=AsyncMock(return_value=settings.WORKFLOW_MAX_ACTIVE_NODE_RUNS_PER_ORG),
            ),
            patch(f"{FACADE_PATH}.workflow_run_repo.create_run", new=AsyncMock()) as create_run,
            pytest.raises(WorkflowAdmissionQuotaError) as refused,
        ):
            await service.start(_ctx(), workflow.id)
        assert refused.value.status_code == 429
        assert refused.value.details["scope"] == "organization"
        create_run.assert_not_awaited()

    @pytest.mark.security
    @pytest.mark.parametrize("trigger_id", ["core.input", "trigger.manual"], ids=["api", "manual"])
    async def test_an_input_that_does_not_fit_the_declared_fields_is_refused_unwritten(
        self, trigger_id
    ):
        entry = NodeInstance(
            id=uuid.uuid4(),
            definition_id=trigger_id,
            definition_version=1,
            config={"fields": [{"name": "seats", "type": "integer"}]},
            layout=NodePosition(x=0, y=0),
        )
        graph = WorkflowGraph(entry_node_id=entry.id, nodes=(entry,))
        # A Manual workflow is started through the API's door too - by the console.
        workflow = _workflow(live_trigger=trigger_id)
        version = _version(graph=graph.model_dump(mode="json"))

        service = WorkflowExecutionService(MagicMock())
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{FACADE_PATH}.workflow_repo.get_version", new=AsyncMock(return_value=version)),
            patch(f"{FACADE_PATH}.workflow_run_repo.create_run", new=AsyncMock()) as create_run,
            pytest.raises(WorkflowRunInputInvalidError) as refused,
        ):
            await service.start(_ctx(), workflow.id, run_input={"seats": "three"})
        assert refused.value.status_code == 422
        assert [problem["field"] for problem in refused.value.details["problems"]] == ["seats"]
        create_run.assert_not_awaited()

    @pytest.mark.parametrize(
        "make_source,expected_kind",
        [
            (lambda: FileRef(file_id=uuid.uuid4(), content_type="text/plain", byte_size=1), "file"),
            (lambda: TableIORef(table_id=uuid.uuid4(), schema_version=1), "table"),
        ],
    )
    async def test_a_fileref_or_tableref_binding_is_recorded_as_a_resource_ref(
        self, make_source, expected_kind
    ):
        node = NodeInstance(
            id=uuid.uuid4(),
            definition_id="debug.echo",
            definition_version=1,
            config={},
            layout=NodePosition(x=0, y=0),
        )
        binding = Binding(target_node_id=node.id, target_field="message", source=make_source())
        # A second, non-file/table binding alongside it: `_record_resource_refs`
        # must skip a binding that matches neither `isinstance` check and keep
        # going, not just handle a graph with exactly one relevant binding.
        literal_binding = Binding(
            target_node_id=node.id, target_field="other", source=LiteralValue(value="x")
        )
        graph = WorkflowGraph(
            entry_node_id=node.id, nodes=(node,), bindings=(literal_binding, binding)
        )
        workflow = _workflow(draft_graph=graph.model_dump(mode="json"))
        created = _run_row(
            workflow_id=workflow.id, mode=WorkflowRunMode.TEST.value, workflow_version_id=None
        )
        entry_node_run = MagicMock(id=uuid.uuid4())

        db = MagicMock()
        service = WorkflowExecutionService(db)
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{FACADE_PATH}.workflow_run_repo.lock_admission", new=AsyncMock()),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.sum_reserved_node_work",
                new=AsyncMock(return_value=0),
            ),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.create_run", new=AsyncMock(return_value=created)
            ),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.create_node_run",
                new=AsyncMock(return_value=entry_node_run),
            ),
            patch(f"{FACADE_PATH}.dispatch_queue.queue_dispatch", new=AsyncMock()),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.update_run", new=AsyncMock(return_value=created)
            ),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.create_resource_ref", new=AsyncMock()
            ) as create_ref,
            patch(f"{FACADE_PATH}.events.append", new=AsyncMock()),
            # This test is about `_record_resource_refs` walking the graph's
            # bindings, not about `validate_graph`'s own rules - the second,
            # non-file/table binding targets a field name chosen to exercise
            # the "skip a non-matching source" branch, not to be a
            # structurally valid graph. `validate_graph` has its own tests.
            patch(f"{FACADE_PATH}.validate_graph", new=AsyncMock(return_value=graph)),
            patch(f"{FACADE_PATH}.file_binding_problems", new=AsyncMock(return_value=[])),
        ):
            await service.start(_ctx(), workflow.id, mode=WorkflowRunMode.TEST)

        create_ref.assert_awaited_once()
        assert create_ref.await_args.kwargs["kind"] == expected_kind

    @pytest.mark.security
    async def test_a_test_run_by_a_caller_without_edit_access_is_refused(self):
        """`workflows:run` (even as widened by a mere `USE` grant) is not

        enough to trigger unreviewed, unpublished draft side effects - a
        test run is held to the same `workflows:edit` bar as `publish`.
        """
        workflow = _workflow()
        service = WorkflowExecutionService(MagicMock())

        async def _resolve_access(
            db: object, ctx: object, resource: object, perm: Perm, *, resource_type: object
        ) -> bool:
            return perm is not Perm.WORKFLOWS_EDIT

        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(side_effect=_resolve_access)),
            pytest.raises(NotFoundError),
        ):
            await service.start(_ctx(), workflow.id, mode=WorkflowRunMode.TEST)

    async def test_a_structurally_invalid_draft_is_refused_with_the_publish_time_error(self):
        """A draft that parses as a `WorkflowGraph` but fails a publish-time

        rule (here, a binding to a field the target node does not have) is
        refused with the same `GraphValidationError` `publish` itself
        raises - not collapsed into the vaguer `WorkflowNotRunnableError` -
        so nothing dispatches a graph `begin_attempt` cannot run.
        """
        node = NodeInstance(
            id=uuid.uuid4(),
            definition_id="debug.echo",
            definition_version=1,
            config={},
            layout=NodePosition(x=0, y=0),
        )
        bad_binding = Binding(
            target_node_id=node.id, target_field="no_such_field", source=LiteralValue(value="x")
        )
        graph = WorkflowGraph(entry_node_id=node.id, nodes=(node,), bindings=(bad_binding,))
        workflow = _workflow(draft_graph=graph.model_dump(mode="json"))
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            pytest.raises(GraphValidationError),
        ):
            await service.start(_ctx(), workflow.id, mode=WorkflowRunMode.TEST)


class TestCancel:
    async def test_cancelling_a_run_that_does_not_exist_is_not_found(self):
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(
                f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=None)
            ) as get_run,
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run_for_update", new=AsyncMock()) as lock,
            pytest.raises(WorkflowRunNotFoundError),
        ):
            await service.cancel(_ctx(), uuid.uuid4())
        assert get_run.await_args.kwargs["organization_id"] == _ORGANIZATION_ID
        lock.assert_not_called()

    @pytest.mark.security
    async def test_cancelling_a_run_the_caller_cannot_reach_is_not_found(self):
        run = _run_row()
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run_for_update", new=AsyncMock()) as lock,
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=None)),
            pytest.raises(WorkflowRunNotFoundError),
        ):
            await service.cancel(_ctx(), run.id)
        # Refused before any lock: an outsider cannot wait on a hidden run's lock.
        lock.assert_not_called()

    @pytest.mark.security
    async def test_cancelling_another_organizations_run_id_is_not_found_and_locks_nothing(self):
        """A caller-controlled run id naming another tenant's row must come

        back indistinguishable from a nonexistent one, before any foreign
        row is locked or inspected - the scoped lookup itself is what
        refuses it, not a permission check that runs after the row (and its
        real `workflow_id`) has already been read into this transaction.
        """
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(
                f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=None)
            ) as get_run,
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run_for_update", new=AsyncMock()) as lock,
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock()) as workflow_get,
            pytest.raises(WorkflowRunNotFoundError),
        ):
            await service.cancel(_ctx(), uuid.uuid4())
        get_run.assert_awaited_once()
        assert get_run.await_args.kwargs["organization_id"] == _ORGANIZATION_ID
        lock.assert_not_called()
        workflow_get.assert_not_called()

    async def test_cancelling_an_already_terminal_run_is_refused(self):
        run = _run_row(status=WorkflowRunStatus.SUCCEEDED.value)
        workflow = _workflow(id=run.workflow_id)
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.get_run_for_update",
                new=AsyncMock(return_value=run),
            ),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            pytest.raises(WorkflowRunAlreadyTerminalError),
        ):
            await service.cancel(_ctx(), run.id)

    async def test_cancelling_a_live_run_closes_its_work_and_marks_it_cancelled(self):
        run = _run_row(status=WorkflowRunStatus.RUNNING.value)
        workflow = _workflow(id=run.workflow_id)
        cancelled = _run_row(id=run.id, status=WorkflowRunStatus.CANCELLED.value)
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.get_run_for_update",
                new=AsyncMock(return_value=run),
            ),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{FACADE_PATH}.cleanup.stop_run_work", new=AsyncMock()) as stopped,
            patch(
                f"{FACADE_PATH}.workflow_run_repo.update_run", new=AsyncMock(return_value=cancelled)
            ) as update_run,
            patch(f"{FACADE_PATH}.events.append", new=AsyncMock()),
            patch(f"{FACADE_PATH}.delivery.deliver_result", new=AsyncMock()) as delivered,
        ):
            result = await service.cancel(_ctx(), run.id)

        assert result.status == WorkflowRunStatus.CANCELLED.value
        # Every live step, request, queued job and parked agent run is closed first.
        stopped.assert_awaited_once()
        assert stopped.await_args.kwargs["run"] is run
        assert (
            update_run.await_args.kwargs["update_data"]["ended_at"]
            == stopped.await_args.kwargs["now"]
        )
        # The run's answer goes to its conversation, if it was started in one.
        delivered.assert_awaited_once_with(service.db, run=cancelled)

    async def test_a_run_gone_between_the_read_and_the_lock_is_not_found(self):
        run = _run_row()
        workflow = _workflow(id=run.workflow_id)
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.get_run_for_update",
                new=AsyncMock(return_value=None),
            ),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            pytest.raises(WorkflowRunNotFoundError),
        ):
            await service.cancel(_ctx(), run.id)


class TestResolveStep:
    def _step(self, run, **overrides):
        step = MagicMock(
            id=uuid.uuid4(),
            workflow_run_id=run.id,
            organization_id=_ORGANIZATION_ID,
            node_instance_id=uuid.uuid4(),
            status="needs_attention",
        )
        for field, value in overrides.items():
            setattr(step, field, value)
        return step

    def _patched(self, run, step, *, locked_step="same", dispatched=None):
        workflow = _workflow(id=run.workflow_id)
        locked = step if locked_step == "same" else locked_step
        return [
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.get_run_for_update",
                new=AsyncMock(return_value=run),
            ),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.get_node_run_by_id",
                new=AsyncMock(return_value=step),
            ),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.get_node_run_by_id_for_update",
                new=AsyncMock(return_value=locked),
            ),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.get_latest_attempt",
                new=AsyncMock(return_value=MagicMock(attempt_no=3)),
            ),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(
                f"{FACADE_PATH}.dispatcher.resolve_needs_attention",
                new=dispatched if dispatched is not None else AsyncMock(return_value=[]),
            ),
            patch(f"{FACADE_PATH}.refresh_run_status", new=AsyncMock(return_value=run)),
        ]

    async def _call(self, run, step, patches, *, ctx=None, choice="run_again"):
        from contextlib import ExitStack

        service = WorkflowExecutionService(MagicMock())
        with ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            return await service.resolve_step(
                ctx or _ctx(), run.id, step.id, WorkflowStepResolve(choice=choice)
            )

    async def test_a_step_that_vanished_between_the_read_and_the_lock_is_not_resolvable(self):
        run = _run_row()
        step = self._step(run)
        with pytest.raises(WorkflowStepNotResolvableError) as refused:
            await self._call(run, step, self._patched(run, step, locked_step=None))
        assert refused.value.details["reason"] == "not_needing_attention"

    async def test_a_run_gone_between_the_read_and_the_lock_is_not_found(self):
        run = _run_row()
        step = self._step(run)
        patches = self._patched(run, step)
        patches[1] = patch(
            f"{FACADE_PATH}.workflow_run_repo.get_run_for_update",
            new=AsyncMock(return_value=None),
        )
        with pytest.raises(WorkflowRunNotFoundError):
            await self._call(run, step, patches)

    @pytest.mark.security
    async def test_an_unknown_step_locks_nothing(self):
        run = _run_row()
        patches = self._patched(run, None)
        from contextlib import ExitStack

        with ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            lock = stack.enter_context(
                patch(f"{FACADE_PATH}.workflow_run_repo.get_run_for_update", new=AsyncMock())
            )
            with pytest.raises(WorkflowStepNotFoundError):
                await WorkflowExecutionService(MagicMock()).resolve_step(
                    _ctx(), run.id, uuid.uuid4(), WorkflowStepResolve(choice="fail_run")
                )
        lock.assert_not_called()

    async def test_resolving_a_step_resolves_it_re_reads_the_status_and_audits_it(self):
        run = _run_row(status=WorkflowRunStatus.NEEDS_ATTENTION.value)
        step = self._step(run)
        dispatched = AsyncMock(return_value=[])
        ctx = _ctx()
        with patch(f"{FACADE_PATH}.record_audit", new=AsyncMock()) as audited:
            result = await self._call(
                run,
                step,
                self._patched(run, step, dispatched=dispatched),
                ctx=ctx,
                choice="fail_run",
            )

        assert result.id == run.id
        assert dispatched.await_args.kwargs["choice"] == "fail_run"
        assert dispatched.await_args.kwargs["node_run"] is step
        audited.assert_awaited_once()
        kwargs = audited.await_args.kwargs
        assert kwargs["action"] == "workflow_run.step_resolved"
        assert kwargs["target_type"] == "workflow_run"
        assert kwargs["target_id"] == str(run.id)
        assert kwargs["actor_user_id"] == ctx.subject_id
        assert kwargs["details"] == {
            "node_run_id": str(step.id),
            "node_instance_id": str(step.node_instance_id),
            "attempt_no": 3,
            "choice": "fail_run",
        }

    async def test_a_step_with_no_recorded_try_is_audited_as_attempt_zero(self):
        run = _run_row()
        step = self._step(run)
        patches = self._patched(run, step)
        patches[4] = patch(
            f"{FACADE_PATH}.workflow_run_repo.get_latest_attempt",
            new=AsyncMock(return_value=None),
        )
        with patch(f"{FACADE_PATH}.record_audit", new=AsyncMock()) as audited:
            await self._call(run, step, patches)
        assert audited.await_args.kwargs["details"]["attempt_no"] == 0


class TestGet:
    @pytest.mark.security
    async def test_a_run_in_another_organizations_workflow_is_not_found(self):
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=None)),
            pytest.raises(WorkflowRunNotFoundError),
        ):
            await service.get(_ctx(), uuid.uuid4())

    async def test_returns_the_run_when_reachable(self):
        run = _run_row()
        workflow = _workflow(id=run.workflow_id)
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
        ):
            result = await service.get(_ctx(), run.id)
        assert result.id == run.id

    @pytest.mark.security
    @pytest.mark.parametrize(
        ("mode", "may_edit", "may_run", "starter", "expected"),
        [
            # The starter who may run it, an editor by grant (no run permission),
            # and a runner who is neither: what `cancel` would let each do.
            (WorkflowRunMode.REAL, False, True, True, True),
            (WorkflowRunMode.REAL, True, False, False, True),
            (WorkflowRunMode.REAL, False, True, False, False),
            (WorkflowRunMode.REAL, False, False, True, False),
            # A test run is its editors' to resolve, whoever started it.
            (WorkflowRunMode.TEST, False, True, True, False),
            (WorkflowRunMode.TEST, True, False, False, True),
        ],
    )
    async def test_it_says_whether_this_caller_may_cancel_and_resolve(
        self, mode, may_edit, may_run, starter, expected
    ):
        ctx = _ctx()
        run = _run_row(
            mode=mode.value, execution_principal_user_id=ctx.user_id if starter else uuid.uuid4()
        )
        workflow = _workflow(id=run.workflow_id)
        service = WorkflowExecutionService(MagicMock())

        async def _resolve_access(
            db: object, ctx: object, resource: object, perm: Perm, *, resource_type: object
        ) -> bool:
            return {Perm.WORKFLOWS_EDIT: may_edit, Perm.WORKFLOWS_RUN: may_run}.get(perm, True)

        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(side_effect=_resolve_access)),
        ):
            result = await service.get(ctx, run.id)
        assert result.can_cancel is expected


class TestList:
    @pytest.mark.security
    async def test_listing_narrowed_to_an_unreachable_workflow_is_not_found(self):
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError),
        ):
            await service.list(_ctx(), workflow_id=uuid.uuid4())

    async def test_an_unfiltered_list_is_narrowed_to_visible_workflows(self):
        service = WorkflowExecutionService(MagicMock())
        ctx = _ctx(OrgRoleName.MEMBER.value)
        visible_ids = [uuid.uuid4()]
        with (
            patch(
                f"{FACADE_PATH}.visible_resource_ids", new=AsyncMock(return_value=visible_ids)
            ) as visible,
            patch(
                f"{FACADE_PATH}.workflow_run_repo.list_runs", new=AsyncMock(return_value=([], 0))
            ) as list_runs,
        ):
            result = await service.list(ctx)

        visible.assert_awaited_once()
        assert list_runs.await_args.kwargs["visible_to_user_id"] == ctx.user_id
        assert list_runs.await_args.kwargs["shared_workflow_ids"] == visible_ids
        assert result.total == 0

    async def test_a_role_that_reaches_every_workflow_lists_unfiltered(self):
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(f"{FACADE_PATH}.visible_resource_ids", new=AsyncMock(return_value=None)),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.list_runs", new=AsyncMock(return_value=([], 0))
            ) as list_runs,
        ):
            await service.list(_ctx())
        assert list_runs.await_args.kwargs["visible_to_user_id"] is None

    async def test_a_workflow_scoped_list_is_authorized_against_that_workflow(self):
        workflow = _workflow()
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.list_runs", new=AsyncMock(return_value=([], 0))
            ) as list_runs,
        ):
            await service.list(_ctx(), workflow_id=workflow.id)
        assert list_runs.await_args.kwargs["workflow_id"] == workflow.id


class TestEventsSince:
    async def test_reads_events_after_the_given_cursor(self):
        run = _run_row()
        workflow = _workflow(id=run.workflow_id)
        event_row = MagicMock(
            id=uuid.uuid4(),
            seq=5,
            kind="node_completed",
            node_run_id=None,
            payload={},
            created_at=datetime.now(UTC),
        )
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.list_events_since",
                new=AsyncMock(return_value=[event_row]),
            ),
        ):
            result = await service.events_since(_ctx(), run.id, after="3")

        assert result.items[0].seq == 5
        assert result.next_cursor == "5"

    async def test_no_new_events_carries_the_same_cursor_forward(self):
        run = _run_row()
        workflow = _workflow(id=run.workflow_id)
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.list_events_since", new=AsyncMock(return_value=[])
            ),
        ):
            result = await service.events_since(_ctx(), run.id, after="7")

        assert result.items == []
        assert result.next_cursor == "7"


@pytest.mark.usefixtures("_no_dispatch_trigger")
class TestThePublicOrigin:
    """Whether an outsider is behind a run's chain, stored on its row (D18a(5)).

    Every surface ends in `_admit`, so the flag stored there is the one a run's
    dispatch, its retries and the runs it causes all read.
    """

    @classmethod
    async def _stored(cls, start) -> bool:
        return (await cls._stored_row(start))["public_origin"]

    @staticmethod
    async def _stored_row(start) -> dict[str, object]:
        created = _run_row()
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=_workflow())),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(
                f"{FACADE_PATH}.workflow_repo.get_version", new=AsyncMock(return_value=_version())
            ),
            patch(f"{FACADE_PATH}.workflow_run_repo.lock_admission", new=AsyncMock()),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.sum_reserved_node_work",
                new=AsyncMock(return_value=0),
            ),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.create_run", new=AsyncMock(return_value=created)
            ) as create_run,
            patch(
                f"{FACADE_PATH}.workflow_run_repo.create_node_run",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ),
            patch(f"{FACADE_PATH}.dispatch_queue.queue_dispatch", new=AsyncMock()),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.update_run", new=AsyncMock(return_value=created)
            ),
            patch(f"{FACADE_PATH}.events.append", new=AsyncMock()),
        ):
            await start(WorkflowExecutionService(MagicMock()))
        return create_run.await_args.kwargs

    @pytest.mark.security
    async def test_a_door_run_is_stored_public(self):
        stored = await self._stored(
            lambda service: service.admit_pinned(
                _ctx(),
                _workflow(),
                _version(),
                triggered_by=WorkflowRunTrigger.WEBHOOK,
                run_input={},
            )
        )

        assert stored is True

    @pytest.mark.security
    async def test_a_run_caused_by_a_public_run_is_stored_public(self):
        root = uuid.uuid4()
        stored = await self._stored(
            lambda service: service.admit_pinned(
                _ctx(),
                _workflow(),
                _version(),
                triggered_by=WorkflowRunTrigger.TABLE_CREATED,
                run_input={},
                causation=Causation(
                    root_run_id=root,
                    causation_run_id=root,
                    visited_trigger_ids=[],
                    depth=1,
                    public_origin=True,
                ),
            )
        )

        assert stored is True

    async def test_an_api_run_is_stored_not_public(self):
        stored = await self._stored(lambda service: service.start(_ctx(), uuid.uuid4()))

        assert stored is False

    @pytest.mark.security
    async def test_a_run_started_while_impersonating_is_stored_so(self):
        """A worker runs its nodes long after the request is gone: the row says it."""
        set_impersonator(uuid.uuid4())
        try:
            stored = await self._stored_row(lambda service: service.start(_ctx(), uuid.uuid4()))
        finally:
            set_impersonator(None)

        assert stored["impersonated"] is True

    async def test_an_ordinary_run_is_stored_not_impersonated(self):
        stored = await self._stored_row(lambda service: service.start(_ctx(), uuid.uuid4()))

        assert stored["impersonated"] is False

    @pytest.mark.security
    async def test_a_run_caused_by_an_impersonated_run_is_stored_impersonated(self):
        root = uuid.uuid4()
        stored = await self._stored_row(
            lambda service: service.admit_pinned(
                _ctx(),
                _workflow(),
                _version(),
                triggered_by=WorkflowRunTrigger.WORKFLOW_CALL,
                run_input={},
                causation=Causation(
                    root_run_id=root,
                    causation_run_id=root,
                    visited_trigger_ids=[],
                    depth=1,
                    impersonated=True,
                ),
            )
        )

        assert stored["impersonated"] is True


class TestTheAppDoor:
    """A page's declared action starts a run through the `app` door (#1976)."""

    @staticmethod
    async def _start(live_trigger: str | None, **kwargs: object):
        workflow = _workflow(live_trigger=live_trigger)
        created = _run_row(workflow_id=workflow.id)
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(
                f"{FACADE_PATH}.workflow_repo.get_version", new=AsyncMock(return_value=_version())
            ),
            patch(f"{FACADE_PATH}.workflow_run_repo.lock_admission", new=AsyncMock()),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.sum_reserved_node_work",
                new=AsyncMock(return_value=0),
            ),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.create_run", new=AsyncMock(return_value=created)
            ) as create_run,
            patch(
                f"{FACADE_PATH}.workflow_run_repo.create_node_run",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ),
            patch(f"{FACADE_PATH}.dispatch_queue.queue_dispatch", new=AsyncMock()),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.update_run", new=AsyncMock(return_value=created)
            ),
            patch(f"{FACADE_PATH}.events.append", new=AsyncMock()),
        ):
            await WorkflowExecutionService(MagicMock()).start(
                _ctx(), workflow.id, triggered_by=WorkflowRunTrigger.APP, **kwargs
            )
        return create_run.await_args.kwargs

    @pytest.mark.parametrize("trigger", ["core.input", "trigger.manual"])
    async def test_it_admits_only_what_a_person_starts_by_hand(self, trigger):
        stored = await self._start(trigger)

        assert stored["triggered_by"] == "app"

    @pytest.mark.security
    @pytest.mark.parametrize(
        "trigger",
        [
            None,
            "trigger.webhook",
            "trigger.schedule",
            "trigger.chat",
            "trigger.form",
            "trigger.workflow_call",
        ],
    )
    async def test_it_refuses_every_other_trigger_and_an_entry_that_is_none(self, trigger):
        with pytest.raises(WorkflowTriggerMismatchError) as refused:
            await self._start(trigger)

        assert refused.value.details["door"] == "app"

    async def test_it_records_the_page_and_version_the_run_came_from(self):
        page = uuid.uuid4()

        stored = await self._start(
            "trigger.manual", source_artifact_id=page, source_version_number=4
        )

        assert (stored["source_artifact_id"], stored["source_version_number"]) == (page, 4)

    async def test_a_start_from_anywhere_else_records_no_page(self):
        stored = await self._start("trigger.manual")

        assert (stored["source_artifact_id"], stored["source_version_number"]) == (None, None)

    @pytest.mark.security
    async def test_an_app_run_is_not_stored_public(self):
        stored = await self._start("trigger.manual")

        assert stored["public_origin"] is False


class TestNodeRunRead:
    def test_a_step_reports_its_tries_its_spend_and_the_error_it_last_failed_with(self):
        row = NodeRun(
            id=uuid.uuid4(),
            node_instance_id=uuid.uuid4(),
            scope_path=[{"loop_node_id": "l", "index": 2}],
            status="failed",
            waiting_reason=None,
        )

        def attempt(
            no: int, status: str, code: str | None, cost: str, guarantee: str | None = "idempotent"
        ) -> NodeAttempt:
            return NodeAttempt(
                node_run_id=row.id,
                attempt_no=no,
                status=status,
                retry_guarantee=guarantee,
                result={"status": status, "error": {"code": code, "message": "m"}}
                if code
                else None,
                cost=Decimal(cost),
            )

        read = node_run_read(
            row,
            [
                attempt(1, "failed", "FIRST", "0.10"),
                attempt(2, "failed", "LAST", "0.05"),
                # The dispatcher's own record of an output, not a try.
                attempt(3, "completed", None, "0", guarantee=None),
            ],
        )

        assert read.attempts == 2 and read.cost == pytest.approx(0.15)
        assert read.error == {"code": "LAST", "message": "m"}
        assert node_run_read(row, []).error is None

        # A step that parked and was woken tried once: the wake carries the same try on.
        parked = NodeAttempt(
            node_run_id=row.id,
            attempt_no=1,
            status="completed",
            retry_guarantee="idempotent",
            result={"status": "waiting", "reason": "external_event", "resume_token": "t"},
            cost=Decimal(0),
        )
        woken = NodeAttempt(
            node_run_id=row.id,
            attempt_no=2,
            status="completed",
            retry_guarantee="idempotent",
            result={"status": "completed", "output": {"run_id": "r"}},
            cost=Decimal(0),
        )
        assert node_run_read(row, [parked, woken]).attempts == 1

    def test_a_step_needing_attention_shows_its_last_tries_status_and_a_late_output(self):
        row = NodeRun(
            id=uuid.uuid4(),
            node_instance_id=uuid.uuid4(),
            scope_path=[],
            status="needs_attention",
            waiting_reason=None,
        )
        uncertain = NodeAttempt(
            node_run_id=row.id,
            attempt_no=1,
            status="uncertain",
            retry_guarantee="none",
            result={"status": "uncertain", "detail": "unsure"},
            late_result={"status": "completed", "output": {"sent": True}},
            cost=Decimal(0),
        )

        read = node_run_read(row, [uncertain])

        assert read.last_attempt_status == "uncertain"
        assert read.late_output == {"sent": True}
        assert node_run_read(row, []).last_attempt_status is None
        assert node_run_read(row, []).late_output is None
        uncertain.late_result = None
        assert node_run_read(row, [uncertain]).late_output is None


@pytest.mark.security
@pytest.mark.parametrize("parent_state", ["missing", "step_missing", "foreign", "cancelled"])
async def test_call_admission_refuses_a_parent_that_disappeared_or_stopped(parent_state):
    service = WorkflowExecutionService(MagicMock())
    parent = _run_row(status="cancelled" if parent_state == "cancelled" else "running")
    if parent_state == "foreign":
        parent.organization_id = uuid.uuid4()
    error = (
        WorkflowRunAlreadyTerminalError if parent_state == "cancelled" else WorkflowNotRunnableError
    )
    with (
        patch(
            f"{FACADE_PATH}.workflow_run_repo.get_node_run_by_id",
            new=AsyncMock(
                return_value=None
                if parent_state == "step_missing"
                else MagicMock(workflow_run_id=parent.id)
            ),
        ),
        patch(
            f"{FACADE_PATH}.workflow_run_repo.get_run_by_id_for_update",
            new=AsyncMock(return_value=None if parent_state == "missing" else parent),
        ),
        patch.object(service, "_admit", new=AsyncMock()) as admit,
        pytest.raises(error),
    ):
        await service.admit_call(
            _ctx(),
            _workflow(),
            _version(),
            run_input={},
            parent_node_run_id=uuid.uuid4(),
            causation=Causation(
                root_run_id=uuid.uuid4(),
                causation_run_id=parent.id,
                visited_trigger_ids=[],
                depth=1,
            ),
        )
    admit.assert_not_awaited()


@pytest.mark.parametrize("hold", [None, Decimal("0")])
@pytest.mark.security
async def test_call_admission_with_nothing_free_waits_instead_of_admitting_without_budget(hold):
    """No try of the calling step to move a hold from (or one holding nothing): refused."""
    service = WorkflowExecutionService(MagicMock())
    parent = _run_row(budget_limit=Decimal("1"))
    attempt = None if hold is None else MagicMock(status="in_flight", reserved_usd=hold)
    with (
        patch(
            f"{FACADE_PATH}.workflow_run_repo.get_node_run_by_id",
            new=AsyncMock(return_value=MagicMock(workflow_run_id=parent.id)),
        ),
        patch(
            f"{FACADE_PATH}.workflow_run_repo.get_run_by_id_for_update",
            new=AsyncMock(return_value=parent),
        ),
        patch(f"{FACADE_PATH}.budget.unreserved", new=AsyncMock(return_value=Decimal("0"))),
        patch(
            f"{FACADE_PATH}.workflow_run_repo.get_latest_attempt",
            new=AsyncMock(return_value=attempt),
        ),
        patch.object(service, "_admit", new=AsyncMock()) as admit,
        pytest.raises(WorkflowBudgetHeldError),
    ):
        await service.admit_call(
            _ctx(),
            _workflow(),
            _version(),
            run_input={},
            parent_node_run_id=uuid.uuid4(),
            causation=Causation(
                root_run_id=uuid.uuid4(),
                causation_run_id=parent.id,
                visited_trigger_ids=[],
                depth=1,
            ),
        )
    admit.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize(
    "payload",
    [
        {"value": "\x00"},
        {"nested": [{"\x00key": "value"}]},
        {"value": "\ud800"},
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": object()},
    ],
)
def test_input_rejects_values_postgres_jsonb_cannot_store(payload):
    from app.services.workflow_execution.facade import _checked_input

    with pytest.raises(WorkflowRunInputInvalidError) as refused:
        _checked_input(payload)
    assert refused.value.status_code == 422
    assert [(p["field"], p["type"]) for p in refused.value.details["problems"]] == [
        ("input", "json_invalid")
    ]


def test_input_accepts_literal_escape_text_and_multilingual_strings():
    from app.services.workflow_execution.facade import _checked_input

    payload = {"value": "literal \\u0000 and 日本語", "tuple": (True, 42)}
    assert _checked_input(payload) == payload
