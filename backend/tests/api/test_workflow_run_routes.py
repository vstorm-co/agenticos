"""Workflow run routes, through the app: the wire contract.

`tests/test_workflow_execution_facade.py` proves what the service does
against a mocked repository; what is left is the handler itself - status
codes, the error envelope, and which routes carry a `require(...)` gate
versus delegate to the service (the `permissions-rbac` skill).
"""

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Response
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.resource_grant import Visibility
from app.db.models.workflow import WorkflowStatus
from app.db.models.workflow_run import WorkflowRunMode, WorkflowRunStatus
from app.main import app
from app.services.workflow_execution.facade import WorkflowExecutionService, _read
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph

pytestmark = pytest.mark.anyio

_ORGANIZATION_ID = uuid.uuid4()

OpenClient = Callable[[], AbstractAsyncContextManager[AsyncClient]]

FACADE_PATH = "app.services.workflow_execution.facade"


def _graph() -> WorkflowGraph:
    entry = NodeInstance(
        id=uuid.uuid4(),
        definition_id="debug.echo",
        definition_version=1,
        config={},
        layout=NodePosition(x=0, y=0),
    )
    return WorkflowGraph(entry_node_id=entry.id, nodes=(entry,))


def _workflow(**overrides: object):
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


def _run_row(**overrides: object):
    run = MagicMock()
    run.id = uuid.uuid4()
    run.workflow_id = uuid.uuid4()
    run.workflow_version_id = uuid.uuid4()
    run.mode = WorkflowRunMode.REAL.value
    # Started over the API, so it answers in no conversation.
    run.reply_conversation_id = None
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
    run.parent_node_run_id = None
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


def _db() -> MagicMock:
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.execute = AsyncMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    return db


def _client_for(role: str) -> Iterator[OpenClient]:
    context = AuthContext(user_id=uuid.uuid4(), organization_id=_ORGANIZATION_ID, role=role)
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_workflow_execution_service] = lambda: (
        WorkflowExecutionService(_db())
    )

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


@pytest.fixture
def owner_client() -> Iterator[OpenClient]:
    yield from _client_for(OrgRoleName.OWNER)


def _url(tail: str = "") -> str:
    return f"{settings.API_V1_STR}/workflow-runs{tail}"


@pytest.fixture(autouse=True)
def _no_dispatch_trigger():
    with patch(
        "app.services.workflow_execution.facade.dispatch_queue.queue_dispatch", new=AsyncMock()
    ):
        yield


class TestStartRoute:
    async def test_starting_a_run_answers_201(self, owner_client: OpenClient):
        workflow = _workflow()
        created = _run_row(workflow_id=workflow.id)
        entry_node_run = MagicMock(id=uuid.uuid4())
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(
                f"{FACADE_PATH}.workflow_repo.get_version",
                new=AsyncMock(
                    return_value=MagicMock(
                        id=workflow.current_version_id,
                        graph=_graph().model_dump(mode="json"),
                        budget_limit=None,
                    )
                ),
            ),
            patch(f"{FACADE_PATH}.workflow_run_repo.lock_admission", new=AsyncMock()),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.sum_reserved_node_work",
                new=AsyncMock(return_value=0),
            ),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.inline_result_bytes",
                new=AsyncMock(return_value=0),
            ),
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
            patch(f"{FACADE_PATH}.events.append", new=AsyncMock()),
        ):
            async with owner_client() as http:
                response = await http.post(_url(), json={"workflow_id": str(workflow.id)})
        assert response.status_code == 201
        assert response.json()["id"] == str(created.id)

    async def test_starting_a_run_over_the_admission_quota_is_429(self, owner_client: OpenClient):
        workflow = _workflow()
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(
                f"{FACADE_PATH}.workflow_repo.get_version",
                new=AsyncMock(
                    return_value=MagicMock(
                        id=workflow.current_version_id,
                        graph=_graph().model_dump(mode="json"),
                        budget_limit=None,
                    )
                ),
            ),
            patch(f"{FACADE_PATH}.workflow_run_repo.lock_admission", new=AsyncMock()),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.sum_reserved_node_work",
                new=AsyncMock(return_value=settings.WORKFLOW_MAX_ACTIVE_NODE_RUNS_PER_ORG),
            ),
        ):
            async with owner_client() as http:
                response = await http.post(_url(), json={"workflow_id": str(workflow.id)})
        assert response.status_code == 429
        assert response.json()["error"]["code"] == "WORKFLOW_ADMISSION_QUOTA_EXCEEDED"

    @pytest.mark.security
    async def test_starting_a_run_of_an_unreachable_workflow_is_not_found(
        self, owner_client: OpenClient
    ):
        with patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=None)):
            async with owner_client() as http:
                response = await http.post(_url(), json={"workflow_id": str(uuid.uuid4())})
        assert response.status_code == 404

    async def test_starting_a_run_with_no_published_version_is_a_409(
        self, owner_client: OpenClient
    ):
        workflow = _workflow(current_version_id=None, status=WorkflowStatus.DRAFT.value)
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
        ):
            async with owner_client() as http:
                response = await http.post(_url(), json={"workflow_id": str(workflow.id)})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "WORKFLOW_NOT_RUNNABLE"


