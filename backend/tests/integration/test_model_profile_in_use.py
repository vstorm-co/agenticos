"""Which agents still run on a model profile, asked of Postgres (#2478).

The question is a text match on JSONB joined across agents, their served version
and the versions environments pin - exactly what a mocked session cannot answer.
Each case is one place a profile id can live, and one that must not count.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.exceptions import AlreadyExistsError, BadRequestError, InUseError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentStatus, AgentVersion
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.credential import ModelProfile
from app.db.models.organization import Organization
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.user import User
from app.repositories import agent_repo, credential_repo
from app.schemas.model_profile import ModelProfileRead, ModelProfileUpdate
from app.services.model_profile import ModelProfileService
from tests.integration._keys import provider_key

pytestmark = pytest.mark.anyio


async def _org(db) -> tuple[Organization, User]:
    owner = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(owner)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(org)
    await db.flush()
    return org, owner


async def _profile(db, org: Organization, label: str = "Ollama · llama4") -> ModelProfile:
    profile = ModelProfile(
        organization_id=org.id,
        label=label,
        provider="ollama",
        model="llama4",
        secret_id=None,
        base_url="http://ollama:11434/v1",
    )
    db.add(profile)
    await db.flush()
    return profile


async def _agent(
    db,
    org: Organization,
    name: str,
    *,
    draft: dict | None = None,
    status: AgentStatus = AgentStatus.PUBLISHED,
) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=f"agent-{uuid.uuid4().hex[:6]}",
        name=name,
        draft_spec=draft or {"name": name},
        status=status.value,
    )
    db.add(agent)
    await db.flush()
    return agent


async def _version(db, agent: Agent, number: int, spec: dict) -> AgentVersion:
    version = AgentVersion(
        id=uuid.uuid4(),
        agent_id=agent.id,
        organization_id=agent.organization_id,
        version=number,
        spec={"name": agent.name, **spec},
    )
    db.add(version)
    await db.flush()
    return version


async def test_every_place_a_profile_is_named_counts_and_history_does_not(db):
    org, _ = await _org(db)
    other_org, _ = await _org(db)
    profile = await _profile(db, org)
    pid = str(profile.id)

    on_draft = await _agent(db, org, "Draft only", draft={"model_profile_id": pid})

    served = await _agent(db, org, "Reviewer on it")
    current = await _version(
        db, served, 1, {"reviewers": [{"name": "check", "model_profile_id": pid}]}
    )
    served.current_version_id = current.id

    pinned = await _agent(db, org, "Pinned in staging")
    old = await _version(
        db,
        pinned,
        1,
        {"capabilities": [{"id": "follow_ups", "config": {"model_profile_id": pid}}]},
    )
    newer = await _version(db, pinned, 2, {"model_profile_id": str(uuid.uuid4())})
    pinned.current_version_id = newer.id
    db.add(
        AgentEnvironment(
            id=uuid.uuid4(),
            organization_id=org.id,
            agent_id=pinned.id,
            name="staging",
            version_id=old.id,
        )
    )

    # History: the version that named it is neither served nor pinned.
    moved_on = await _agent(db, org, "Moved on")
    await _version(db, moved_on, 1, {"model_profile_id": pid})
    moved_on.current_version_id = (await _version(db, moved_on, 2, {})).id

    # Archived still counts: unarchiving restores the version it served.
    archived = await _agent(
        db, org, "Archived", draft={"model_profile_id": pid}, status=AgentStatus.ARCHIVED
    )
    # Another tenant's agent naming the same id is not this organization's business.
    await _agent(db, other_org, "Elsewhere", draft={"model_profile_id": pid})
    await db.flush()

    users = await agent_repo.naming_model_profile(db, organization_id=org.id, profile_id=profile.id)

    assert [agent.id for agent in users] == [archived.id, on_draft.id, pinned.id, served.id]


async def test_deleting_a_profile_an_agent_runs_on_is_refused_and_keeps_it(db):
    org, owner = await _org(db)
    profile = await _profile(db, org)
    await _agent(db, org, "Helpdesk", draft={"model_profile_id": str(profile.id)})
    ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)

    with pytest.raises(InUseError) as refused:
        await ModelProfileService(db).delete_profile(ctx, profile.id)

    assert "Helpdesk" in refused.value.message
    assert (await db.execute(select(ModelProfile.id))).scalars().all() == [profile.id]


async def test_an_unused_profile_is_deleted(db):
    org, owner = await _org(db)
    profile = await _profile(db, org)
    await _agent(db, org, "Elsewhere", draft={"model_profile_id": str(uuid.uuid4())})
    ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)

    await ModelProfileService(db).delete_profile(ctx, profile.id)

    assert (await db.execute(select(ModelProfile.id))).scalars().all() == []


async def test_an_edit_keeps_the_id_and_a_taken_label_is_refused(db):
    org, owner = await _org(db)
    profile = await _profile(db, org)
    await _profile(db, org, label="Taken")
    ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)
    service = ModelProfileService(db)

    updated = await service.update_profile(
        ctx, profile.id, ModelProfileUpdate(base_url="http://gpu-box:11434/v1")
    )

    assert updated.id == profile.id
    assert updated.base_url == "http://gpu-box:11434/v1"
    with pytest.raises(AlreadyExistsError):
        await service.update_profile(ctx, profile.id, ModelProfileUpdate(label="Taken"))


async def test_the_repository_writes_nothing_for_another_organization(db):
    org, _ = await _org(db)
    other, _ = await _org(db)
    profile = await _profile(db, org)

    await credential_repo.update_profile(
        db, organization_id=other.id, profile=profile, update_data={"label": "Hijacked"}
    )

    assert profile.label == "Ollama · llama4"


async def test_an_id_quoted_in_instructions_is_not_a_reference(db):
    """A whole JSON value counts; the same characters inside a longer string do not."""
    org, _ = await _org(db)
    profile = await _profile(db, org)
    await _agent(
        db,
        org,
        "Talks about it",
        draft={"instructions": f"Never switch to model {profile.id}, it is slow."},
    )
    named = await _agent(db, org, "Runs on it", draft={"specialists": [{"x": [str(profile.id)]}]})
    await db.flush()

    users = await agent_repo.naming_model_profile(db, organization_id=org.id, profile_id=profile.id)

    assert [agent.id for agent in users] == [named.id]


async def test_a_delete_waits_for_a_draft_save_in_flight_and_then_sees_it(engine: AsyncEngine):
    """The in-use check and the delete are one step to a concurrent spec write.

    A draft save naming the profile holds the shared side of the lock until it
    commits; the delete takes the exclusive side first, so it waits, and its
    check then reads the committed draft and refuses (#2478).
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as setup:
        org, owner = await _org(setup)
        profile = await _profile(setup, org)
        agent = await _agent(setup, org, "Helpdesk", draft={"name": "Helpdesk"})
        await setup.commit()
    ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)

    async with factory() as saving, factory() as deleting:
        row = await saving.get(Agent, agent.id)
        assert row is not None
        await agent_repo.update(
            saving, agent=row, update_data={"draft_spec": {"model_profile_id": str(profile.id)}}
        )
        delete = asyncio.create_task(ModelProfileService(deleting).delete_profile(ctx, profile.id))
        await asyncio.sleep(0.3)
        # Still waiting on the uncommitted draft save.
        assert not delete.done()

        await saving.commit()
        with pytest.raises(InUseError):
            await asyncio.wait_for(delete, timeout=10)
        await deleting.rollback()

    async with factory() as check:
        assert (await check.execute(select(ModelProfile.id))).scalars().all() == [profile.id]


