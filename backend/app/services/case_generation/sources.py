"""What the case generator is shown, gathered under the caller's own access.

Every source a person picks has its own gate, checked here and nowhere else, and
a source the caller may not use is refused by name rather than quietly left out:
a dataset that silently lacks the cases somebody asked for reads as the
generator's failure, not as the permission it was.

The generator itself has no tools. Everything it sees is gathered here, bounded
and deterministic, and handed over in the prompt - so the only thing a hostile
document or conversation can steer is the text of a proposal a person reviews.
Text from conversations and documents is redacted before it leaves for the
model, the same way a case is redacted before it is stored.
"""

from dataclasses import dataclass, field
from typing import cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import get as get_capability
from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent
from app.db.models.case_generation import CaseOrigin
from app.db.models.knowledge_base import KnowledgeBase
from app.repositories import agent_repo, agent_run_repo, knowledge_base_repo, rag_document_repo
from app.services.access import COLLECTION, SKILL, resolve_access
from app.services.agent_registry import AgentRegistryService
from app.services.dataset import redact_credentials
from app.services.rag.vectorstore import BaseVectorStore
from app.services.skills import SkillService

# How much of each source one generation reads. Fixed, so what a generation
# costs and what it saw follow from the agent rather than from chance.
MAX_DOCUMENTS = 12
PASSAGES_PER_DOCUMENT = 3
DOCUMENT_POOL = 500
MAX_QUESTIONS = 60
MAX_INSTRUCTIONS = 12_000
MAX_SKILL_BODY = 2_000
MAX_PASSAGE = 1_500
MAX_QUESTION = 2_000


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    # Whether calling it changes something; only such a call is a case's to expect.
    writes: bool


@dataclass(frozen=True)
class SkillSummary:
    name: str
    description: str
    body: str


@dataclass(frozen=True)
class AgentMaterial:
    """The agent as its instructions, skills and tools describe it."""

    name: str
    description: str | None
    instructions: str
    skills: list[SkillSummary]
    tools: list[Tool]


@dataclass(frozen=True)
class Passage:
    """A piece of a knowledge base document, as the generator cites it."""

    ref: str
    document_id: UUID
    filename: str
    page: int
    text: str


@dataclass(frozen=True)
class Question:
    """A question somebody asked the agent, as the generator cites it."""

    ref: str
    message_id: UUID
    conversation_id: UUID
    run_id: UUID
    text: str
    rated_down: bool
    comment: str | None
    askers: tuple[UUID, ...] = ()
    """Whose question it is, as an erasure counts it (`AskedQuestion.askers`)."""


@dataclass
class Material:
    """Everything one generation shows the generator, and what was left out."""

    agent: AgentMaterial
    passages: list[Passage] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    # Collections the agent binds that the caller may not read.
    excluded_collections: int = 0


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + " [...]"


def _redacted(text: str) -> str:
    cleaned, _ = redact_credentials(text)
    return cleaned or ""


def spread[T](items: list[T], count: int) -> list[T]:
    """`count` items picked evenly from first to last, in order - all of them if fewer."""
    if len(items) <= count:
        return list(items)
    if count == 1:
        return [items[0]]
    step = (len(items) - 1) / (count - 1)
    return [items[round(index * step)] for index in range(count)]