class TestListRoute:
    """The `workflows:view` gate itself is proven generically by
    `tests/api/test_platform_routes.py`'s `CALLS`-driven sweep, which now
    carries a `GET /workflow-runs` entry - not re-proven here."""

    async def test_listing_answers_the_page(self, owner_client: OpenClient):
        run = _run_row()
        with (
            patch(f"{FACADE_PATH}.visible_resource_ids", new=AsyncMock(return_value=None)),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.list_runs", new=AsyncMock(return_value=([run], 1))
            ),
        ):
            async with owner_client() as http:
                response = await http.get(_url())
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == str(run.id)

    async def test_listing_passes_the_filters_through(self, owner_client: OpenClient):
        listed = AsyncMock(return_value=([], 0))
        with (
            patch(f"{FACADE_PATH}.visible_resource_ids", new=AsyncMock(return_value=None)),
            patch(f"{FACADE_PATH}.workflow_run_repo.list_runs", new=listed),
        ):
            async with owner_client() as http:
                response = await http.get(
                    _url(),
                    params=[
                        ("status", "failed"),
                        ("status", "cancelled"),
                        ("mode", "test"),
                        ("triggered_by", "webhook"),
                        ("created_after", "2026-09-01T00:00:00Z"),
                    ],
                )
        assert response.status_code == 200
        filters = listed.await_args.kwargs["filters"]
        assert [item.value for item in filters.statuses] == ["failed", "cancelled"]
        assert (filters.mode.value, filters.triggered_by.value) == ("test", "webhook")
        assert filters.created_after.year == 2026 and filters.created_before is None


class TestRetryRoute:
    async def test_retrying_answers_the_new_run(self, owner_client: OpenClient):
        run = _run_row()
        retry = AsyncMock(return_value=_read(run))
        with patch.object(WorkflowExecutionService, "retry", new=retry):
            async with owner_client() as http:
                response = await http.post(_url(f"/{run.id}/retry"))
        assert response.status_code == 201
        assert response.json()["id"] == str(run.id)
        assert retry.await_args.args[1] == run.id


class TestGetRoute:
    async def test_getting_one_run(self, owner_client: OpenClient):
        run = _run_row()
        workflow = _workflow(id=run.workflow_id)
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
        ):
            async with owner_client() as http:
                response = await http.get(_url(f"/{run.id}"))
        assert response.status_code == 200
        assert response.json()["id"] == str(run.id)

    @pytest.mark.security
    async def test_a_cross_tenant_run_is_not_found(self, owner_client: OpenClient):
        with patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=None)):
            async with owner_client() as http:
                response = await http.get(_url(f"/{uuid.uuid4()}"))
        assert response.status_code == 404


