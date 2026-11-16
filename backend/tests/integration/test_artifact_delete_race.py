"""App deletion releases partial source locks before waiting (#3021).

A second event flush can recheck the unchanged source FK after this transaction's
first update. Holding the App while waiting for its run would block that recheck.
An FK scan can also visit runs opposite a sweeper's UUID order. Both cycles are
forced on model-created and migrated schemas; retries release every partial lock,
contention expires as a write-free 409, and bytes follow only a committed delete.
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
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.background import discard_deferred, drain, start_deferred
from app.core.config import settings
from app.core.exceptions import ConcurrentChangeError
from app.core.permissions import AuthContext
from app.db.locks import LOCK_NOT_AVAILABLE
from app.db.models.artifact import Artifact
from app.db.models.workflow import Workflow
from app.db.models.workflow_run import WorkflowEvent, WorkflowRun
from app.repositories import artifact_repo
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


async def seed(db: AsyncSession, *, single: bool = False) -> tuple[AuthContext, UUID, UUID, UUID]:
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
    for run_id in [low] if single else [high, low]:
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


async def wait_for_contention(
    factory: async_sessionmaker[AsyncSession],
    pid: int,
    retrying: asyncio.Event,
) -> None:
    async with asyncio.timeout(5):
        while not retrying.is_set():
            async with factory() as db:
                blockers = await db.scalar(
                    text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": pid}
                )
            if blockers:
                return
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("single", [False, True], ids=["sweep", "two-events-one-run"])
async def test_deleting_the_source_does_not_deadlock_event_writes(
    schema_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    single: bool,
) -> None:
    retrying = asyncio.Event()
    original = artifact_repo.lock_for_delete

    async def observed(db: AsyncSession, artifact: Artifact) -> None:
        try:
            await original(db, artifact)
        except DBAPIError as failure:
            if getattr(failure.orig, "sqlstate", None) == LOCK_NOT_AVAILABLE:
                retrying.set()
            raise

    monkeypatch.setattr(artifact_repo, "lock_for_delete", observed)
    factory = async_sessionmaker(schema_engine, expire_on_commit=False)
    async with factory() as db:
        ctx, app_id, low, high = await seed(db, single=single)
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
            await wait_for_contention(factory, pid, retrying)
            # A reconciler processes more than one run in its transaction, in UUID order.
            async with asyncio.timeout(5):
                second = (
                    first
                    if single
                    else await workflow_run_repo.get_run_for_update(
                        writer, high, organization_id=org_id
                    )
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
        assert [run.id for run in runs] == ([low] if single else [low, high])
        assert all(
            run.source_artifact_id is None
            and run.source_version_number == 1
            and run.status == "cancelled"
            and run.next_event_seq == (2 if single else 1)
            for run in runs
        )
        events = list((await db.scalars(select(WorkflowEvent))).all())
        assert {(event.workflow_run_id, event.seq) for event in events} == (
            {(low, 0), (low, 1)} if single else {(low, 0), (high, 0)}
        )


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


@pytest.mark.parametrize("target", ["app", "run"])
async def test_busy_deletion_returns_a_retryable_conflict_without_writing(
    schema_engine: AsyncEngine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    factory = async_sessionmaker(schema_engine, expire_on_commit=False)
    async with factory() as db:
        ctx, app_id, low, _high = await seed(db)
    storage = LocalFileStorage(tmp_path)
    monkeypatch.setattr("app.services.artifact.get_file_storage", lambda: storage)
    monkeypatch.setattr("app.services.artifact._DELETE_LOCK_SECONDS", 0)
    path = f"artifacts/{ctx.organization_id}/{app_id}/index.html"
    await storage.save_at(path, b"keep")
    async with factory() as writer, factory() as deleter:
        table = Artifact if target == "app" else WorkflowRun
        row_id = app_id if target == "app" else low
        await writer.execute(select(table.id).where(table.id == row_id).with_for_update())
        try:
            with pytest.raises(ConcurrentChangeError) as refused:
                await ArtifactService(deleter).delete(ctx, app_id)
            assert refused.value.status_code == 409
            assert refused.value.details == {"artifact_id": app_id}
            # Even a caller committing after catching the refusal cannot delete rows or bytes.
            await deleter.commit()
            start_deferred(deleter)
            await drain()
            assert await storage.exists(path)
            await writer.rollback()
        finally:
            discard_deferred(deleter)
    async with factory() as db:
        assert await db.get(Artifact, app_id) is not None
        run = await db.get(WorkflowRun, low)
        assert run is not None and run.source_artifact_id == app_id
