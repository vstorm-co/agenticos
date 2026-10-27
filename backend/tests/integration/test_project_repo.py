"""What the projects tables guarantee that only a database can.

A project is listed to its owner, to everyone when it is the organization's and
to whoever it was shared with; its chat count is everybody's chats in it;
deleting it leaves its chats as ordinary ones and takes its container's row with
it; and a project's container belongs to no agent.
"""

import uuid

import pytest
from sqlalchemy import select

from app.db.models.agent_workspace import AgentWorkspace
from app.db.models.conversation import Conversation
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import agent_workspace as workspace_repo
from app.repositories import conversation_repo, project_repo, sandbox_connection_repo

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
    # A starter's account deleted since: the project was its only way in.
    orphan = await conversation_repo.create_conversation(
        db, organization_id=org.id, user_id=None, title="o", project_id=project.id
    )
    container = await workspace_repo.create(
        db,
        organization_id=org.id,
        agent_id=None,
        project_id=project.id,
        scope="project",
        scope_key=f"dp-{project.id.hex}",
        backend="state",
    )
    found = await workspace_repo.get_for_project(db, organization_id=org.id, project_id=project.id)
    assert found is not None and found.id == container.id and found.agent_id is None
    # Moved to another connection, it leaves a second container; both are listed.
    moved = await workspace_repo.create(
        db,
        organization_id=org.id,
        agent_id=None,
        project_id=project.id,
        scope="project",
        scope_key=f"dp-{uuid.uuid4().hex[:20]}",
        backend="state",
    )
    every = await workspace_repo.list_for_project(db, organization_id=org.id, project_id=project.id)
    assert {row.id for row in every} == {container.id, moved.id}

    assert await project_repo.ownerless_chat_ids(db, project=project) == [orphan.id]
    await project_repo.detach_conversations(db, project=project)
    await project_repo.delete(db, project)
    kept = await db.execute(
        select(Conversation.id, Conversation.project_id).where(Conversation.id == chat.id)
    )
    assert kept.one() == (chat.id, None)
    assert await db.scalar(select(Conversation.id).where(Conversation.id == orphan.id)) is None
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

    # A project's chats reach a reader through the projects they may see - the
    # set the service passes - never through having started one.
    through_project = [project.id]
    listed = await conversation_repo.get_conversations_by_user(
        db,
        alice.id,
        organization_id=org.id,
        project_id=project.id,
        visible_project_ids=through_project,
    )
    assert [conversation.id for conversation in listed] == [inside.id]
    assert (
        await conversation_repo.count_conversations(
            db,
            alice.id,
            organization_id=org.id,
            project_id=project.id,
            visible_project_ids=through_project,
        )
        == 1
    )
    # Started there, but with the project out of reach: not listed at all.
    assert (
        await conversation_repo.get_conversations_by_user(
            db, alice.id, organization_id=org.id, project_id=project.id
        )
        == []
    )


async def test_a_project_chat_works_in_its_projects_container(db) -> None:
    """A run in a project chat keeps its files on the project's container, which
    names no conversation - the chat's files panel finds it through the project."""
    alice = await _user(db)
    org = await _org(db, owner=alice)
    project = await _project(db, org, alice, name="Launch", visibility=Visibility.PRIVATE.value)
    in_project = await conversation_repo.create_conversation(
        db, organization_id=org.id, user_id=alice.id, title="in", project_id=project.id
    )
    plain = await conversation_repo.create_conversation(
        db, organization_id=org.id, user_id=alice.id, title="out"
    )
    container = await workspace_repo.create(
        db,
        organization_id=org.id,
        agent_id=None,
        project_id=project.id,
        scope="project",
        scope_key=f"dp-{project.id.hex}",
        backend="state",
    )

    found = await workspace_repo.kept_for_conversation(
        db, organization_id=org.id, conversation_id=in_project.id
    )
    assert found is not None and found.id == container.id
    assert (
        await workspace_repo.kept_for_conversation(
            db, organization_id=org.id, conversation_id=plain.id
        )
        is None
    )


async def test_the_projects_on_a_connection_are_named_in_order(db) -> None:
    alice = await _user(db)
    org, other = await _org(db, owner=alice), await _org(db, owner=alice)
    host = await sandbox_connection_repo.create(
        db, organization_id=org.id, name="Host", kind="docker", base_url="http://sbx:8080"
    )
    for name in ("Launch", "Audit"):
        await project_repo.create(
            db,
            organization_id=org.id,
            owner_user_id=alice.id,
            name=name,
            description=None,
            instructions="",
            default_agent_id=None,
            backend="service",
            sandbox_connection_id=host.id,
        )
    await _project(db, org, alice, name="Notes", visibility=Visibility.PRIVATE.value)

    assert await project_repo.names_on_connection(
        db, organization_id=org.id, connection_id=host.id
    ) == ["Audit", "Launch"]
    assert (
        await project_repo.names_on_connection(db, organization_id=other.id, connection_id=host.id)
        == []
    )


