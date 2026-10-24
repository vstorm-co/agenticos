"""A queued generation, carried out by its job in the worker.

The request that started the generation checked everything up front and queued
the job in its own transaction; this runs it later, as the person who asked,
with their access as it is now. The material is gathered again rather than
carried in the job, so the job holds identifiers only - never the questions
people asked - and a source the requester lost in between is not read.
"""

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException
from app.core.permissions import AuthContext
from app.db.models.case_generation import CaseGeneration, CaseOrigin, GenerationStatus
from app.db.session import get_worker_db_context
from app.repositories import case_generation_repo, member_repo
from app.schemas.case_generation import CaseGenerationRequest
from app.services import change_feed
from app.services.case_generation.facade import CaseGenerationService
from app.services.case_generation.generation import generate
from app.services.rag.embeddings import EmbeddingService
from app.services.rag.vectorstore import BaseVectorStore, process_vector_store

logger = logging.getLogger(__name__)

type Sessions = Callable[[], AbstractAsyncContextManager[AsyncSession]]

REQUESTER_GONE = "Whoever started this generation is no longer a member."
AGENT_GONE = "The agent the cases were for was deleted."
STOPPED = "The generation stopped before it finished. Start it again."


async def requester(db: AsyncSession, generation: CaseGeneration) -> AuthContext | None:
    """The requester's authority as it is now, or `None` once they left the organization."""
    user_id = generation.requested_by_user_id
    if user_id is None:
        return None
    membership = await member_repo.get_active(
        db, organization_id=generation.organization_id, user_id=user_id
    )
    if membership is None:
        return None
    return AuthContext(
        user_id=user_id, organization_id=generation.organization_id, role=membership.role
    )


async def _fail(db: AsyncSession, generation: CaseGeneration, error: str) -> None:
    await case_generation_repo.finish_generation(
        db,
        generation,
        status=GenerationStatus.FAILED.value,
        finished_at=datetime.now(UTC),
        error=error,
    )


class CaseGenerationWorker:
    """Carries one generation to its end, recording why when it cannot."""

    def __init__(
        self,
        generation_id: UUID,
        organization_id: UUID,
        *,
        sessions: Sessions = get_worker_db_context,
        vector_store: BaseVectorStore | None = None,
    ) -> None:
        self.generation_id = generation_id
        self.organization_id = organization_id
        self.sessions = sessions
        self.vector_store = vector_store

    def _store(self) -> BaseVectorStore:
        if self.vector_store is None:
            self.vector_store = process_vector_store(settings.rag, EmbeddingService(settings.rag))
        return self.vector_store

    async def run(self) -> None:
        async with self.sessions() as db:
            ended = await self._run(db)
        if ended is not None:
            await change_feed.publish_dataset(
                organization_id=self.organization_id,
                dataset_id=ended.dataset_id,
                actor_user_id=ended.requested_by_user_id,
            )

    async def _run(self, db: AsyncSession) -> CaseGeneration | None:
        """Run the generation; the generation, once it has ended, for its dataset to be told."""
        generation = await case_generation_repo.get_generation(
            db, self.generation_id, organization_id=self.organization_id
        )
        if generation is None or generation.status != GenerationStatus.RUNNING.value:
            return None
        ctx = await requester(db, generation)
        if ctx is None or generation.agent_id is None:
            await _fail(db, generation, REQUESTER_GONE if ctx is None else AGENT_GONE)
            return generation
        service = CaseGenerationService(db, vector_store=self._store())
        request = CaseGenerationRequest(
            agent_id=generation.agent_id,
            sources=[CaseOrigin(source).value for source in generation.sources],
            count=generation.requested_count,
        )
        try:
            _, material, quotas, prompt = await service.plan(ctx, generation.dataset_id, request)
        except AppException as exc:
            await _fail(db, generation, exc.message)
            return generation
        await generate(
            db,
            generation_id=generation.id,
            ctx=ctx,
            prompt=prompt,
            material=material,
            quotas=quotas,
        )
        await db.refresh(generation)
        if generation.auto_accept and generation.status == GenerationStatus.READY.value:
            await self._accept(db, service, ctx, generation)
        return generation

    @staticmethod
    async def _accept(
        db: AsyncSession,
        service: CaseGenerationService,
        ctx: AuthContext,
        generation: CaseGeneration,
    ) -> None:
        """Accept the drafts; refused, they stay waiting for a person rather than vanish."""
        try:
            async with db.begin_nested():
                await service.accept_drafted(ctx, generation)
        except AppException as exc:
            logger.warning(
                "case_generation_auto_accept_refused",
                extra={"generation_id": str(generation.id), "reason": exc.message},
            )


async def settle_lost(generation_id: UUID, organization_id: UUID) -> None:
    """Fail a generation whose job ended for good while it was still running.

    A worker killed under the job cannot mark the row itself, and nothing else
    would ever finish it. A generation the job already ended is left as it is.
    """
    async with get_worker_db_context() as db:
        generation = await case_generation_repo.get_generation(
            db, generation_id, organization_id=organization_id
        )
        if generation is not None and generation.status == GenerationStatus.RUNNING.value:
            await _fail(db, generation, STOPPED)
