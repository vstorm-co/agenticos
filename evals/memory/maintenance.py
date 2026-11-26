"""Replay frozen sessions through the production AgenticOS extraction handler."""

from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID, uuid4

from dataset import Query, Session
from retrieval import Evidence, Retrieved
from sqlalchemy import make_url, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.config import settings
from app.core.memory_keys import person_owner_key
from app.db.models.agent import Agent, AgentStatus, AgentVersion
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.conversation import Conversation, Message
from app.db.models.credential import ModelProfile
from app.db.models.organization import OrganizationMember
from app.db.models.system_agent_profile import MEMORY_MAINTENANCE, SystemAgentProfile
from app.db.models.user import User
from app.repositories.memory_claim import ClaimScope
from app.services.memory._claims import recall
from app.services.memory.extraction import _allows_personal, _memory_binding
from app.worker.jobs import ExtractMemory
from app.worker.tasks.memory_tasks import extract_memory


@dataclass(frozen=True)
class Starter:
    organization_id: UUID
    agent_id: UUID
    version_id: UUID


async def check_setup(engine: AsyncEngine, agent_id: UUID, model_id: str) -> Starter:
    if engine.url != make_url(settings.DATABASE_URL):
        # The production handler opens its own session from the application settings.
        raise ValueError(
            "Set POSTGRES_* and MEMORY_BENCH_AGENTICOS_DSN to the same disposable database."
        )
    async with AsyncSession(engine) as db:
        agent = await db.get(Agent, agent_id)
        if (
            agent is None
            or agent.status != AgentStatus.PUBLISHED.value
            or agent.current_version_id is None
        ):
            raise ValueError(
                "Use the published starter agent in the disposable benchmark database."
            )
        version = await db.get(AgentVersion, agent.current_version_id)
        binding = (
            _memory_binding(version.spec)
            if version
            and version.agent_id == agent.id
            and version.organization_id == agent.organization_id
            else None
        )
        if binding is None or not _allows_personal(binding):
            raise ValueError("The published starter must allow personal memory.")
        profile = await db.get(SystemAgentProfile, (agent.organization_id, MEMORY_MAINTENANCE))
        model = (
            await db.get(ModelProfile, profile.model_profile_id)
            if profile and profile.enabled and profile.model_profile_id
            else None
        )
        if (
            model is None
            or model.organization_id != agent.organization_id
            or model.provider != "openrouter"
            or model.model != model_id
            or model.fallback_profile_ids
            or model.params.get("thinking") != "low"
        ):
            raise ValueError(
                "Configure the same OpenRouter extraction model at low effort for maintenance."
            )
        if profile is None or profile.monthly_budget_usd is None or profile.monthly_budget_usd <= 0:
            raise ValueError(
                "Set a positive memory maintenance budget in the disposable organization."
            )
        return Starter(agent.organization_id, agent.id, agent.current_version_id)


async def seed_session(
    db: AsyncSession, starter: Starter, user_id: UUID, session: Session
) -> tuple[UUID, UUID]:
    conversation_id, run_id = uuid4(), uuid4()
    db.add(
        Conversation(id=conversation_id, organization_id=starter.organization_id, user_id=user_id)
    )
    await db.flush()
    now = datetime.now(UTC)
    db.add(
        AgentRun(
            id=run_id,
            organization_id=starter.organization_id,
            user_id=user_id,
            agent_id=starter.agent_id,
            agent_version_id=starter.version_id,
            conversation_id=conversation_id,
            status=RunStatus.COMPLETED.value,
            surface=RunSurface.WEB.value,
            started_at=now,
            ended_at=now,
        )
    )
    await db.flush()
    db.add_all(
        [
            Message(
                conversation_id=conversation_id,
                run_id=run_id,
                role=turn.role,
                content=turn.content,
                created_at=session.date,
            )
            for turn in session.turns
        ]
    )
    await db.commit()
    return conversation_id, run_id


async def replay_maintenance(
    engine: AsyncEngine, starter: Starter, query: Query, top_k: int
) -> Retrieved:
    started = perf_counter()
    user_id = uuid4()
    sources: dict[UUID, Session] = {}
    async with AsyncSession(engine) as db:
        db.add(User(id=user_id, email=f"{user_id}@memory-bench.invalid"))
        await db.flush()
        db.add(
            OrganizationMember(
                organization_id=starter.organization_id, user_id=user_id, role="member"
            )
        )
        await db.commit()
        for session in query.sessions:
            conversation_id, run_id = await seed_session(db, starter, user_id, session)
            sources[conversation_id] = session
            await extract_memory(
                ExtractMemory(organization_id=starter.organization_id, run_id=run_id)
            )

        runs = (
            await db.scalars(
                select(AgentRun).where(
                    AgentRun.organization_id == starter.organization_id,
                    AgentRun.user_id == user_id,
                    AgentRun.system_role == MEMORY_MAINTENANCE,
                )
            )
        ).all()
        expected = sum(
            any(turn.role == "user" and turn.content.strip() for turn in session.turns)
            for session in query.sessions
        )
        if len(runs) != expected or any(
            run.status != RunStatus.COMPLETED.value or not run.input_tokens for run in runs
        ):
            raise ValueError(
                "Maintenance did not complete a model-backed run for each user-bearing session."
            )
        cost = (
            None
            if any(run.cost_is_partial for run in runs)
            else float(sum(run.cost_usd for run in runs))
        )
        indexed = perf_counter()
        owner_key = person_owner_key(user_id)
        hits = await recall(
            db,
            organization_id=starter.organization_id,
            scopes=[ClaimScope(owner_key, starter.agent_id), ClaimScope(owner_key)],
            query=query.question,
            limit=top_k,
        )
        retrieved = perf_counter()
        evidence = []
        for claim in hits:
            source = (
                sources.get(claim.source_conversation_id) if claim.source_conversation_id else None
            )
            evidence.append(
                Evidence(
                    source_id=source.id if source else None,
                    text=claim.statement,
                    date=source.date if source else None,
                )
            )
    return Retrieved(evidence, (indexed - started) * 1_000, (retrieved - indexed) * 1_000, cost)
