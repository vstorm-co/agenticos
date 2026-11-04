"""What a bootstrapped organization opens with: the Architect and AgenticOS."""

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.commands.bootstrap import _resolve_starter_agents
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.credential import ModelProfile
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.services.sandbox_connection import SandboxConnectionService
from tests.integration._keys import provider_key

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _no_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    """No sandbox here, so the run never depends on a `sandboxd` that happens to answer."""
    monkeypatch.setattr(
        SandboxConnectionService, "ensure_local_connection", AsyncMock(return_value=None)
    )


async def _owner(db: AsyncSession) -> AuthContext:
    owner = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(owner)
    await db.flush()
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=owner.id, role="owner"))
    await db.flush()
    return AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)


async def _agents(db: AsyncSession, ctx: AuthContext) -> dict[str, Agent]:
    rows = await db.execute(select(Agent).where(Agent.organization_id == ctx.organization_id))
    return {agent.name: agent for agent in rows.scalars()}


async def test_a_new_organization_gets_both_and_nothing_called_getting_started(
    db: AsyncSession,
) -> None:
    ctx = await _owner(db)

    await _resolve_starter_agents(db, ctx, None)

    agents = await _agents(db, ctx)
    assert set(agents) == {"Architect", "AgenticOS"}
    # Visible to the organization, not to the person who ran bootstrap alone.
    assert agents["AgenticOS"].visibility == Visibility.ORG
    assert agents["AgenticOS"].current_version_id is None


async def test_a_second_run_finds_both_and_adds_neither(db: AsyncSession) -> None:
    ctx = await _owner(db)

    await _resolve_starter_agents(db, ctx, None)
    await _resolve_starter_agents(db, ctx, None)

    assert len(await _agents(db, ctx)) == 2


async def test_with_a_model_the_architect_publishes_and_the_starter_runs_on_it(
    db: AsyncSession,
) -> None:
    ctx = await _owner(db)
    profile = ModelProfile(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        label="Model",
        provider="openai",
        model="gpt-4.1",
        secret_id=await provider_key(db, ctx.organization_id),
    )
    db.add(profile)
    await db.flush()

    await _resolve_starter_agents(db, ctx, profile.id)

    agents = await _agents(db, ctx)
    assert agents["Architect"].current_version_id is not None
    starter = agents["AgenticOS"]
    assert starter.draft_spec["model_profile_id"] == str(profile.id)
