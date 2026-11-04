"""An organization key reading a workflow's log, against Postgres: the scope it needs, the runs
whose lines it may see, and the organizations it never reaches.

A key reads what the runs list shows it - the runs it started or an outsider's input started -
so a dashboard built on a key never sees a line the key could not reach through the run.
"""

import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api import deps
from app.core.config import settings
from app.core.permissions import Perm
from app.db.models.workflow_run import WorkflowRunMode
from app.main import app
from app.repositories import workflow_log_entry as workflow_log_repo
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.api_key import ApiKeyCreate
from app.services.api_key import ApiKeyService
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph
from tests.integration.workflow_run_support import SeededRun, seed_run

pytestmark = pytest.mark.anyio

API = settings.API_V1_STR


def _graph() -> WorkflowGraph:
    step = NodeInstance(
        id=uuid.uuid4(),
        definition_id="core.input",
        definition_version=1,
        label="Start",
        layout=NodePosition(x=0, y=0),
    )
    return WorkflowGraph(entry_node_id=step.id, nodes=(step,), edges=())


async def _line(seeded: SeededRun, run_id: uuid.UUID, message: str) -> None:
    async with seeded.factory() as db:
        await workflow_log_repo.create(
            db,
            organization_id=seeded.org.id,
            workflow_id=seeded.run.workflow_id,
            run_id=run_id,
            node_instance_id=seeded.graph.entry_node_id,
            step_label="Start",
            outcome="out",
            status="completed",
            message=message,
            is_test=False,
            is_pinned=False,
        )
        await db.commit()


async def _private_run(seeded: SeededRun) -> uuid.UUID:
    """A second run of the workflow that nobody outside started."""
    async with seeded.factory() as db:
        run = await workflow_run_repo.create_run(
            db,
            organization_id=seeded.org.id,
            workflow_id=seeded.run.workflow_id,
            workflow_version_id=None,
            draft_graph_snapshot=seeded.graph.model_dump(mode="json"),
            mode=WorkflowRunMode.TEST.value,
            triggered_by="chat",
            public_origin=False,
            execution_principal_user_id=seeded.principal.id,
            budget_limit=None,
            node_count=1,
            deadline_at=None,
            root_run_id=None,
            causation_run_id=None,
            visited_trigger_ids=[],
            depth=0,
            started_at=datetime.now(UTC),
            run_input=None,
        )
        await db.commit()
        return run.id


@asynccontextmanager
async def _as_key(seeded: SeededRun, *scopes: Perm) -> AsyncIterator[AsyncClient]:
    async with seeded.factory() as db:
        issued = await ApiKeyService(db).create(
            seeded.ctx, ApiKeyCreate(name="dashboard", scopes=list(scopes))
        )
        await db.commit()

    async def session() -> AsyncGenerator[AsyncSession]:
        async with seeded.factory() as opened:
            yield opened
            await opened.commit()

    app.dependency_overrides[deps.get_db_session] = session
    app.dependency_overrides[deps.get_redis] = lambda: MagicMock()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {issued.key}"},
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
async def logged(engine: AsyncEngine) -> tuple[SeededRun, uuid.UUID]:
    """A workflow with a line from a run an outsider started and one from a private run."""
    seeded = await seed_run(engine, _graph(), triggered_by="webhook")
    private = await _private_run(seeded)
    await _line(seeded, seeded.run.id, "public line")
    await _line(seeded, private, "private line")
    return seeded, private


class TestAKeyWithTheViewScope:
    async def test_it_reads_the_workflows_log_and_only_the_lines_of_runs_it_may_see(
        self, logged: tuple[SeededRun, uuid.UUID]
    ):
        seeded, _ = logged
        async with _as_key(seeded, Perm.WORKFLOWS_VIEW) as client:
            response = await client.get(f"{API}/workflows/{seeded.run.workflow_id}/logs")
        assert response.status_code == 200, response.text
        body = response.json()
        assert [item["message"] for item in body["items"]] == ["public line"]
        assert body["total"] == 1

    async def test_it_reads_the_per_day_summary_of_those_lines(
        self, logged: tuple[SeededRun, uuid.UUID]
    ):
        seeded, _ = logged
        async with _as_key(seeded, Perm.WORKFLOWS_VIEW) as client:
            response = await client.get(
                f"{API}/workflows/{seeded.run.workflow_id}/logs/summary?days=7&tz=Europe/Warsaw"
            )
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 1

    async def test_it_reads_a_runs_lines_but_not_a_runs_it_may_not_see(
        self, logged: tuple[SeededRun, uuid.UUID]
    ):
        seeded, private = logged
        async with _as_key(seeded, Perm.WORKFLOWS_VIEW) as client:
            visible = await client.get(f"{API}/workflow-runs/{seeded.run.id}/logs")
            hidden = await client.get(f"{API}/workflow-runs/{private}/logs")
        assert visible.status_code == 200, visible.text
        assert [item["message"] for item in visible.json()["items"]] == ["public line"]
        assert hidden.status_code == 404

    async def test_it_reads_the_organizations_recent_lines_of_runs_it_may_see(
        self, logged: tuple[SeededRun, uuid.UUID]
    ):
        seeded, _ = logged
        async with _as_key(seeded, Perm.WORKFLOWS_VIEW) as client:
            response = await client.get(f"{API}/workflow-logs")
        assert response.status_code == 200, response.text
        body = response.json()
        assert [item["message"] for item in body["items"]] == ["public line"]
        assert body["counts"] == {"out": 1}


@pytest.mark.security
class TestAKeyWithoutIt:
    async def test_every_log_read_is_refused(self, logged: tuple[SeededRun, uuid.UUID]):
        seeded, _ = logged
        workflow = seeded.run.workflow_id
        async with _as_key(seeded, Perm.TABLES_VIEW) as client:
            answers = [
                await client.get(f"{API}/workflows/{workflow}/logs"),
                await client.get(f"{API}/workflows/{workflow}/logs/summary"),
                await client.get(f"{API}/workflow-runs/{seeded.run.id}/logs"),
                await client.get(f"{API}/workflow-logs"),
            ]
        assert [answer.status_code for answer in answers] == [404, 404, 404, 403]


@pytest.mark.security
async def test_a_key_never_reaches_another_organizations_workflow(
    engine: AsyncEngine, logged: tuple[SeededRun, uuid.UUID]
):
    seeded, _ = logged
    elsewhere = await seed_run(engine, _graph(), triggered_by="webhook")
    await _line(elsewhere, elsewhere.run.id, "their line")
    async with _as_key(seeded, Perm.WORKFLOWS_VIEW) as client:
        foreign = [
            await client.get(f"{API}/workflows/{elsewhere.run.workflow_id}/logs"),
            await client.get(f"{API}/workflows/{elsewhere.run.workflow_id}/logs/summary"),
            await client.get(f"{API}/workflow-runs/{elsewhere.run.id}/logs"),
        ]
        recent = await client.get(f"{API}/workflow-logs")
    assert [answer.status_code for answer in foreign] == [404, 404, 404]
    assert "their line" not in recent.text
