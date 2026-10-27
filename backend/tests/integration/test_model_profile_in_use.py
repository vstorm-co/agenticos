"""Which agents still run on a model profile, asked of Postgres (#2478).

The question is a text match on JSONB joined across agents, their served version
and the versions environments pin - exactly what a mocked session cannot answer.
Each case is one place a profile id can live, and one that must not count.
"""

import uuid

import pytest
from sqlalchemy import select

from app.core.exceptions import AlreadyExistsError, InUseError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentStatus, AgentVersion
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.credential import ModelProfile
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import agent_repo, credential_repo
from app.schemas.model_profile import ModelProfileUpdate
from app.services.model_profile import ModelProfileService

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
