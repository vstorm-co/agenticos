"""`CaseGenerationService` - draft cases for a dataset, and decide what was drafted.

Propose, never write: the generator's drafts wait as proposals, and only a
person's Accept turns them into cases - all of one decision into one new dataset
version. Every route lands here, and every one needs `datasets:edit` on the
dataset: a proposal drafted from a conversation is text the caller's dataset
viewers have not been shown, and deciding it changes the dataset.
"""

from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.agents.system_agents import CASE_GENERATOR
from app.core.audit import record_audit
from app.core.background import spawn_after_commit
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.case_generation import (
    CaseGeneration,
    CaseOrigin,
    CaseProposal,
    GenerationStatus,
)
from app.repositories import agent_repo, case_generation_repo, credential_repo
from app.schemas.case_generation import (
    CaseGenerationEstimate,
    CaseGenerationList,
    CaseGenerationRead,
    CaseGenerationRequest,
    CaseProposalAccept,
    CaseProposalDismiss,
    CaseProposalList,
    CaseProposalRead,
    SourcePlan,
)
from app.schemas.dataset import DatasetCaseContent, DatasetVersionRead
from app.services.ai_assistance import AiAssistanceService
from app.services.case_generation.drafts import split
from app.services.case_generation.estimate import estimate_cost
from app.services.case_generation.generation import run_generation
from app.services.case_generation.prompt import build_prompt
from app.services.case_generation.sources import Material, SourceGatherer
from app.services.dataset import DatasetService, GeneratedCase, proposals_hidden_from
from app.services.rag.vectorstore import BaseVectorStore
from app.services.system_agent_runner import SystemAgentRunner

# A restart loses a generation mid-run: it runs in the process that answered the
# request. Past any real run's length, a running one is reported as interrupted.
INTERRUPTED_AFTER = timedelta(minutes=30)
INTERRUPTED = "The generation was interrupted before it finished. Start it again."


def _generation_read(generation: CaseGeneration, *, now: datetime) -> CaseGenerationRead:
    read = CaseGenerationRead.model_validate(generation)
    if (
        generation.status == GenerationStatus.RUNNING.value
        and now - generation.created_at > INTERRUPTED_AFTER
    ):
        return read.model_copy(
            update={"status": GenerationStatus.FAILED.value, "error": INTERRUPTED}
        )
    return read


def _material(origin: CaseOrigin, material: Material) -> int:
    if origin is CaseOrigin.KNOWLEDGE:
        return len(material.passages)
    if origin is CaseOrigin.CONVERSATION:
        return len(material.questions)
    if origin is CaseOrigin.AGENT:
        return len(material.agent.tools)
    return 0


def _drafted(proposal: CaseProposal) -> DatasetCaseContent:
    return DatasetCaseContent.model_validate(
        {field: getattr(proposal, field) for field in DatasetCaseContent.model_fields}
    )


