"""An App deletion and a workflow sweep take run locks in the same order (#3021).

The FK scan can visit runs in physical order, opposite a reconciler's UUID order.
Pin that scan plan and pause deletion on a run the sweep already holds: without
ordered pre-locking, it holds the next run the sweep needs and PostgreSQL aborts
one transaction. Exercise real service deletion on model-created and migrated
schemas; storage follows the request's commit rather than its successful flush.
"""

import asyncio
import os
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.background import discard_deferred, drain, start_deferred
from app.core.config import settings
from app.core.permissions import AuthContext
from app.db.models.artifact import Artifact
from app.db.models.workflow import Workflow
from app.db.models.workflow_run import WorkflowEvent, WorkflowRun
from app.repositories import workflow_run as workflow_run_repo
from app.services.artifact import ArtifactService
from app.services.file_storage import LocalFileStorage
from tests.integration.workflow_run_support import seed_member

pytestmark = pytest.mark.anyio


@pytest.fixture(params=["models", "migrations"])
async def schema_engine(
    request: pytest.FixtureRequest, engine: AsyncEngine
) -> AsyncIterator[AsyncEngine]:
    if request.param == "models":
        yield engine
        return
    name = f"agenticos_app_delete_test_{uuid4().hex[:12]}"
    maintenance = create_async_engine(
        settings.DATABASE_URL.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT"
    )
    migrated = create_async_engine(settings.DATABASE_URL.rsplit("/", 1)[0] + f"/{name}")
    try:
        async with maintenance.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{name}"'))
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "head",
            env={**os.environ, "POSTGRES_DB": name},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        assert process.returncode == 0, (stdout + stderr).decode()
        yield migrated
    finally:
        await migrated.dispose()
        async with maintenance.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await maintenance.dispose()


async def seed(db: AsyncSession) -> tuple[AuthContext, UUID, UUID, UUID]:
    person, org = await seed_member(db)
    app = Artifact(
        id=uuid4(),
        organization_id=org.id,
        owner_user_id=person.id,
        name="source",
        title="Source",
        visibility="private",
    )
    workflow = Workflow(
        id=uuid4(),
        organization_id=org.id,
        owner_user_id=person.id,
        name="Work",
        slug="work",
        visibility="private",
        draft_graph={},
    )
    db.add_all([app, workflow])
    await db.flush()
    low, high = sorted([uuid4(), uuid4()])
    # The FK's physical scan is the reverse of the sweep's UUID lock order.
    for run_id in [high, low]:
        db.add(
            WorkflowRun(
                id=run_id,
                organization_id=org.id,
                workflow_id=workflow.id,
                draft_graph_snapshot={},
                mode="test",
                status="running",
                triggered_by="app",
                root_run_id=run_id,
                source_artifact_id=app.id,
                source_version_number=1,
                execution_principal_user_id=person.id,
                started_at=datetime.now(UTC),
            )
        )
        await db.flush()
    await db.commit()
    return AuthContext(user_id=person.id, organization_id=org.id, role="owner"), app.id, low, high


async def wait_for_block(factory: async_sessionmaker[AsyncSession], pid: int) -> None:
    async with asyncio.timeout(5):
        while True:
            async with factory() as db:
                blockers = await db.scalar(
                    text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": pid}
                )
            if blockers:
                return
            await asyncio.sleep(0.01)


async def test_deleting_the_source_does_not_deadlock_a_sweeps_event_writes(
    schema_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(schema_engine, expire_on_commit=False)
    async with factory() as db:
        ctx, app_id, low, high = await seed(db)
    org_id = ctx.organization_id
    async with factory() as writer, factory() as deleter:
        first = await workflow_run_repo.get_run_for_update(writer, low, organization_id=org_id)
        assert first is not None
        first.status = "cancelled"
        await workflow_run_repo.append_event(
            writer, run=first, kind="run.cancelled", node_run_id=None, payload={}
        )
        await deleter.execute(text("SET LOCAL enable_indexscan = off"))
        await deleter.execute(text("SET LOCAL enable_bitmapscan = off"))
        pid = await deleter.scalar(text("SELECT pg_backend_pid()"))
        assert isinstance(pid, int)
        deleting = asyncio.create_task(ArtifactService(deleter).delete(ctx, app_id))
        try:
            await wait_for_block(factory, pid)
            # A reconciler processes more than one run in its transaction, in UUID order.
            async with asyncio.timeout(5):
                second = await workflow_run_repo.get_run_for_update(
                    writer, high, organization_id=org_id
                )
                assert second is not None
                second.status = "cancelled"
                await workflow_run_repo.append_event(
                    writer, run=second, kind="run.cancelled", node_run_id=None, payload={}
                )
                await writer.commit()
                await deleting
                await deleter.commit()
                discard_deferred(deleter)
        finally:
            deleting.cancel()
            await asyncio.gather(deleting, return_exceptions=True)
            discard_deferred(deleter)
    async with factory() as db:
        assert await db.get(Artifact, app_id) is None
        runs = list((await db.scalars(select(WorkflowRun).order_by(WorkflowRun.id))).all())
        assert [run.id for run in runs] == [low, high]
        assert all(
            run.source_artifact_id is None
            and run.source_version_number == 1
            and run.status == "cancelled"
            and run.next_event_seq == 1
            for run in runs
        )
        events = list((await db.scalars(select(WorkflowEvent))).all())
        assert {(event.workflow_run_id, event.seq) for event in events} == {(low, 0), (high, 0)}


@pytest.mark.parametrize("commit", [False, True])
async def test_app_bytes_follow_the_commit_and_survive_rollback(
    schema_engine: AsyncEngine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    commit: bool,
) -> None:
    factory = async_sessionmaker(schema_engine, expire_on_commit=False)
    async with factory() as db:
        ctx, app_id, low, high = await seed(db)
    storage = LocalFileStorage(tmp_path)
    monkeypatch.setattr("app.services.artifact.get_file_storage", lambda: storage)
    path = f"artifacts/{ctx.organization_id}/{app_id}/index.html"
    await storage.save_at(path, b"<h1>Source</h1>")
    async with factory() as db:
        try:
            await ArtifactService(db).delete(ctx, app_id)
            await drain()
            assert await storage.exists(path)
            if commit:
                await db.commit()
                start_deferred(db)
            else:
                await db.rollback()
                discard_deferred(db)
            await drain()
            assert await storage.exists(path) is not commit
        finally:
            discard_deferred(db)
    async with factory() as db:
        assert (await db.get(Artifact, app_id) is None) is commit
        for run_id in [low, high]:
            run = await db.get(WorkflowRun, run_id)
            assert run is not None
            assert run.source_artifact_id == (None if commit else app_id)