async def test_the_projects_a_member_may_see_by_id(db) -> None:
    """Their own, the organization's and those shared with them - or every one,
    for somebody who sees them all; and never another organization's."""
    alice, bob = await _user(db), await _user(db)
    org = await _org(db, owner=alice)
    elsewhere = await _org(db, owner=bob)
    mine = await _project(db, org, alice, name="Mine", visibility=Visibility.PRIVATE.value)
    everyones = await _project(db, org, bob, name="All", visibility=Visibility.ORG.value)
    shared = await _project(db, org, bob, name="Shared", visibility=Visibility.PRIVATE.value)
    hidden = await _project(db, org, bob, name="Hidden", visibility=Visibility.PRIVATE.value)
    await _project(db, elsewhere, bob, name="Theirs", visibility=Visibility.ORG.value)

    def visible(*, see_all: bool, shared_ids: list[uuid.UUID]):
        return project_repo.visible_ids(
            db, organization_id=org.id, user_id=alice.id, see_all=see_all, shared_ids=shared_ids
        )

    assert set(await visible(see_all=False, shared_ids=[])) == {mine.id, everyones.id}
    assert set(await visible(see_all=False, shared_ids=[shared.id])) == {
        mine.id,
        everyones.id,
        shared.id,
    }
    assert set(await visible(see_all=True, shared_ids=[])) == {
        mine.id,
        everyones.id,
        shared.id,
        hidden.id,
    }


async def test_a_staged_workspace_cannot_replace_the_selected_generation(db) -> None:
    owner = await _user(db)
    org = await _org(db, owner=owner)
    project = await _project(db, org, owner, name="Wiki", visibility="private")
    generation = uuid.uuid4()
    source = await workspace_repo.create(
        db,
        organization_id=org.id,
        agent_id=None,
        project_id=project.id,
        scope="project",
        scope_key=f"dp-{project.id.hex}",
        backend="state",
    )
    staged = await workspace_repo.create(
        db,
        organization_id=org.id,
        agent_id=None,
        project_id=project.id,
        scope="project",
        scope_key=f"dp-{generation.hex}",
        backend="state",
    )
    assert (
        await workspace_repo.get_for_project(db, organization_id=org.id, project_id=project.id)
    ).id == source.id
    project.workspace_generation = generation
    await db.flush()
    assert (
        await workspace_repo.get_for_project(db, organization_id=org.id, project_id=project.id)
    ).id == staged.id
    assert (
        await workspace_repo.get_for_project(
            db, organization_id=uuid.uuid4(), project_id=project.id
        )
        is None
    )
    assert (
        await project_repo.get(db, project.id, organization_id=org.id, for_update=True) is project
    )


async def test_project_transfer_checks_include_runs_waiting_for_people(db) -> None:
    from app.db.models.agent import Agent
    from app.db.models.agent_run import AgentRun

    owner = await _user(db)
    org = await _org(db, owner=owner)
    project = await _project(db, org, owner, name="Wiki", visibility="private")
    agent = Agent(id=uuid.uuid4(), organization_id=org.id, slug="transfer-test", name="Test")
    conversation = Conversation(
        id=uuid.uuid4(), organization_id=org.id, user_id=owner.id, project_id=project.id
    )
    db.add_all([agent, conversation])
    await db.flush()
    assert not await project_repo.has_active_runs(db, project_id=project.id, organization_id=org.id)
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        status="awaiting_answer",
    )
    db.add(run)
    await db.flush()
    for status in ("running", "awaiting_answer", "awaiting_approval", "completed"):
        run.status = status
        await db.flush()
        assert await project_repo.has_active_runs(
            db, project_id=project.id, organization_id=org.id
        ) == (status != "completed")
    assert not await project_repo.has_active_runs(
        db, project_id=project.id, organization_id=uuid.uuid4()
    )


async def test_source_and_target_connections_are_protected_while_copying(db) -> None:
    from app.repositories import background_job as jobs

    owner = await _user(db)
    org = await _org(db, owner=owner)
    project = await _project(db, org, owner, name="Wiki", visibility="private")
    source, target = uuid.uuid4(), uuid.uuid4()
    job_id = await jobs.add(
        db,
        kind="move-project-workspace",
        pool="ingest",
        payload={"source_connection_id": str(source), "target_connection_id": str(target)},
        max_attempts=3,
        priority=0,
        organization_id=org.id,
    )
    project.workspace_move_job_id = job_id
    await db.flush()
    assert await project_repo.active_moves_for_connection(
        db, connection_id=source, organization_id=org.id
    )
    assert await project_repo.active_moves_for_connection(
        db, connection_id=target, organization_id=org.id
    )
    assert not await project_repo.active_moves_for_connection(
        db, connection_id=target, organization_id=uuid.uuid4()
    )
    assert await jobs.for_project_moves(db, []) == {}
    assert job_id in await jobs.for_project_moves(db, [job_id])
    row = await jobs.get(db, job_id)
    row.status = "dead"
    await db.flush()
    assert not await project_repo.active_moves_for_connection(
        db, connection_id=source, organization_id=org.id
    )


async def test_project_file_users_block_transfer_registration_until_commit(db, engine) -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.core.permissions import AuthContext, Perm
    from app.services.project import ProjectService

    owner = await _user(db)
    org = await _org(db, owner=owner)
    project = await _project(db, org, owner, name="Serialized workspace", visibility="private")
    await db.commit()
    ctx = AuthContext(user_id=owner.id, organization_id=org.id, role="owner")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as files, factory() as transfer:
        # Upload, mkdir and remove all enter with PROJECTS_USE; queuing a
        # transfer enters with PROJECTS_EDIT before checking active runs.
        await ProjectService(files).get(ctx, project.id, perm=Perm.PROJECTS_USE)
        await transfer.execute(text("SET LOCAL lock_timeout = '150ms'"))
        with pytest.raises(DBAPIError) as refused:
            await ProjectService(transfer).get(ctx, project.id, perm=Perm.PROJECTS_EDIT)
        assert getattr(refused.value.orig, "sqlstate", None) == "55P03"
        await transfer.rollback()
        await files.commit()
        assert (
            await ProjectService(transfer).get(ctx, project.id, perm=Perm.PROJECTS_EDIT)
        ).id == project.id
