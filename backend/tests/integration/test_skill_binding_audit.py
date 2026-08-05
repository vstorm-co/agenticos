"""The `audit-skill-bindings` sweep against a real database.

#179 added a publish-time check that a bound skill is one the publisher can
reach. This sweep is its offline half - it finds versions frozen *before* that
check that still hand a private skill to every run. The property that cannot be
faked with mocks, and the reason this test exists, is that the answer is about
the rows and not about the publisher's role today: promoting the publisher after
a bad publish must not make the exposure disappear. The unit suite in
`tests/test_audit_skill_bindings.py` covers the decisions; this proves the whole
scan, including the join that selects the running version, behaves that way.
"""

from __future__ import annotations

import uuid

import pytest

from app.commands import audit_skill_bindings as sweep
from app.commands.audit_skill_bindings import BindingStatus
from app.core.permissions import OrgRoleName
from app.db.models.agent import Agent, AgentStatus, AgentVersion
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.skill import Skill
from app.db.models.user import User

pytestmark = pytest.mark.anyio


async def _user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _org_with_owner(db) -> tuple[Organization, User]:
    owner = await _user(db)
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(org)
    await db.flush()
    return org, owner


async def _member(db, org: Organization, user: User, role: OrgRoleName) -> OrganizationMember:
    member = OrganizationMember(
        id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role=role.value
    )
    db.add(member)
    await db.flush()
    return member


async def _skill(db, org: Organization, owner: User, *, visibility: Visibility) -> Skill:
    skill = Skill(
        id=uuid.uuid4(),
        organization_id=org.id,
        owner_user_id=owner.id,
        name=f"skill-{uuid.uuid4().hex[:8]}",
        description="private know-how",
        content="do the thing",
        visibility=visibility.value,
    )
    db.add(skill)
    await db.flush()
    return skill


async def _published_agent(
    db, org: Organization, *, skill_id: uuid.UUID, publisher_id: uuid.UUID | None
) -> Agent:
    """A published agent whose current version binds one skill."""
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=f"agent-{uuid.uuid4().hex[:6]}",
        name="Support",
        description=None,
        draft_spec={"name": "Support", "skill_ids": [str(skill_id)]},
        status=AgentStatus.PUBLISHED.value,
    )
    db.add(agent)
    await db.flush()
    version = AgentVersion(
        id=uuid.uuid4(),
        agent_id=agent.id,
        organization_id=org.id,
        version=1,
        spec={"name": "Support", "skill_ids": [str(skill_id)]},
        published_by_user_id=publisher_id,
    )
    db.add(version)
    await db.flush()
    agent.current_version_id = version.id
    await db.flush()
    return agent


async def _agent(db, org: Organization, *, name: str = "Support") -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=f"agent-{uuid.uuid4().hex[:6]}",
        name=name,
        description=None,
        draft_spec={"name": name},
        status=AgentStatus.PUBLISHED.value,
    )
    db.add(agent)
    await db.flush()
    return agent


async def _version(
    db,
    agent: Agent,
    org: Organization,
    *,
    number: int,
    skill_id: uuid.UUID | None = None,
    publisher_id: uuid.UUID | None = None,
    subagents: list[dict] | None = None,
) -> AgentVersion:
    spec: dict = {"name": agent.name}
    if skill_id is not None:
        spec["skill_ids"] = [str(skill_id)]
    if subagents is not None:
        spec["subagents"] = subagents
    version = AgentVersion(
        id=uuid.uuid4(),
        agent_id=agent.id,
        organization_id=org.id,
        version=number,
        spec=spec,
        published_by_user_id=publisher_id,
    )
    db.add(version)
    await db.flush()
    return version


async def _environment(
    db, agent: Agent, org: Organization, version: AgentVersion, *, name: str, is_default: bool
) -> AgentEnvironment:
    env = AgentEnvironment(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        name=name,
        version_id=version.id,
        is_default=is_default,
    )
    db.add(env)
    await db.flush()
    return env


