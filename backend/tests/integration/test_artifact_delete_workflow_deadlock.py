"""An app deletion and its workflow writer finish without reversing row locks.

A second update of one run in a transaction rechecks its source-app foreign key.
If a concurrent delete already holds the app row and waits to SET NULL on that
run, the foreign-key check and deletion deadlock. Both operations must take the
workflow organization guards before either row. The barrier below observes the
actual PostgreSQL waiter; no timed sleep chooses the interleaving.
"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.background import discard_deferred
from app.db.locks import LockScope, hold_subject
from app.db.models.artifact import Artifact
from app.db.models.workflow_run import WorkflowEvent, WorkflowRun, WorkflowRunStatus
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.artifact import ArtifactActionRunCreate
from app.services.artifact import ArtifactService
from app.services.file_storage import LocalFileStorage
from tests.integration.test_artifact_action_runs import _live, _page, _served_id
from tests.integration.test_artifact_actions import _world

pytestmark = pytest.mark.anyio


@pytest.fixture
def storage(tmp_path: Path) -> Iterator[LocalFileStorage]:
    local = LocalFileStorage(tmp_path)
    with (
        patch("app.services.artifact.get_file_storage", return_value=local),
        patch("app.services.file_storage.get_file_storage", return_value=local),
    ):
        yield local


async def test_deleting_an_app_waits_for_its_workflow_writer_and_keeps_the_run(
    engine: AsyncEngine, storage: LocalFileStorage
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as setup:
        world = await _world(setup)
        workflow = await _live(world, "Collect")
        artifact_id = await _page(world, workflow)
        started = await ArtifactService(setup).start_action(
            world.boss,
            artifact_id,
            await _served_id(setup, world.boss, artifact_id),
            workflow.id,
            ArtifactActionRunCreate(),
        )
        await setup.commit()
        discard_deferred(setup)

    deleting_pids: asyncio.Queue[int] = asyncio.Queue()

    async def delete_app() -> None:
        async with sessions() as deleting:
            try:
                pid = await deleting.scalar(text("SELECT pg_backend_pid()"))
                assert isinstance(pid, int)
                await deleting_pids.put(pid)
                await ArtifactService(deleting).delete(world.boss, artifact_id)
                await deleting.commit()
            finally:
                discard_deferred(deleting)

    async with asyncio.timeout(15), sessions() as writer:
        await hold_subject(writer, LockScope.WORKFLOW_FILE_BYTES, world.org.id)
        await hold_subject(writer, LockScope.WORKFLOW_INLINE_RESULTS_PER_ORG, world.org.id)
        run = await workflow_run_repo.get_run_by_id_for_update(writer, started.run_id)
        assert run is not None and run.source_artifact_id == artifact_id
        source_version = run.source_version_number
        sequence = run.next_event_seq
        await workflow_run_repo.update_run(
            writer,
            run=run,
            update_data={
                "status": WorkflowRunStatus.CANCELLED.value,
                "ended_at": datetime.now(UTC),
            },
        )
        writer_pid = await writer.scalar(text("SELECT pg_backend_pid()"))
        assert isinstance(writer_pid, int)

        async with asyncio.TaskGroup() as group:
            deleting = group.create_task(delete_app())
            deleting_pid = await deleting_pids.get()
            async with sessions() as observer:
                while True:
                    blocked, advisory = (
                        await observer.execute(
                            text(
                                "SELECT :writer_pid = ANY(pg_blocking_pids(:deleting_pid)), "
                                "EXISTS (SELECT 1 FROM pg_locks WHERE pid = :deleting_pid "
                                "AND locktype = 'advisory' AND NOT granted)"
                            ),
                            {"writer_pid": writer_pid, "deleting_pid": deleting_pid},
                        )
                    ).one()
                    if blocked:
                        break
                    assert not deleting.done(), "App deletion did not wait for the workflow writer"
                    await asyncio.sleep(0.01)
            assert blocked
            # This is the second real UPDATE of the run, after the delete waits.
            # With the old lock order, PostgreSQL detects the FK/SET NULL cycle.
            event = await workflow_run_repo.append_event(
                writer, run=run, kind="run_cancelled", node_run_id=None, payload={}
            )
            assert event.seq == sequence
            await writer.commit()

    assert advisory, "App deletion must wait before locking the source app row"
    async with sessions() as observed:
        assert await observed.get(Artifact, artifact_id) is None
        retained = await observed.get(WorkflowRun, started.run_id)
        assert retained is not None
        assert retained.source_artifact_id is None
        assert retained.source_version_number == source_version
        assert retained.status == WorkflowRunStatus.CANCELLED.value
        assert retained.next_event_seq == sequence + 1
        saved_event = (
            await observed.execute(
                select(WorkflowEvent).where(
                    WorkflowEvent.workflow_run_id == started.run_id,
                    WorkflowEvent.seq == sequence,
                )
            )
        ).scalar_one()
        assert saved_event.kind == "run_cancelled"
