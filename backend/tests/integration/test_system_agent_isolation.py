"""A system agent is run by the platform alone, against a real database.

The eval judge is an agent row, but nobody chats with it, exposes it, embeds it,
schedules it or delegates to it: every one of those paths refuses it in the
service, and the runner refuses any run of it outside the eval surface. Its own
runner still reaches it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.agents.spec import AgentSpec
from app.agents.system_agents import JUDGE
from app.core.exceptions import (
    BadRequestError,
    SystemAgentRestrictedError,
    SystemAgentUnavailableError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import ApiKeySecret, SecretKind, seal_secret
from app.core.vault import VaultScope
from app.db.models.agent import Agent, AgentKind
from app.db.models.agent_run import AgentRun, RunSurface
from app.db.models.credential import ModelProfile
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.user import User
from app.schemas.agent_embed import EmbedCreate
from app.schemas.agent_exposure import ExposureCreate
from app.schemas.agent_trigger import TriggerCreate
from app.services.agent_embed import AgentEmbedService
from app.services.agent_exposure import AgentExposureService
from app.services.agent_registry import DELEGATION_CAPABILITY_ID, AgentRegistryService
from app.services.agent_runner import AgentRunnerService
from app.services.agent_trigger import AgentTriggerService
from app.services.system_agent_runner import SystemAgentRunner
from app.services.system_agents import SystemAgentService

pytestmark = pytest.mark.anyio


async def _owner(db) -> AuthContext:
    """An organization with AI assistance on, its owner, and a model with a key."""
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
        ai_assistance_enabled=True,
    )
    db.add(organization)
    await db.flush()
    db.add(
        OrganizationMember(
            id=uuid.uuid4(),
            organization_id=organization.id,
            user_id=user.id,
            role=OrgRoleName.OWNER.value,
        )
    )
    sealed = seal_secret(
        ApiKeySecret(api_key="sk-test-key"), scope=VaultScope.organization(organization.id)
    )
    secret = OrganizationSecret(
        id=uuid.uuid4(),
        organization_id=organization.id,
        name="Key",
        purpose="openai",
        visibility="org",
        kind=SecretKind.API_KEY.value,
        sealed_secret=sealed.ciphertext,
        hint=sealed.hint,
    )
    db.add(secret)
    await db.flush()
    db.add(
        ModelProfile(
            id=uuid.uuid4(),
            organization_id=organization.id,
            label="Default",
            provider="openai",
            model="gpt-4.1",
            secret_id=secret.id,
        )
    )
    await db.flush()
    return AuthContext(user_id=user.id, organization_id=organization.id, role=OrgRoleName.OWNER)


async def _judge(db, ctx: AuthContext) -> Agent:
    return await SystemAgentService(db).ensure(organization_id=ctx.organization_id, key=JUDGE.key)


async def _runs_of(db, agent: Agent) -> list[AgentRun]:
    return list(await db.scalars(select(AgentRun).where(AgentRun.agent_id == agent.id)))


class TestRunning:
    @pytest.mark.parametrize(
        "surface",
        [
            RunSurface.WEB,
            RunSurface.API,
            RunSurface.EMBED,
            RunSurface.SLACK,
            RunSurface.TELEGRAM,
            RunSurface.SCHEDULE,
        ],
    )
    async def test_every_surface_but_eval_refuses_it_before_any_run(self, db, surface) -> None:
        ctx = await _owner(db)
        judge = await _judge(db, ctx)

        with pytest.raises(SystemAgentRestrictedError) as refused:
            await AgentRunnerService(db).execute(ctx, judge.id, "Grade this", surface=surface)

        assert refused.value.details["agent_id"] == judge.id
        assert await _runs_of(db, judge) == []

    async def test_its_own_runner_still_reaches_it(self, db) -> None:
        ctx = await _owner(db)

        agent = await SystemAgentRunner(db).require_runnable(ctx, key=JUDGE.key)

        assert agent.system_key == JUDGE.key


class TestAttaching:
    async def test_it_cannot_be_put_on_a_channel(self, db) -> None:
        ctx = await _owner(db)
        judge = await _judge(db, ctx)

        with pytest.raises(SystemAgentRestrictedError, match="a channel"):
            await AgentExposureService(db).create(
                ctx, judge.id, ExposureCreate(channel_bot_id=uuid.uuid4())
            )

    async def test_it_cannot_be_embedded_or_given_a_public_page(self, db) -> None:
        ctx = await _owner(db)
        judge = await _judge(db, ctx)

        with pytest.raises(SystemAgentRestrictedError, match="an embed"):
            await AgentEmbedService(db).create(
                ctx,
                EmbedCreate.model_validate(
                    {"agent_id": str(judge.id), "name": "Judge", "config": {"kind": "page"}}
                ),
            )

    async def test_it_cannot_be_scheduled(self, db) -> None:
        ctx = await _owner(db)
        judge = await _judge(db, ctx)

        with pytest.raises(SystemAgentRestrictedError, match="a schedule"):
            await AgentTriggerService(db).create(
                ctx, judge.id, TriggerCreate(prompt="Grade", interval_seconds=3600)
            )

    async def test_no_agent_can_publish_with_it_as_a_delegate(self, db) -> None:
        ctx = await _owner(db)
        judge = await _judge(db, ctx)
        spec = AgentSpec.model_validate(
            {
                "name": "Coordinator",
                "capabilities": [{"id": DELEGATION_CAPABILITY_ID}],
                "subagents": [
                    {
                        "agent_id": str(judge.id),
                        "agent_version_id": str(judge.current_version_id),
                    }
                ],
            }
        )

        with pytest.raises(BadRequestError) as refused:
            await AgentRegistryService(db).validate_spec(ctx, spec)

        assert any("is a judge" in problem for problem in refused.value.details["problems"])


class TestADatasetsOwnJudge:
    async def test_it_is_refused_everywhere_the_seeded_judge_is(self, db) -> None:
        ctx = await _owner(db)
        own = await SystemAgentService(db).create_judge(
            ctx, name="Refunds judge", description="Grades refunds.", instructions="Be strict."
        )

        with pytest.raises(SystemAgentRestrictedError):
            await AgentRunnerService(db).execute(ctx, own.id, "Grade this", surface=RunSurface.WEB)
        with pytest.raises(SystemAgentRestrictedError, match="a channel"):
            await AgentExposureService(db).create(
                ctx, own.id, ExposureCreate(channel_bot_id=uuid.uuid4())
            )
        assert await _runs_of(db, own) == []

    async def test_its_own_runner_reaches_it_by_id(self, db) -> None:
        ctx = await _owner(db)
        own = await SystemAgentService(db).create_judge(
            ctx, name="Refunds judge", description="Grades refunds.", instructions="Be strict."
        )

        agent = await SystemAgentRunner(db).require_runnable(ctx, key=JUDGE.key, agent_id=own.id)

        assert agent.id == own.id

    async def test_an_ordinary_agent_picked_as_the_judge_is_missing(self, db) -> None:
        ctx = await _owner(db)
        mine = await AgentRegistryService(db).create(ctx, AgentSpec(name="Support"))

        with pytest.raises(SystemAgentUnavailableError) as refused:
            await SystemAgentRunner(db).require_runnable(ctx, key=JUDGE.key, agent_id=mine.id)

        assert refused.value.reason == "missing"


class TestListing:
    async def test_judges_are_listed_apart_from_the_organization_s_agents(self, db) -> None:
        ctx = await _owner(db)
        judge = await _judge(db, ctx)
        own = await SystemAgentService(db).create_judge(
            ctx, name="Refunds judge", description="Grades refunds.", instructions="Be strict."
        )
        registry = AgentRegistryService(db)
        mine = await registry.create(ctx, AgentSpec(name="Support"))

        listed, total = await registry.list_agents(ctx)
        judges, judge_total = await registry.list_agents(ctx, kind=AgentKind.JUDGE)

        assert ([agent.id for agent in listed], total) == ([mine.id], 1)
        assert ({agent.id for agent in judges}, judge_total) == ({judge.id, own.id}, 2)
