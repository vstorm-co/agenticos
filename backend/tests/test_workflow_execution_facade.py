"""`app.services.workflow_execution.facade.WorkflowExecutionService`.

The repository and `resolve_access`/`visible_resource_ids` are mocked at the
database edge, matching `test_workflow_registry_service.py`'s bargain for the
sibling service. `_trigger_dispatch` (the low-latency direct trigger) is
patched to a no-op: its own mechanics belong to `workflow_tasks.py` and the
dispatcher's own tests, and constructing a real Prefect flow call here would
test infrastructure this module does not own.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.resource_grant import Visibility
from app.db.models.workflow import WorkflowStatus
from app.db.models.workflow_run import WorkflowRunMode, WorkflowRunStatus
from app.services.workflow_execution.exceptions import (
    WorkflowNotRunnableError,
    WorkflowRunAlreadyTerminalError,
    WorkflowRunNotFoundError,
)
from app.services.workflow_execution.facade import WorkflowExecutionService
from app.services.workflow_registry import WorkflowArchivedError
from app.workflows.contracts.io import Binding, FileRef, LiteralValue, TableIORef
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph

pytestmark = pytest.mark.anyio

FACADE_PATH = "app.services.workflow_execution.facade"

_ORGANIZATION_ID = uuid.uuid4()


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
    run.root_run_id = run.id
    run.causation_run_id = None
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
    with patch.object(WorkflowExecutionService, "_trigger_dispatch", MagicMock()):
        yield


@pytest.mark.usefixtures("_no_dispatch_trigger")
class TestStart:
    async def test_starting_an_unreachable_workflow_is_not_found(self):
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError),
        ):
            await service.start(_ctx(), uuid.uuid4())

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
            patch(
                f"{FACADE_PATH}.workflow_run_repo.create_run", new=AsyncMock(return_value=created)
            ) as create_run,
            patch(
                f"{FACADE_PATH}.workflow_run_repo.create_node_run",
                new=AsyncMock(return_value=entry_node_run),
            ),
            patch(f"{FACADE_PATH}.workflow_run_repo.create_outbox", new=AsyncMock()),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.update_run", new=AsyncMock(return_value=created)
            ),
            patch(f"{FACADE_PATH}.events.append", new=AsyncMock()),
        ):
            result = await service.start(_ctx(), workflow.id)

        assert result.id == created.id
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
            patch(
                f"{FACADE_PATH}.workflow_run_repo.create_run", new=AsyncMock(return_value=created)
            ) as create_run,
            patch(
                f"{FACADE_PATH}.workflow_run_repo.create_node_run",
                new=AsyncMock(return_value=entry_node_run),
            ),
            patch(f"{FACADE_PATH}.workflow_run_repo.create_outbox", new=AsyncMock()),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.update_run", new=AsyncMock(return_value=created)
            ),
            patch(f"{FACADE_PATH}.events.append", new=AsyncMock()),
        ):
            result = await service.start(_ctx(), workflow.id, mode=WorkflowRunMode.TEST)

        assert result.mode == WorkflowRunMode.TEST.value
        assert create_run.await_args.kwargs["workflow_version_id"] is None
        assert create_run.await_args.kwargs["draft_graph_snapshot"] is not None

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
            patch(
                f"{FACADE_PATH}.workflow_run_repo.create_run", new=AsyncMock(return_value=created)
            ),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.create_node_run",
                new=AsyncMock(return_value=entry_node_run),
            ),
            patch(f"{FACADE_PATH}.workflow_run_repo.create_outbox", new=AsyncMock()),
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
        ):
            await service.start(_ctx(), workflow.id, mode=WorkflowRunMode.TEST)

        create_ref.assert_awaited_once()
        assert create_ref.await_args.kwargs["kind"] == expected_kind

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
                f"{FACADE_PATH}.workflow_run_repo.get_run_for_update",
                new=AsyncMock(return_value=None),
            ) as get_for_update,
            pytest.raises(WorkflowRunNotFoundError),
        ):
            await service.cancel(_ctx(), uuid.uuid4())
        assert get_for_update.await_args.kwargs["organization_id"] == _ORGANIZATION_ID

    async def test_cancelling_a_run_the_caller_cannot_reach_is_not_found(self):
        run = _run_row()
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(
                f"{FACADE_PATH}.workflow_run_repo.get_run_for_update",
                new=AsyncMock(return_value=run),
            ),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=None)),
            pytest.raises(WorkflowRunNotFoundError),
        ):
            await service.cancel(_ctx(), run.id)

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
                f"{FACADE_PATH}.workflow_run_repo.get_run_for_update",
                new=AsyncMock(return_value=None),
            ) as get_for_update,
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock()) as workflow_get,
            pytest.raises(WorkflowRunNotFoundError),
        ):
            await service.cancel(_ctx(), uuid.uuid4())
        get_for_update.assert_awaited_once()
        assert get_for_update.await_args.kwargs["organization_id"] == _ORGANIZATION_ID
        workflow_get.assert_not_called()

    async def test_cancelling_an_already_terminal_run_is_refused(self):
        run = _run_row(status=WorkflowRunStatus.SUCCEEDED.value)
        workflow = _workflow(id=run.workflow_id)
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(
                f"{FACADE_PATH}.workflow_run_repo.get_run_for_update",
                new=AsyncMock(return_value=run),
            ),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            pytest.raises(WorkflowRunAlreadyTerminalError),
        ):
            await service.cancel(_ctx(), run.id)

    async def test_cancelling_a_live_run_marks_it_cancelled(self):
        run = _run_row(status=WorkflowRunStatus.RUNNING.value)
        workflow = _workflow(id=run.workflow_id)
        cancelled = _run_row(id=run.id, status=WorkflowRunStatus.CANCELLED.value)
        service = WorkflowExecutionService(MagicMock())
        with (
            patch(
                f"{FACADE_PATH}.workflow_run_repo.get_run_for_update",
                new=AsyncMock(return_value=run),
            ),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{FACADE_PATH}.workflow_run_repo.cancel_live_outbox_for_run", new=AsyncMock()),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.update_run", new=AsyncMock(return_value=cancelled)
            ),
            patch(f"{FACADE_PATH}.events.append", new=AsyncMock()),
        ):
            result = await service.cancel(_ctx(), run.id)

        assert result.status == WorkflowRunStatus.CANCELLED.value


class TestGet:
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


class TestList:
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


class TestTriggerDispatch:
    async def test_delegates_to_the_worker_tasks_direct_trigger(self):
        """`_trigger_dispatch` is a thin wrapper - the actual submit-to-the-

        deployment mechanics belong to `workflow_tasks.trigger_dispatch`
        (its own tests), shared with `dispatcher._advance`'s own use of it.
        """
        db = MagicMock()
        service = WorkflowExecutionService(db)
        workflow_run_id, node_run_id = uuid.uuid4(), uuid.uuid4()

        with patch("app.worker.tasks.workflow_tasks.trigger_dispatch") as trigger:
            service._trigger_dispatch(workflow_run_id=workflow_run_id, node_run_id=node_run_id)

        trigger.assert_called_once_with(
            db, workflow_run_id=workflow_run_id, node_run_id=node_run_id
        )
