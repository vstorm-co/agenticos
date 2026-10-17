"""What the projects tables guarantee that only a database can.

A project is listed to its owner, to everyone when it is the organization's and
to whoever it was shared with; its chat count is everybody's chats in it;
deleting it leaves its chats as ordinary ones and takes its container's row with
it; and a project's container belongs to no agent.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.models.agent_workspace import AgentWorkspace
from app.db.models.conversation import Conversation
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import agent_workspace as workspace_repo
from app.repositories import conversation_repo, project_repo

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


async def _org(db, *, owner: User) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=owner.id, role="owner")
    )
    await db.flush()
    return org


async def _project(db, org: Organization, owner: User, *, name: str, visibility: str):
    return await project_repo.create(
        db,
        organization_id=org.id,
        owner_user_id=owner.id,
        name=name,
        description=f"{name} work",
        instructions="",
        default_agent_id=None,
        backend="state",
        visibility=visibility,
    )


async def test_a_reader_sees_their_own_the_organizations_and_what_was_shared(db) -> None:
    alice, bob = await _user(db), await _user(db)
    org = await _org(db, owner=alice)
    mine = await _project(db, org, alice, name="Launch", visibility=Visibility.PRIVATE.value)
    everyones = await _project(db, org, bob, name="Handbook", visibility=Visibility.ORG.value)
    shared = await _project(db, org, bob, name="Audit", visibility=Visibility.PRIVATE.value)
    hidden = await _project(db, org, bob, name="Secret", visibility=Visibility.PRIVATE.value)

    seen, total = await project_repo.list_visible(
        db, organization_id=org.id, user_id=alice.id, see_all=False, shared_ids=[shared.id]
    )
    assert {project.id for project in seen} == {mine.id, everyones.id, shared.id}
    assert total == 3

    everything, _ = await project_repo.list_visible(
        db, organization_id=org.id, user_id=alice.id, see_all=True, shared_ids=[]
    )
    assert hidden.id in {project.id for project in everything}

    found, _ = await project_repo.list_visible(
        db,
        organization_id=org.id,
        user_id=alice.id,
        see_all=True,
        shared_ids=[],
        search="aud",
        only_ids=[shared.id, mine.id],
    )
    assert [project.id for project in found] == [shared.id]
    assert await project_repo.get(db, mine.id, organization_id=uuid.uuid4()) is None


async def test_the_chat_count_is_everybodys_and_leaves_archived_out(db) -> None:
    alice, bob = await _user(db), await _user(db)
    org = await _org(db, owner=alice)
    project = await _project(db, org, alice, name="Launch", visibility=Visibility.ORG.value)
    for user, archived in ((alice, False), (alice, False), (alice, True), (bob, False)):
        conversation = await conversation_repo.create_conversation(
            db, organization_id=org.id, user_id=user.id, title="t", project_id=project.id
        )
        conversation.is_archived = archived
    await db.flush()

    activity = await project_repo.chat_activity(
        db, organization_id=org.id, project_ids=[project.id]
    )
    count, last = activity[project.id]
    assert count == 3 and last is not None
    assert await project_repo.chat_activity(db, organization_id=org.id, project_ids=[]) == {}


async def test_deleting_a_project_keeps_its_chats_and_takes_its_container(db) -> None:
    alice = await _user(db)
    org = await _org(db, owner=alice)
    project = await _project(db, org, alice, name="Launch", visibility=Visibility.PRIVATE.value)
    renamed = await project_repo.update(
        db, project=project, update_data={"name": "Launch v2", "instructions": "Be brief."}
    )
    assert renamed.name == "Launch v2"
    chat = await conversation_repo.create_conversation(
        db, organization_id=org.id, user_id=alice.id, title="t", project_id=project.id
    )
    container = await workspace_repo.create(
        db,
        organization_id=org.id,
        agent_id=None,
        project_id=project.id,
        scope="project",
        scope_key=f"dp-{uuid.uuid4().hex[:20]}",
        backend="state",
    )
    found = await workspace_repo.get_for_project(db, organization_id=org.id, project_id=project.id)
    assert found is not None and found.id == container.id and found.agent_id is None

    await project_repo.detach_conversations(db, project=project)
    await project_repo.delete(db, project)
    kept = await db.execute(
        select(Conversation.id, Conversation.project_id).where(Conversation.id == chat.id)
    )
    assert kept.one() == (chat.id, None)
    left = await db.scalar(select(AgentWorkspace.id).where(AgentWorkspace.id == container.id))
    assert left is None


async def test_a_projects_chat_list_holds_only_the_chats_started_in_it(db) -> None:
    alice = await _user(db)
    org = await _org(db, owner=alice)
    project = await _project(db, org, alice, name="Launch", visibility=Visibility.PRIVATE.value)
    inside = await conversation_repo.create_conversation(
        db, organization_id=org.id, user_id=alice.id, title="in", project_id=project.id
    )
    await conversation_repo.create_conversation(
        db, organization_id=org.id, user_id=alice.id, title="out"
    )

    listed = await conversation_repo.get_conversations_by_user(
        db, alice.id, organization_id=org.id, project_id=project.id
    )
    assert [conversation.id for conversation in listed] == [inside.id]
    assert (
        await conversation_repo.count_conversations(
            db, alice.id, organization_id=org.id, project_id=project.id
        )
        == 1
    )