class TestCancelRoute:
    async def test_cancelling_a_live_run(self, owner_client: OpenClient):
        run = _run_row()
        workflow = _workflow(id=run.workflow_id)
        cancelled = _run_row(id=run.id, status=WorkflowRunStatus.CANCELLED.value)
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.get_run_for_update",
                new=AsyncMock(return_value=run),
            ),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{FACADE_PATH}.workflow_run_repo.cancel_live_outbox_for_run", new=AsyncMock()),
            patch(f"{FACADE_PATH}.background_job_repo.cancel_queued_for_payload", new=AsyncMock()),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.list_live_node_runs",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.update_run", new=AsyncMock(return_value=cancelled)
            ),
            patch(f"{FACADE_PATH}.events.append", new=AsyncMock()),
        ):
            async with owner_client() as http:
                response = await http.post(_url(f"/{run.id}/cancel"))
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"

    async def test_cancelling_an_already_terminal_run_is_a_409(self, owner_client: OpenClient):
        run = _run_row(status=WorkflowRunStatus.SUCCEEDED.value)
        workflow = _workflow(id=run.workflow_id)
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.get_run_for_update",
                new=AsyncMock(return_value=run),
            ),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
        ):
            async with owner_client() as http:
                response = await http.post(_url(f"/{run.id}/cancel"))
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "WORKFLOW_RUN_TERMINAL"


class TestNodesRoute:
    async def test_listing_a_runs_steps(self, owner_client: OpenClient):
        run = _run_row()
        workflow = _workflow(id=run.workflow_id)
        node_run = MagicMock(
            id=uuid.uuid4(),
            node_instance_id=uuid.uuid4(),
            scope_path=[],
            status="succeeded",
            waiting_reason=None,
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
        )
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.list_node_runs_page",
                new=AsyncMock(return_value=([node_run], 1)),
            ),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.list_attempts_of", new=AsyncMock(return_value=[])
            ),
        ):
            async with owner_client() as http:
                response = await http.get(_url(f"/{run.id}/nodes"))
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["status"] == "succeeded" and body["items"][0]["attempts"] == 0


class TestGraphRoute:
    async def test_answering_with_the_graph_a_run_executes(self, owner_client: OpenClient):
        run = _run_row()
        workflow = _workflow(id=run.workflow_id)
        entry = uuid.uuid4()
        graph = WorkflowGraph.model_validate(
            {
                "entry_node_id": str(entry),
                "nodes": [
                    {
                        "id": str(entry),
                        "definition_id": "core.input",
                        "definition_version": 1,
                        "layout": {"x": 0, "y": 0},
                    }
                ],
            }
        )
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{FACADE_PATH}.dispatcher.resolve_graph", new=AsyncMock(return_value=graph)),
        ):
            async with owner_client() as http:
                response = await http.get(_url(f"/{run.id}/graph"))
        assert response.status_code == 200
        assert response.json()["graph"]["entry_node_id"] == str(entry)


class TestEventsRoute:
    async def test_listing_events_since_a_cursor(self, owner_client: OpenClient):
        run = _run_row()
        workflow = _workflow(id=run.workflow_id)
        event_row = MagicMock(
            id=uuid.uuid4(),
            seq=9,
            kind="node_completed",
            node_run_id=None,
            payload={},
            created_at=datetime.now(UTC),
        )
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(
                f"{FACADE_PATH}.workflow_run_repo.list_events_since",
                new=AsyncMock(return_value=[event_row]),
            ),
        ):
            async with owner_client() as http:
                response = await http.get(_url(f"/{run.id}/events"), params={"after": "3"})
        assert response.status_code == 200
        body = response.json()
        assert body["items"][0]["seq"] == 9
        assert body["next_cursor"] == "9"

    async def test_an_invalid_cursor_is_a_400(self, owner_client: OpenClient):
        run = _run_row()
        workflow = _workflow(id=run.workflow_id)
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
        ):
            async with owner_client() as http:
                response = await http.get(
                    _url(f"/{run.id}/events"), params={"after": "not-a-number"}
                )
        assert response.status_code == 400


