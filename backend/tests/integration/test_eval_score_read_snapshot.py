"""A score and its required case revision remain one readable PostgreSQL snapshot."""

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, delete, event, select
from sqlalchemy.engine import AdaptedConnection, ExecutionContext
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models.case_score import CaseScore
from app.db.models.dataset import Dataset, DatasetCase
from app.repositories import eval_run_repo
from app.schemas.scoring import CaseScoreRead
from tests.integration.test_eval_runs_repo import _dataset, _owner

pytestmark = pytest.mark.anyio


async def test_score_keeps_its_revision_when_dataset_deletion_commits_after_its_select(
    engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as seed:
        ctx = await _owner(seed)
        dataset, _version, revisions = await _dataset(seed, ctx, cases=1)
        revision = revisions[0]
        score = CaseScore(
            id=uuid4(),
            organization_id=ctx.organization_id,
            dataset_id=dataset.id,
            case_revision_id=revision.id,
            case_id=revision.case_id,
            answer="The scored answer",
            scoring={},
            results=[],
            passed=True,
        )
        seed.add(score)
        await seed.commit()
        dataset_id, score_id, revision_id = dataset.id, score.id, revision.id
        question, reference = revision.input, revision.reference_answer

    selected, release = asyncio.Event(), asyncio.Event()
    boundaries = 0

    async def pause(_driver: object) -> None:
        selected.set()
        await release.wait()

    def after_score_select(
        connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: ExecutionContext,
        _executemany: bool,
    ) -> None:
        nonlocal boundaries
        if "FROM case_scores" in statement and not selected.is_set():
            boundaries += 1
            adapted = connection.connection.dbapi_connection
            assert isinstance(adapted, AdaptedConnection)
            adapted.run_async(pause)

    async def read_scores() -> dict[UUID, CaseScore]:
        async with factory() as reader:
            connection = await reader.connection()
            event.listen(connection.sync_connection, "after_cursor_execute", after_score_select)
            try:
                return await eval_run_repo.scores(
                    reader, [score_id], organization_id=ctx.organization_id
                )
            finally:
                event.remove(connection.sync_connection, "after_cursor_execute", after_score_select)

    pending = asyncio.create_task(read_scores())
    deleted = False
    try:
        await asyncio.wait_for(selected.wait(), timeout=10)
        # Pause after the primary score query in both versions. Waiting only on
        # selectin's revision query would stop exercising deletion after a join fix.
        async with factory() as remover:
            removed = await remover.execute(
                delete(Dataset).where(Dataset.id == dataset_id).returning(Dataset.id)
            )
            assert removed.scalar_one() == dataset_id
            await remover.commit()
            deleted = True
        release.set()
        scores = await asyncio.wait_for(pending, timeout=10)
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)

    assert deleted and boundaries == 1
    async with factory() as verifier:
        assert await verifier.scalar(select(Dataset.id).where(Dataset.id == dataset_id)) is None
        assert await verifier.scalar(select(CaseScore.id).where(CaseScore.id == score_id)) is None
        assert (
            await verifier.scalar(select(DatasetCase.id).where(DatasetCase.id == revision_id))
            is None
        )

    assert set(scores) == {score_id}
    read = CaseScoreRead.model_validate(scores[score_id])
    assert read.case_revision_id == revision_id
    assert (read.question, read.reference_answer) == (question, reference)
    assert read.answer == "The scored answer"
    assert read.outcome is True
    # Runs are optional and may already be gone; the required question is not.
    assert (read.run_id, read.run_model, read.agent_version_id) == (None, None, None)
