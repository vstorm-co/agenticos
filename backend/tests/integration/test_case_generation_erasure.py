"""Accepting a draft and deleting its source account cannot recreate personal data."""

import asyncio
from collections.abc import Sequence
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.case_generation import CaseProposal
from app.db.models.dataset import DatasetCase
from app.db.models.user import User
from app.repositories import case_generation_repo
from app.services.case_generation import CaseGenerationService
from app.services.personal_data import ANONYMISED_CASE_INPUT
from app.services.user import UserService
from tests.integration import case_generation_world as world
from tests.integration.test_case_generation import _accept, _setup

pytestmark = pytest.mark.anyio


async def test_acceptance_and_source_account_erasure_serialize(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as setup:
        owner, org, agent, dataset = await _setup(setup)
        source = await world.user(setup)
        run, conversation, question = await world.asked(
            setup, org, agent, source, "Private source question", minutes=1
        )
        _, proposals = await world.proposals(
            setup,
            org,
            dataset,
            agent,
            1,
            source_run_id=run.id,
            source_conversation_id=conversation.id,
            source_message_id=question.id,
        )
        proposal = proposals[0]
        proposal.input = "Private source question"
        dataset_id, proposal_id, source_id = dataset.id, proposal.id, source.id
        await setup.commit()
    claimed = asyncio.Event()
    release = asyncio.Event()
    erasing_process: asyncio.Queue[int] = asyncio.Queue()
    take = case_generation_repo.take_proposals

    async def pause_after_claim(
        db: AsyncSession,
        dataset_id: UUID,
        ids: Sequence[UUID],
        *,
        organization_id: UUID,
        without_origin: str | None = None,
    ) -> list[CaseProposal]:
        taken = await take(
            db, dataset_id, ids, organization_id=organization_id, without_origin=without_origin
        )
        claimed.set()
        await release.wait()
        return taken

    monkeypatch.setattr(case_generation_repo, "take_proposals", pause_after_claim)

    async def accept() -> None:
        async with sessions() as session:
            await CaseGenerationService(session, vector_store=MagicMock()).accept(
                owner, dataset_id, _accept(proposal_id)
            )
            await session.commit()

    async def erase() -> None:
        async with sessions() as session:
            process = await session.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(process, int)
            await erasing_process.put(process)
            await UserService(session).delete(source_id)
            await session.commit()

    async with asyncio.timeout(10), asyncio.TaskGroup() as group:
        group.create_task(accept())
        await claimed.wait()
        group.create_task(erase())
        process = await erasing_process.get()
        async with sessions() as observer:
            while True:
                blocked = await observer.scalar(
                    text("SELECT pg_blocking_pids(:pid) <> '{}'::int[]"), {"pid": process}
                )
                if blocked:
                    break
                await asyncio.sleep(0.01)
        release.set()
    async with sessions() as session:
        assert await session.get(User, source_id) is None
        inputs = list(
            (
                await session.scalars(
                    select(DatasetCase.input).where(DatasetCase.dataset_id == dataset_id)
                )
            ).all()
        )
        assert inputs == [ANONYMISED_CASE_INPUT]
