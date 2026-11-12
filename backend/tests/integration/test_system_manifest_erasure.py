"""Erasing a person also trims what the system roles kept of their memory.

A memory-maintenance run's manifest holds the transcript it read and the facts it
drew from it; a daily briefing's holds the person's notes and requests it read.
Both runs are attributed to the person, not linked to their memory - so deleting
the notes and claims alone left those copies behind.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.run_manifest import RunManifest
from app.db.models.system_agent_profile import DAILY_BRIEFING, MEMORY_MAINTENANCE
from app.db.models.user import User
from app.services.access import member_context
from app.services.memory import MemoryService
from app.services.personal_data import PersonalDataService

pytestmark = [pytest.mark.anyio, pytest.mark.security]

SECRET = "Ada's bank PIN is 4321"


async def _user(db: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    return user


async def _org(db: AsyncSession, *members: User) -> tuple[Organization, Agent]:
    org = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=members[0].id
    )
    db.add(org)
    await db.flush()
    db.add_all(
        OrganizationMember(organization_id=org.id, user_id=member.id, role="owner")
        for member in members
    )
    agent = Agent(organization_id=org.id, name="Helper", slug=f"a-{uuid.uuid4().hex[:8]}")
    db.add(agent)
    await db.flush()
    return org, agent


async def _manifest(
    db: AsyncSession, org: Organization, agent: Agent, user: User, *, role: str | None
) -> RunManifest:
    run = AgentRun(
        organization_id=org.id,
        agent_id=agent.id,
        user_id=user.id,
        surface="proactive",
        system_role=role,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    await db.flush()
    manifest = RunManifest(
        run_id=run.id,
        organization_id=org.id,
        payload={
            "instructions": "Extract durable facts.",
            "messages": [f"Conversation:\n\n{SECRET}"],
            "transcript": [{"parts": [{"content": SECRET}]}],
        },
    )
    db.add(manifest)
    await db.flush()
    return manifest


async def _payload(db: AsyncSession, manifest: RunManifest) -> dict[str, object]:
    await db.refresh(manifest)
    return manifest.payload


@pytest.mark.parametrize("role", [MEMORY_MAINTENANCE, DAILY_BRIEFING])
async def test_forget_me_trims_the_persons_system_manifests_in_that_organization(
    db: AsyncSession, role: str
) -> None:
    person, colleague = await _user(db), await _user(db)
    org, agent = await _org(db, person, colleague)
    elsewhere, other_agent = await _org(db, person)
    theirs = await _manifest(db, org, agent, person, role=role)
    colleagues = await _manifest(db, org, agent, colleague, role=role)
    other_org = await _manifest(db, elsewhere, other_agent, person, role=role)
    own_chat = await _manifest(db, org, agent, person, role=None)
    ctx = await member_context(db, organization_id=org.id, user_id=person.id)
    assert ctx is not None

    await MemoryService(db).forget_person(ctx, person.id)

    assert await _payload(db, theirs) == {"instructions": "Extract durable facts."}
    assert theirs.truncated
    assert "messages" in await _payload(db, colleagues)
    # "Forget me" is per organization; the person is still a member elsewhere.
    assert "messages" in await _payload(db, other_org)
    assert "messages" in await _payload(db, own_chat)


@pytest.mark.parametrize("role", [MEMORY_MAINTENANCE, DAILY_BRIEFING])
async def test_deleting_the_account_trims_its_system_manifests_everywhere(
    db: AsyncSession, role: str
) -> None:
    person, colleague = await _user(db), await _user(db)
    org, agent = await _org(db, colleague, person)
    elsewhere, other_agent = await _org(db, colleague, person)
    here = await _manifest(db, org, agent, person, role=role)
    there = await _manifest(db, elsewhere, other_agent, person, role=role)
    colleagues = await _manifest(db, org, agent, colleague, role=role)

    await PersonalDataService(db).purge(person.id)

    for manifest in (here, there):
        payload = await _payload(db, manifest)
        assert "messages" not in payload and "transcript" not in payload
        assert SECRET not in str(payload)
    assert "messages" in await _payload(db, colleagues)
