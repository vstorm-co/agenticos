"""Whose platform authority a resumed run carries - never the resumer's own.

A run resumed after an approval is rebuilt on its own person's membership. A run
with no person - a visitor's on a public surface, or one whose starter was deleted
after it parked - has nobody's authority to rebuild, and the approver releasing
it must not fill the gap with theirs. A run the publisher stands in for gets none
either, whoever resumes it: the conversation is a visitor's.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec, PlatformMcpServerRef
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.api_key import ApiKey
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.services.agent_runner import AgentRunnerService

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
_SPEC = AgentSpec(
    name="Helper", mcp_servers=[PlatformMcpServerRef(account="platform", approval="writes")]
)


async def _user(db: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db: AsyncSession) -> Organization:
    founder = await _user(db)
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(org)
    await db.flush()
    return org


async def _member(db: AsyncSession, org: Organization, role: OrgRoleName) -> AuthContext:
    user = await _user(db)
    db.add(
        OrganizationMember(
            id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role=role.value
        )
    )
    await db.flush()
    return AuthContext(user_id=user.id, organization_id=org.id, role=role.value)


async def _parked(
    db: AsyncSession,
    org: Organization,
    *,
    person: uuid.UUID | None,
    publisher_fallback: bool = False,
    key_scopes: list[str] | None = None,
) -> AgentRun:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=f"helper-{uuid.uuid4().hex[:8]}",
        name="Helper",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        user_id=person,
        initiated_by_publisher_fallback=publisher_fallback,
        key_scopes=key_scopes,
        status=RunStatus.AWAITING_APPROVAL.value,
        surface=RunSurface.EMBED.value if publisher_fallback else RunSurface.WEB.value,
        started_at=_NOW,
    )
    db.add(run)
    await db.commit()
    return run


async def _keys_of(db: AsyncSession, user_id: uuid.UUID | None) -> int:
    return (
        await db.execute(select(func.count()).select_from(ApiKey).where(ApiKey.user_id == user_id))
    ).scalar_one()


async def test_a_visitors_run_resumed_by_an_admin_gets_no_platform_authority(db: AsyncSession):
    org = await _org(db)
    admin = await _member(db, org, OrgRoleName.ADMIN)
    run = await _parked(db, org, person=None, publisher_fallback=True)
    runner = AgentRunnerService(db)

    assert await runner._platform_credential(_SPEC, admin, run) is None
    assert await runner._run_owner_context(admin, run) is None
    assert await _keys_of(db, admin.user_id) == 0


async def test_a_run_whose_person_was_deleted_resumes_with_no_platform_authority(
    db: AsyncSession,
):
    org = await _org(db)
    admin = await _member(db, org, OrgRoleName.ADMIN)
    departed = await _member(db, org, OrgRoleName.BUILDER)
    run = await _parked(db, org, person=departed.user_id)
    await db.delete(await db.get(User, departed.user_id))
    await db.commit()
    await db.refresh(run)
    assert run.user_id is None
    runner = AgentRunnerService(db)

    assert await runner._platform_credential(_SPEC, admin, run) is None
    assert await runner._run_owner_context(admin, run) is None
    assert await _keys_of(db, admin.user_id) == 0


async def test_the_publisher_resuming_their_visitors_run_gets_no_platform_authority(
    db: AsyncSession,
):
    """The publisher names the run's subject; the conversation is still a visitor's."""
    org = await _org(db)
    publisher = await _member(db, org, OrgRoleName.ADMIN)
    run = await _parked(db, org, person=publisher.user_id, publisher_fallback=True)
    runner = AgentRunnerService(db)

    assert await runner._platform_credential(_SPEC, publisher, run) is None
    owner = await runner._run_owner_context(publisher, run)
    assert owner is not None and owner.subject_is_publisher_fallback
    assert await _keys_of(db, publisher.user_id) == 0


async def test_an_owned_run_resumed_by_another_carries_the_owners_role_under_its_key(
    db: AsyncSession,
):
    org = await _org(db)
    admin = await _member(db, org, OrgRoleName.ADMIN)
    builder = await _member(db, org, OrgRoleName.BUILDER)
    run = await _parked(
        db, org, person=builder.user_id, key_scopes=[Perm.AGENTS_VIEW.value, "not-a-scope"]
    )

    owner = await AgentRunnerService(db)._run_owner_context(admin, run)

    assert owner is not None
    assert (owner.user_id, owner.role) == (builder.user_id, OrgRoleName.BUILDER.value)
    assert owner.key_scopes == frozenset({Perm.AGENTS_VIEW})
    assert not owner.subject_is_publisher_fallback


async def test_the_runs_own_person_still_gets_their_platform_key(db: AsyncSession):
    org = await _org(db)
    builder = await _member(db, org, OrgRoleName.BUILDER)
    run = await _parked(db, org, person=builder.user_id)

    assert await AgentRunnerService(db)._platform_credential(_SPEC, builder, run) is not None
    assert await _keys_of(db, builder.user_id) == 1