class TestTheSweepFindsAnOutOfReachBinding:
    async def test_a_private_skill_bound_by_a_non_owner_is_exposed(self, db) -> None:
        org, _ = await _org_with_owner(db)
        author = await _user(db)
        colleague = await _user(db)
        await _member(db, org, author, OrgRoleName.MEMBER)
        skill = await _skill(db, org, colleague, visibility=Visibility.PRIVATE)
        agent = await _published_agent(db, org, skill_id=skill.id, publisher_id=author.id)

        findings = await sweep._scan(db)

        mine = [f for f in findings if f.agent_slug == agent.slug]
        assert len(mine) == 1
        assert mine[0].status is BindingStatus.EXPOSED
        assert mine[0].skill_id == skill.id

    async def test_it_is_still_found_after_the_publisher_is_promoted(self, db) -> None:
        """The heart of #186. A Builder's role reaches every skill, so re-deriving
        access today would clear this - which is exactly the mistake. The frozen
        binding is unchanged, so the sweep must still report it."""
        org, _ = await _org_with_owner(db)
        author = await _user(db)
        colleague = await _user(db)
        membership = await _member(db, org, author, OrgRoleName.MEMBER)
        skill = await _skill(db, org, colleague, visibility=Visibility.PRIVATE)
        agent = await _published_agent(db, org, skill_id=skill.id, publisher_id=author.id)

        membership.role = OrgRoleName.BUILDER.value
        await db.flush()

        findings = await sweep._scan(db)

        mine = [f for f in findings if f.agent_slug == agent.slug]
        assert len(mine) == 1
        assert mine[0].status is BindingStatus.EXPOSED

    async def test_a_binding_whose_publisher_is_gone_is_unknown(self, db) -> None:
        org, _ = await _org_with_owner(db)
        colleague = await _user(db)
        skill = await _skill(db, org, colleague, visibility=Visibility.PRIVATE)
        agent = await _published_agent(db, org, skill_id=skill.id, publisher_id=None)

        findings = await sweep._scan(db)

        mine = [f for f in findings if f.agent_slug == agent.slug]
        assert len(mine) == 1
        assert mine[0].status is BindingStatus.UNKNOWN