class TestFileRoute:
    """A run's file, served - the route over a mocked repository, both ways."""

    async def test_a_run_s_file_downloads_as_an_attachment(self, owner_client: OpenClient):
        run = _run_row()
        workflow = _workflow(id=run.workflow_id)
        row = MagicMock(
            id=uuid.uuid4(), storage_path="p", content_type="application/pdf", filename="a.pdf"
        )
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{FACADE_PATH}.workflow_file_repo.get_for_run", new=AsyncMock(return_value=row)),
            patch(
                "app.api.routes.v1.workflow_runs.stored_file_response",
                new=AsyncMock(return_value=Response(content=b"%PDF", media_type="application/pdf")),
            ) as respond,
        ):
            async with owner_client() as http:
                response = await http.get(_url(f"/{run.id}/files/{row.id}"))
        assert response.status_code == 200 and response.content == b"%PDF"
        assert respond.await_args.kwargs["attachment_name"] == "a.pdf"
        assert respond.await_args.kwargs["headers"]["X-Content-Type-Options"] == "nosniff"

    @pytest.mark.parametrize("missing", ["row", "bytes"])
    async def test_a_file_the_run_does_not_have_is_404(
        self, owner_client: OpenClient, missing: str
    ):
        run = _run_row()
        workflow = _workflow(id=run.workflow_id)
        row = MagicMock(id=uuid.uuid4(), storage_path="p", content_type="text/plain", filename=None)
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(
                f"{FACADE_PATH}.workflow_file_repo.get_for_run",
                new=AsyncMock(return_value=None if missing == "row" else row),
            ),
            patch(
                "app.api.routes.v1.workflow_runs.stored_file_response",
                new=AsyncMock(return_value=None),
            ),
        ):
            async with owner_client() as http:
                response = await http.get(_url(f"/{run.id}/files/{row.id}"))
        assert response.status_code == 404


class TestFileListRoute:
    async def test_a_run_s_files_are_listed(self, owner_client: OpenClient):
        run = _run_row()
        workflow = _workflow(id=run.workflow_id)
        row = MagicMock(
            id=uuid.uuid4(),
            filename="report.csv",
            content_type="text/csv",
            byte_size=12,
            producing_node_run_id=None,
            created_at=datetime.now(UTC),
        )
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(
                f"{FACADE_PATH}.workflow_file_repo.list_for_run", new=AsyncMock(return_value=[row])
            ),
        ):
            async with owner_client() as http:
                response = await http.get(_url(f"/{run.id}/files"))
        assert response.status_code == 200
        assert response.json()["items"][0]["filename"] == "report.csv"


def _log_row(**overrides: object):
    row = MagicMock()
    row.id = uuid.uuid4()
    row.workflow_id = uuid.uuid4()
    row.run_id = uuid.uuid4()
    row.node_instance_id = uuid.uuid4()
    row.step_label = "Send the mail"
    row.outcome = "out"
    row.status = "succeeded"
    row.message = "Send the mail → out"
    row.is_test = False
    row.is_pinned = False
    row.created_at = datetime.now(UTC)
    for field, value in overrides.items():
        setattr(row, field, value)
    return row