class SourceGatherer:
    """Reads what one generation is drafted from, refusing what the caller may not use."""

    def __init__(self, db: AsyncSession, vector_store: BaseVectorStore) -> None:
        self.db = db
        self.vector_store = vector_store

    async def gather(self, ctx: AuthContext, agent_id: UUID, sources: list[CaseOrigin]) -> Material:
        """The material for these sources, about this agent.

        Raises:
            NotFoundError: For an agent the caller may not view.
            BadRequestError: Naming `sources`, for a source the caller may not use
                or that has nothing to draft from.
        """
        agent = await AgentRegistryService(self.db).get(ctx, agent_id, perm=Perm.AGENTS_VIEW)
        spec = await self._spec(ctx, agent)
        material = Material(agent=await self._agent(ctx, agent, spec))
        if CaseOrigin.KNOWLEDGE in sources:
            await self._knowledge(ctx, spec, material)
        if CaseOrigin.CONVERSATION in sources:
            await self._conversations(ctx, agent, material)
        return material

    async def _spec(self, ctx: AuthContext, agent: Agent) -> AgentSpec:
        """The published spec, or the draft of an agent that was never published."""
        published = agent.current_version_id
        version = (
            await agent_repo.get_version(self.db, published, organization_id=ctx.organization_id)
            if published is not None
            else None
        )
        if version is not None:
            return AgentSpec.model_validate(version.spec)
        try:
            return AgentSpec.model_validate(agent.draft_spec)
        except ValidationError:
            raise refused_field(
                "agent_id",
                "This agent's draft is not complete enough to draft cases from. "
                "Finish or publish it first.",
            ) from None

    async def _agent(self, ctx: AuthContext, agent: Agent, spec: AgentSpec) -> AgentMaterial:
        # A run reads its agent's skills whoever runs it; this prompt quotes their
        # bodies to the caller, so only the skills the caller may view go in.
        skills = [
            skill
            for skill in await SkillService(self.db).resolve_for_agent(ctx, list(spec.skill_ids))
            if await resolve_access(self.db, ctx, skill, Perm.SKILLS_VIEW, resource_type=SKILL)
        ]
        tools: list[Tool] = []
        for binding in spec.capabilities:
            if not binding.enabled:
                continue
            try:
                capability = get_capability(binding.id)
            except BadRequestError:
                # A capability this deployment no longer ships contributes no tools.
                continue
            for tool in capability.effective_tools(binding.tool_overrides):
                tools.append(
                    Tool(
                        name=tool.name,
                        description=tool.description,
                        writes=not capability.tool_is_read_only(tool),
                    )
                )
        return AgentMaterial(
            name=agent.name,
            description=agent.description,
            instructions=_clip(spec.instructions, MAX_INSTRUCTIONS),
            skills=[
                SkillSummary(
                    name=skill.name,
                    description=skill.description or "",
                    body=_clip(skill.content, MAX_SKILL_BODY),
                )
                for skill in skills
            ],
            tools=tools,
        )

    async def _readable_collections(
        self, ctx: AuthContext, spec: AgentSpec
    ) -> tuple[list[KnowledgeBase], int]:
        bound = await knowledge_base_repo.get_in_organization(
            self.db, list(spec.collection_ids), organization_id=ctx.organization_id
        )
        readable = [
            kb
            for kb in bound
            if await resolve_access(
                self.db, ctx, kb, Perm.COLLECTIONS_VIEW, resource_type=COLLECTION
            )
        ]
        return readable, len(bound) - len(readable)

    async def _knowledge(self, ctx: AuthContext, spec: AgentSpec, material: Material) -> None:
        if not spec.collection_ids:
            raise refused_field("sources", "This agent has no knowledge base to draft cases from")
        readable, excluded = await self._readable_collections(ctx, spec)
        material.excluded_collections = excluded
        if not readable:
            raise refused_field(
                "sources", "You cannot read any of the knowledge bases this agent uses"
            )
        by_id = {kb.id: kb for kb in readable}
        documents = await rag_document_repo.indexed_in(
            self.db, list(by_id), organization_id=ctx.organization_id, limit=DOCUMENT_POOL
        )
        for document in spread(documents, MAX_DOCUMENTS):
            if not document.vector_document_id:
                continue
            # `indexed_in` reads documents through their collection, so one is set.
            kb = by_id[cast(UUID, document.knowledge_base_id)]
            chunks = await self.vector_store.get_document_chunks(
                kb.collection_name, document.vector_document_id, kb.vector_tenant
            )
            for chunk in spread([c for c in chunks if c.content.strip()], PASSAGES_PER_DOCUMENT):
                material.passages.append(
                    Passage(
                        ref=f"P{len(material.passages) + 1}",
                        document_id=document.id,
                        filename=document.filename,
                        page=chunk.page_num,
                        text=_redacted(_clip(chunk.content, MAX_PASSAGE)),
                    )
                )
        if not material.passages:
            raise refused_field(
                "sources", "This agent's knowledge bases have no indexed text to draft cases from"
            )

    async def _conversations(self, ctx: AuthContext, agent: Agent, material: Material) -> None:
        if not ctx.has(Perm.RUNS_VIEW):
            raise refused_field(
                "sources", "Drafting cases from conversations needs permission to view runs"
            )
        asked = await agent_run_repo.questions_asked(
            self.db, organization_id=ctx.organization_id, agent_id=agent.id, limit=MAX_QUESTIONS
        )
        if not asked:
            raise refused_field("sources", "Nobody has asked this agent anything yet")
        material.questions = [
            Question(
                ref=f"C{index}",
                message_id=question.message_id,
                conversation_id=question.conversation_id,
                run_id=question.run_id,
                text=_redacted(_clip(question.content, MAX_QUESTION)),
                rated_down=question.rated_down,
                comment=_redacted(question.comment) if question.comment else None,
                askers=question.askers,
            )
            for index, question in enumerate(asked, start=1)
        ]