class CaseGenerationService:
    """Generate cases for a dataset and decide what was generated."""

    def __init__(self, db: AsyncSession, *, vector_store: BaseVectorStore) -> None:
        self.db = db
        self.datasets = DatasetService(db)
        self.sources = SourceGatherer(db, vector_store)

    async def _plan(
        self, ctx: AuthContext, dataset_id: UUID, data: CaseGenerationRequest
    ) -> tuple[UUID, Material, dict[CaseOrigin, int], str]:
        """The dataset, the material, each source's quota and the prompt for one request.

        Raises:
            NotFoundError: For a dataset the caller may not edit, or an agent they
                may not view.
            AiAssistanceDisabledError: When the organization switched AI assistance off.
            BadRequestError: Naming `sources` or `agent_id`, for a source the caller
                may not use or that has nothing to draft from.
        """
        dataset = await self.datasets.get(ctx, dataset_id, perm=Perm.DATASETS_EDIT)
        await AiAssistanceService(self.db).require_enabled(organization_id=ctx.organization_id)
        sources = [CaseOrigin(source) for source in data.sources]
        quotas = split(data.count, sources)
        material = await self.sources.gather(ctx, data.agent_id, sources)
        return dataset.id, material, quotas, build_prompt(material, quotas)

    async def _price(self, ctx: AuthContext, prompt: str, count: int) -> Decimal | None:
        """The estimated cost on the generator's model, or `None` when it has no price.

        Read without seeding: an organization whose generator is not created yet is
        priced on the profile it would be published on, the oldest one.
        """
        agent = await agent_repo.get_system(
            self.db, organization_id=ctx.organization_id, key=CASE_GENERATOR.key
        )
        profile_id: UUID | None = None
        if agent is None:
            oldest = await credential_repo.oldest_profile(
                self.db, organization_id=ctx.organization_id
            )
            profile_id = oldest.id if oldest is not None else None
        elif agent.current_version_id is not None:
            version = await agent_repo.get_version(
                self.db, agent.current_version_id, organization_id=ctx.organization_id
            )
            profile_id = (
                AgentSpec.model_validate(version.spec).model_profile_id if version else None
            )
        profile = (
            await credential_repo.get_profile(
                self.db, profile_id, organization_id=ctx.organization_id
            )
            if profile_id is not None
            else None
        )
        if profile is None:
            return None
        return estimate_cost(prompt, count, model_name=profile.model, provider=profile.provider)

    async def estimate(
        self, ctx: AuthContext, dataset_id: UUID, data: CaseGenerationRequest
    ) -> CaseGenerationEstimate:
        """What this request would draft from each source, and roughly cost.

        Reads the same material a generation would, under the same gates, and
        calls no model: the estimate is what a person decides with.
        """
        _, material, quotas, prompt = await self._plan(ctx, dataset_id, data)
        return CaseGenerationEstimate(
            count=data.count,
            sources=[
                SourcePlan(source=origin.value, cases=cases, material=_material(origin, material))
                for origin, cases in quotas.items()
            ],
            excluded_collections=material.excluded_collections,
            estimated_cost_usd=await self._price(ctx, prompt, data.count),
        )

    async def start(
        self, ctx: AuthContext, dataset_id: UUID, data: CaseGenerationRequest
    ) -> CaseGenerationRead:
        """Start drafting cases. Answers at once; the generator runs after the commit.

        Raises:
            NotFoundError, AiAssistanceDisabledError, BadRequestError: As
                :meth:`estimate` does.
            SystemAgentUnavailableError: When the generator cannot run for this caller.
        """
        dataset_id, material, quotas, prompt = await self._plan(ctx, dataset_id, data)
        # Refused here with the reason, rather than queued to fail at once; the run
        # checks the same again when it starts.
        await SystemAgentRunner(self.db).require_runnable(ctx, key=CASE_GENERATOR.key)
        generation = await case_generation_repo.create_generation(
            self.db,
            organization_id=ctx.organization_id,
            dataset_id=dataset_id,
            agent_id=data.agent_id,
            requested_by_user_id=ctx.subject_id,
            sources=list(data.sources),
            requested_count=data.count,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="dataset.generation_started",
            target_type="dataset",
            target_id=str(dataset_id),
            details={
                "agent_id": str(data.agent_id),
                "sources": list(data.sources),
                "count": data.count,
            },
        )
        spawn_after_commit(
            self.db,
            run_generation(
                generation_id=generation.id,
                dataset_id=dataset_id,
                ctx=ctx,
                prompt=prompt,
                material=material,
                quotas=quotas,
            ),
            name=f"case-generation-{generation.id}",
        )
        return _generation_read(generation, now=datetime.now(UTC))

    async def list_generations(
        self, ctx: AuthContext, dataset_id: UUID, *, limit: int = 20
    ) -> CaseGenerationList:
        """The dataset's newest generations, with how each went."""
        dataset = await self.datasets.get(ctx, dataset_id, perm=Perm.DATASETS_EDIT)
        generations = await case_generation_repo.list_generations(
            self.db, dataset.id, organization_id=ctx.organization_id, limit=limit
        )
        now = datetime.now(UTC)
        return CaseGenerationList(items=[_generation_read(g, now=now) for g in generations])

    async def list_proposals(
        self,
        ctx: AuthContext,
        dataset_id: UUID,
        *,
        generation_id: UUID | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> CaseProposalList:
        """A page of the drafted cases waiting on this dataset that the caller may read.

        Drafts from chats are left out for a caller who may not view runs, and
        only counted in `hidden`.
        """
        dataset = await self.datasets.get(ctx, dataset_id, perm=Perm.DATASETS_EDIT)
        hidden_origin = proposals_hidden_from(ctx)
        items, total = await case_generation_repo.list_proposals(
            self.db,
            dataset.id,
            organization_id=ctx.organization_id,
            generation_id=generation_id,
            without_origin=hidden_origin,
            skip=skip,
            limit=limit,
        )
        hidden = (
            0
            if hidden_origin is None
            else (
                await case_generation_repo.count_pending(
                    self.db,
                    [dataset.id],
                    organization_id=ctx.organization_id,
                    only_origin=hidden_origin,
                    generation_id=generation_id,
                )
            ).get(dataset.id, 0)
        )
        return CaseProposalList(
            items=[CaseProposalRead.model_validate(item) for item in items],
            total=total,
            hidden=hidden,
        )

    async def _take(
        self, ctx: AuthContext, dataset_id: UUID, ids: list[UUID]
    ) -> list[CaseProposal]:
        """Take proposals out of the queue under the dataset's lock.

        A draft the caller may not read - one from chats, without `runs:view` -
        is not theirs to decide, and stays waiting.

        Raises:
            NotFoundError: When none of them is waiting any more - somebody else
                decided them first, or they never were this dataset's.
        """
        taken = await case_generation_repo.take_proposals(
            self.db,
            dataset_id,
            ids,
            organization_id=ctx.organization_id,
            without_origin=proposals_hidden_from(ctx),
        )
        if not taken:
            raise NotFoundError(
                message="These proposed cases were already decided",
                details={"dataset_id": dataset_id, "ids": ids},
            )
        return taken

    async def _count(self, ctx: AuthContext, taken: list[CaseProposal], *, accepted: bool) -> None:
        per_generation = Counter(proposal.generation_id for proposal in taken)
        await case_generation_repo.count_decisions(
            self.db, dict(per_generation), organization_id=ctx.organization_id, accepted=accepted
        )

    async def accept(
        self, ctx: AuthContext, dataset_id: UUID, data: CaseProposalAccept
    ) -> DatasetVersionRead:
        """Accept drafted cases - as drafted, or as edited - into one new dataset version.

        A proposal somebody else decided meanwhile is skipped; the version holds
        the ones this decision took.

        Raises:
            NotFoundError: For a dataset the caller may not edit, or when none of
                the proposals is still waiting.
        """
        dataset = await self.datasets.lock_for_edit(ctx, dataset_id)
        edits = {item.id: item.content for item in data.items}
        taken = await self._take(ctx, dataset.id, list(edits))
        cases = [
            GeneratedCase(
                content=edits[proposal.id] or _drafted(proposal),
                source_document_id=proposal.source_document_id,
                source_run_id=proposal.source_run_id,
                source_conversation_id=proposal.source_conversation_id,
                source_message_id=proposal.source_message_id,
            )
            for proposal in taken
        ]
        version = await self.datasets.add_generated(ctx, dataset, cases)
        await self._count(ctx, taken, accepted=True)
        return version

    async def dismiss(self, ctx: AuthContext, dataset_id: UUID, data: CaseProposalDismiss) -> None:
        """Dismiss drafted cases. Nothing of them is kept, and the dataset does not change.

        Raises:
            NotFoundError: For a dataset the caller may not edit, or when none of
                the proposals is still waiting.
        """
        dataset = await self.datasets.lock_for_edit(ctx, dataset_id)
        taken = await self._take(ctx, dataset.id, data.ids)
        await self._count(ctx, taken, accepted=False)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="dataset.proposals_dismissed",
            target_type="dataset",
            target_id=str(dataset.id),
            details={"name": dataset.name, "dismissed": len(taken)},
        )