class TestRunLogsRoute:
    async def test_a_runs_lines_are_listed_and_the_paging_reaches_the_repository(
        self, owner_client: OpenClient
    ):
        run = _run_row()
        workflow = _workflow(id=run.workflow_id)
        listed = AsyncMock(return_value=([_log_row()], 1))
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{FACADE_PATH}.workflow_log_repo.list_for_run", new=listed),
        ):
            async with owner_client() as http:
                response = await http.get(_url(f"/{run.id}/logs?skip=2&limit=5"))
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1 and body["items"][0]["message"] == "Send the mail → out"
        assert (listed.await_args.kwargs["skip"], listed.await_args.kwargs["limit"]) == (2, 5)

    async def test_a_run_the_caller_cannot_reach_answers_404(self, owner_client: OpenClient):
        run = _run_row()
        with (
            patch(f"{FACADE_PATH}.workflow_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=_workflow())),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=False)),
        ):
            async with owner_client() as http:
                response = await http.get(_url(f"/{run.id}/logs"))
        assert response.status_code == 404

    async def test_an_organization_key_may_not_call_it(self, owner_client: OpenClient):
        from app.api.public_api import is_public_route
        from app.api.routes.v1.workflow_runs import logs_router, router

        by_path = {route.path: route for route in (*router.routes, *logs_router.routes)}
        assert is_public_route(by_path["/{run_id}/nodes"])
        assert not is_public_route(by_path["/{run_id}/logs"])
        assert not is_public_route(by_path["/{workflow_id}/logs"])


class TestWorkflowLogsRoute:
    def _url(self, workflow_id: uuid.UUID, query: str = "") -> str:
        return f"{settings.API_V1_STR}/workflows/{workflow_id}/logs{query}"

    async def test_a_workflows_log_is_listed_with_its_filters_passed_on(
        self, owner_client: OpenClient
    ):
        workflow = _workflow()
        step = uuid.uuid4()
        listed = AsyncMock(return_value=([_log_row(is_test=True)], 1))
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{FACADE_PATH}.workflow_log_repo.list_for_workflow", new=listed),
        ):
            async with owner_client() as http:
                response = await http.get(
                    self._url(
                        workflow.id,
                        f"?node_instance_id={step}&outcome=error&q=mail&include_test=true"
                        "&from=2026-10-01T00:00:00Z&to=2026-10-02T00:00:00Z&skip=3&limit=10",
                    )
                )
        assert response.status_code == 200
        assert response.json()["items"][0]["is_test"] is True
        filters = listed.await_args.kwargs["filters"]
        assert (filters.node_instance_id, filters.outcome, filters.query) == (step, "error", "mail")
        assert filters.include_test is True
        assert filters.created_from == datetime(2026, 10, 1, tzinfo=UTC)
        assert filters.created_to == datetime(2026, 10, 2, tzinfo=UTC)
        assert (listed.await_args.kwargs["skip"], listed.await_args.kwargs["limit"]) == (3, 10)

    async def test_a_run_id_or_its_start_is_passed_on_and_anything_else_is_refused(
        self, owner_client: OpenClient
    ):
        workflow = _workflow()
        run = uuid.uuid4()
        listed = AsyncMock(return_value=([], 0))
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{FACADE_PATH}.workflow_log_repo.list_for_workflow", new=listed),
        ):
            async with owner_client() as http:
                whole = await http.get(self._url(workflow.id, f"?run={run}"))
                dashless = await http.get(self._url(workflow.id, f"?run={run.hex}"))
                start = await http.get(self._url(workflow.id, "?run=3f2a1b9c-4"))
                refused = [
                    await http.get(self._url(workflow.id, f"?run={value}"))
                    for value in (
                        "3f2",
                        "xyz123",
                        f"{run}0",
                        "3f2a%25",
                        "3f2a" * 9,
                        "3f2a" * 9 + "-",
                        "3f2a3f2a3f",
                        "3f2a-3f2a3f",
                    )
                ]
        assert whole.status_code == dashless.status_code == start.status_code == 200
        assert [call.kwargs["filters"].run for call in listed.await_args_list] == [
            str(run),
            run.hex,
            "3f2a1b9c-4",
        ]
        for response in refused:
            assert response.status_code == 422
            problems = response.json()["error"]["details"]["fields"]
            assert problems == [
                {"field": "run", "message": "A run id, or its first 4 or more characters"}
            ]
            assert "pattern" not in response.text
        assert listed.await_count == 3

    async def test_test_runs_are_left_out_unless_asked_for(self, owner_client: OpenClient):
        workflow = _workflow()
        listed = AsyncMock(return_value=([], 0))
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{FACADE_PATH}.workflow_log_repo.list_for_workflow", new=listed),
        ):
            async with owner_client() as http:
                response = await http.get(self._url(workflow.id))
        assert response.status_code == 200
        assert listed.await_args.kwargs["filters"].include_test is False

    async def test_a_workflow_the_caller_cannot_view_answers_404_like_its_runs(
        self, owner_client: OpenClient
    ):
        workflow = _workflow()
        with (
            patch(f"{FACADE_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{FACADE_PATH}.resolve_access", new=AsyncMock(return_value=False)),
        ):
            async with owner_client() as http:
                logs = await http.get(self._url(workflow.id))
                runs = await http.get(
                    f"{settings.API_V1_STR}/workflow-runs?workflow_id={workflow.id}"
                )
        assert logs.status_code == runs.status_code == 404

    async def test_a_limit_over_the_page_ceiling_is_refused(self, owner_client: OpenClient):
        async with owner_client() as http:
            response = await http.get(self._url(uuid.uuid4(), "?limit=101"))
        assert response.status_code == 422