async def test_a_profile_saved_with_a_key_reads_as_keyless_once_the_key_is_gone(db):
    """A gateway profile that had a key keeps its endpoint when the key is
    deleted; the stored intent is what says it is now missing one."""
    org, owner = await _org(db)
    secret_id = await provider_key(db, org.id)
    ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)
    service = ModelProfileService(db)
    with_key = await credential_repo.create_profile(
        db,
        organization_id=org.id,
        label="Gateway",
        provider="openai",
        model="gpt-5",
        secret_id=secret_id,
        base_url="http://gw.example/v1",
        runs_without_key=False,
    )
    keyless = await service.update_profile(
        ctx,
        (
            await credential_repo.create_profile(
                db,
                organization_id=org.id,
                label="vLLM",
                provider="openai",
                model="llama",
                secret_id=secret_id,
                base_url="http://vllm:8000/v1",
            )
        ).id,
        ModelProfileUpdate(secret_id=None),
    )
    await db.execute(delete(OrganizationSecret).where(OrganizationSecret.id == secret_id))
    await db.flush()
    await db.refresh(with_key)

    assert with_key.secret_id is None
    assert ModelProfileRead.model_validate(with_key).missing_key is True
    assert ModelProfileRead.model_validate(keyless).missing_key is False


async def test_two_edits_cannot_each_take_half_of_what_a_profile_needs(engine: AsyncEngine):
    """One edit drops the key of a gateway profile, the other its endpoint. Each is
    allowed on its own; together they leave a profile that cannot run. The second
    waits for the first and validates what it committed (#2478)."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as setup:
        org, owner = await _org(setup)
        secret_id = await provider_key(setup, org.id)
        profile = await credential_repo.create_profile(
            setup,
            organization_id=org.id,
            label="Gateway",
            provider="openai",
            model="gpt-5",
            secret_id=secret_id,
            base_url="http://gw.example/v1",
        )
        await setup.commit()
    ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)

    async with factory() as first, factory() as second:
        await ModelProfileService(first).update_profile(
            ctx, profile.id, ModelProfileUpdate(secret_id=None)
        )
        racing = asyncio.create_task(
            ModelProfileService(second).update_profile(
                ctx, profile.id, ModelProfileUpdate(base_url=None)
            )
        )
        await asyncio.sleep(0.3)
        assert not racing.done()

        await first.commit()
        with pytest.raises(BadRequestError):
            await asyncio.wait_for(racing, timeout=10)
        await second.rollback()