class TestTheSweepReachesVersionsOtherThanTheDefault:
    """The gap #248's first pass had: a run does not always load
    `current_version_id`. A named environment can pin an older version, and a
    parent can pin a delegate version - both execute, so both must be scanned."""

    async def test_a_named_environment_pinned_to_an_unsafe_older_version_is_found(self, db) -> None:
        org, _ = await _org_with_owner(db)
        author = await _user(db)
        colleague = await _user(db)
        await _member(db, org, author, OrgRoleName.MEMBER)
        private = await _skill(db, org, colleague, visibility=Visibility.PRIVATE)
        own = await _skill(db, org, author, visibility=Visibility.PRIVATE)

        agent = await _agent(db, org)
        unsafe = await _version(
            db, agent, org, number=1, skill_id=private.id, publisher_id=author.id
        )
        safe = await _version(db, agent, org, number=2, skill_id=own.id, publisher_id=author.id)
        agent.current_version_id = safe.id
        await db.flush()
        await _environment(db, agent, org, safe, name="default", is_default=True)
        await _environment(db, agent, org, unsafe, name="production", is_default=False)

        findings = await sweep._scan(db)

        mine = [f for f in findings if f.agent_slug == agent.slug]
        assert len(mine) == 1
        assert mine[0].version_number == 1
        assert mine[0].skill_id == private.id

    async def test_a_delegate_version_reached_only_through_a_pin_is_found(self, db) -> None:
        org, _ = await _org_with_owner(db)
        author = await _user(db)
        colleague = await _user(db)
        await _member(db, org, author, OrgRoleName.MEMBER)
        private = await _skill(db, org, colleague, visibility=Visibility.PRIVATE)

        delegate = await _agent(db, org, name="Researcher")
        unsafe = await _version(
            db, delegate, org, number=1, skill_id=private.id, publisher_id=author.id
        )
        safe = await _version(db, delegate, org, number=2, publisher_id=author.id)
        delegate.current_version_id = safe.id  # the delegate's own default is clean
        await db.flush()

        parent = await _agent(db, org, name="Boss")
        parent_v = await _version(
            db,
            parent,
            org,
            number=1,
            publisher_id=author.id,
            subagents=[{"agent_id": str(delegate.id), "agent_version_id": str(unsafe.id)}],
        )
        parent.current_version_id = parent_v.id
        await db.flush()

        findings = await sweep._scan(db)

        mine = [f for f in findings if f.agent_slug == delegate.slug]
        assert len(mine) == 1
        assert mine[0].version_number == 1
        assert mine[0].skill_id == private.id

    async def test_a_pin_to_an_archived_delegate_is_not_reported(self, db) -> None:
        """The runner refuses to delegate to an archived agent, so its pinned
        version can no longer load - the sweep must not flag it."""
        org, _ = await _org_with_owner(db)
        author = await _user(db)
        colleague = await _user(db)
        await _member(db, org, author, OrgRoleName.MEMBER)
        private = await _skill(db, org, colleague, visibility=Visibility.PRIVATE)

        delegate = await _agent(db, org, name="Researcher")
        unsafe = await _version(
            db, delegate, org, number=1, skill_id=private.id, publisher_id=author.id
        )
        delegate.current_version_id = unsafe.id
        delegate.status = AgentStatus.ARCHIVED.value
        await db.flush()

        parent = await _agent(db, org, name="Boss")
        parent_v = await _version(
            db,
            parent,
            org,
            number=1,
            publisher_id=author.id,
            subagents=[{"agent_id": str(delegate.id), "agent_version_id": str(unsafe.id)}],
        )
        parent.current_version_id = parent_v.id
        await db.flush()

        findings = await sweep._scan(db)

        assert [f for f in findings if f.agent_slug == delegate.slug] == []


class TestTheSweepClearsAReachableBinding:
    async def test_an_org_visible_skill_is_not_reported(self, db) -> None:
        org, _ = await _org_with_owner(db)
        author = await _user(db)
        colleague = await _user(db)
        await _member(db, org, author, OrgRoleName.MEMBER)
        skill = await _skill(db, org, colleague, visibility=Visibility.ORG)
        agent = await _published_agent(db, org, skill_id=skill.id, publisher_id=author.id)

        findings = await sweep._scan(db)

        assert [f for f in findings if f.agent_slug == agent.slug] == []

    async def test_a_skill_the_publisher_owns_is_not_reported(self, db) -> None:
        org, _ = await _org_with_owner(db)
        author = await _user(db)
        await _member(db, org, author, OrgRoleName.MEMBER)
        skill = await _skill(db, org, author, visibility=Visibility.PRIVATE)
        agent = await _published_agent(db, org, skill_id=skill.id, publisher_id=author.id)

        findings = await sweep._scan(db)

        assert [f for f in findings if f.agent_slug == agent.slug] == []

    async def test_a_disabled_skill_is_not_a_live_exposure(self, db) -> None:
        """`resolve_for_agent` skips a disabled skill, so no run receives it."""
        org, _ = await _org_with_owner(db)
        author = await _user(db)
        colleague = await _user(db)
        await _member(db, org, author, OrgRoleName.MEMBER)
        skill = await _skill(db, org, colleague, visibility=Visibility.PRIVATE)
        skill.enabled = False
        await db.flush()
        agent = await _published_agent(db, org, skill_id=skill.id, publisher_id=author.id)

        findings = await sweep._scan(db)

        assert [f for f in findings if f.agent_slug == agent.slug] == []
