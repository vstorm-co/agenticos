"""A project's chats against real rows: listed to its members, continued by them, signed by them.

Which rows a `WHERE` lands on, and whether a grant the access resolver reads
really lets a teammate in, are not things a mocked session can say.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.agents.spec import AgentSpec
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import chat_file as chat_file_repo
from app.repositories import conversation_repo, project_repo
from app.schemas.conversation import MessageCreate, MessageRead
from app.schemas.message_rating import MessageRatingCreate
from app.services.conversation import ConversationService
from app.services.file_upload import FileUploadService
from app.services.message_rating import MessageRatingService

pytestmark = pytest.mark.anyio


async def _user(db, name: str | None = None) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
        full_name=name,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db, *members: tuple[User, str]) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=members[0][0].id,
    )
    db.add(org)
    await db.flush()
    for user, role in members:
        db.add(
            OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role=role)
        )
    await db.flush()
    return org


async def _agent(db, org: Organization, owner: User) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        owner_user_id=owner.id,
        name="Analyst",
        slug=f"analyst-{uuid.uuid4().hex[:8]}",
        draft_spec=AgentSpec(name="Analyst").model_dump(mode="json"),
        visibility=Visibility.PRIVATE.value,
    )
    db.add(agent)
    await db.flush()
    return agent


async def _project(db, org: Organization, owner: User, *, visibility: str):
    return await project_repo.create(
        db,
        organization_id=org.id,
        owner_user_id=owner.id,
        name="Launch",
        description=None,
        instructions="",
        default_agent_id=None,
        visibility=visibility,
        backend="service",
    )


class TestATeammateInAnOrganizationsProject:
    async def test_reads_continues_and_signs_a_chat_somebody_else_started(self, db) -> None:
        kacper, anna = await _user(db, "Kacper"), await _user(db, "Anna")
        org = await _org(db, (kacper, "owner"), (anna, "member"))
        project = await _project(db, org, kacper, visibility=Visibility.ORG.value)
        chat = await conversation_repo.create_conversation(
            db, organization_id=org.id, user_id=kacper.id, title="Plan", project_id=project.id
        )
        service = ConversationService(db)

        await service.get_conversation(chat.id, organization_id=org.id, user_id=anna.id)
        await service.add_message(
            chat.id,
            MessageCreate(role="user", content="I'll take the budget part"),
            organization_id=org.id,
            user_id=anna.id,
        )
        items, _, _ = await service.transcript(
            chat.id, organization_id=org.id, user_id=anna.id, include_tool_calls=True
        )

        turn = MessageRead.model_validate(items[-1])
        assert turn.sender is not None and turn.sender.name == "Anna"
        # Continuing is all the project gives: the thread stays Kacper's to rename.
        with pytest.raises(NotFoundError):
            await service.get_conversation(
                chat.id, organization_id=org.id, user_id=anna.id, for_write=True
            )

    async def test_a_private_project_keeps_its_chats_from_the_rest(self, db) -> None:
        kacper, anna = await _user(db), await _user(db)
        org = await _org(db, (kacper, "owner"), (anna, "member"))
        project = await _project(db, org, kacper, visibility=Visibility.PRIVATE.value)
        chat = await conversation_repo.create_conversation(
            db, organization_id=org.id, user_id=kacper.id, title="Plan", project_id=project.id
        )

        with pytest.raises(NotFoundError):
            await ConversationService(db).get_conversation(
                chat.id, organization_id=org.id, user_id=anna.id
            )

    async def test_the_list_holds_everybodys_chats_with_who_saw_and_who_works(self, db) -> None:
        kacper, anna = await _user(db, "Kacper"), await _user(db, "Anna")
        org = await _org(db, (kacper, "owner"), (anna, "member"))
        project = await _project(db, org, kacper, visibility=Visibility.ORG.value)
        mine = await conversation_repo.create_conversation(
            db, organization_id=org.id, user_id=kacper.id, title="Mine", project_id=project.id
        )
        theirs = await conversation_repo.create_conversation(
            db, organization_id=org.id, user_id=anna.id, title="Theirs", project_id=project.id
        )
        await conversation_repo.create_conversation(
            db, organization_id=org.id, user_id=anna.id, title="Elsewhere"
        )
        await conversation_repo.mark_read(db, user_id=anna.id, conversation_id=mine.id)
        agent = await _agent(db, org, kacper)
        db.add(
            AgentRun(
                id=uuid.uuid4(),
                organization_id=org.id,
                agent_id=agent.id,
                conversation_id=theirs.id,
                user_id=anna.id,
                status="running",
                started_at=datetime.now(UTC) - timedelta(seconds=5),
            )
        )
        await db.flush()

        items, total = await ConversationService(db).list_project_chats(
            project.id, organization_id=org.id, user_id=kacper.id
        )

        by_title = {item.title: item for item in items}
        assert total == 2 and set(by_title) == {"Mine", "Theirs"}
        assert by_title["Mine"].owner.name == "Kacper"
        assert [reader.name for reader in by_title["Mine"].seen_by] == ["Anna"]
        assert by_title["Theirs"].working.name == "Anna"
        assert by_title["Mine"].working is None


class TestAContinuedChatInTheTeammatesOwnList:
    async def test_listed_while_the_project_is_theirs_and_gone_when_it_is_not(self, db) -> None:
        kacper, anna = await _user(db, "Kacper"), await _user(db, "Anna")
        org = await _org(db, (kacper, "owner"), (anna, "member"))
        project = await _project(db, org, kacper, visibility=Visibility.ORG.value)
        chat = await conversation_repo.create_conversation(
            db, organization_id=org.id, user_id=kacper.id, title="Plan", project_id=project.id
        )
        read_only = await conversation_repo.create_conversation(
            db, organization_id=org.id, user_id=kacper.id, title="Only read", project_id=project.id
        )
        service = ConversationService(db)
        await service.add_message(
            chat.id,
            MessageCreate(role="user", content="on it"),
            organization_id=org.id,
            user_id=anna.id,
        )

        listed, total = await service.list_conversations(user_id=anna.id, organization_id=org.id)
        assert [c.id for c in listed] == [chat.id] and total == 1
        assert read_only.id not in {c.id for c in listed}

        # The project goes private: typing in it once is not access (#641).
        project.visibility = Visibility.PRIVATE.value
        await db.flush()
        listed, total = await service.list_conversations(user_id=anna.id, organization_id=org.id)
        assert (listed, total) == ([], 0)

    async def test_a_former_member_lists_nothing_of_it(self, db) -> None:
        kacper, anna = await _user(db), await _user(db)
        org = await _org(db, (kacper, "owner"), (anna, "member"))
        project = await _project(db, org, kacper, visibility=Visibility.ORG.value)
        chat = await conversation_repo.create_conversation(
            db, organization_id=org.id, user_id=kacper.id, title="Plan", project_id=project.id
        )
        await conversation_repo.create_message(
            db, conversation_id=chat.id, role="user", content="hi", author_user_id=anna.id
        )
        service = ConversationService(db)
        assert await service._project_threads(anna.id, org.id) == {chat.id}

        await db.execute(
            delete(OrganizationMember).where(
                OrganizationMember.organization_id == org.id,
                OrganizationMember.user_id == anna.id,
            )
        )
        assert await service._project_threads(anna.id, org.id) == set()


class TestRatingATeammatesAnswer:
    async def test_whoever_reads_the_chat_rates_its_answers_and_nobody_else(self, db) -> None:
        kacper, anna, stranger = await _user(db), await _user(db), await _user(db)
        org = await _org(db, (kacper, "owner"), (anna, "member"), (stranger, "member"))
        shared = await _project(db, org, kacper, visibility=Visibility.ORG.value)
        chat = await conversation_repo.create_conversation(
            db, organization_id=org.id, user_id=kacper.id, title="Plan", project_id=shared.id
        )
        answer = await conversation_repo.create_message(
            db, conversation_id=chat.id, role="assistant", content="Here is the plan"
        )
        ratings = MessageRatingService(db)

        rating, is_new = await ratings.rate_message(
            chat.id, answer.id, anna.id, org.id, MessageRatingCreate(rating=1)
        )
        assert is_new and rating.rating == 1
        await ratings.remove_rating(chat.id, answer.id, anna.id, org.id)

        shared.visibility = Visibility.PRIVATE.value
        await db.flush()
        with pytest.raises(NotFoundError):
            await ratings.rate_message(
                chat.id, answer.id, stranger.id, org.id, MessageRatingCreate(rating=1)
            )


class TestOpeningATeammatesAttachment:
    async def test_an_attachment_opens_for_whoever_reads_its_chat(self, db) -> None:
        kacper, anna, stranger = await _user(db), await _user(db), await _user(db)
        org = await _org(db, (kacper, "owner"), (anna, "member"), (stranger, "member"))
        project = await _project(db, org, kacper, visibility=Visibility.ORG.value)
        chat = await conversation_repo.create_conversation(
            db, organization_id=org.id, user_id=kacper.id, title="Plan", project_id=project.id
        )
        turn = await conversation_repo.create_message(
            db, conversation_id=chat.id, role="user", content="see attached"
        )

        async def upload(name: str):
            return await chat_file_repo.create(
                db,
                user_id=kacper.id,
                filename=name,
                mime_type="text/csv",
                size=3,
                storage_path=f"{uuid.uuid4().hex}/{name}",
                file_type="csv",
            )

        attached, unsent = await upload("budget.csv"), await upload("draft.csv")
        await chat_file_repo.link_to_message(
            db, message_id=turn.id, file_ids=[attached.id], user_id=kacper.id
        )
        # A bulk UPDATE: the row this session already holds is read again, as a
        # request's fresh session would.
        await db.refresh(attached)
        files = FileUploadService(db)

        own = await files.get_readable_file(unsent.id, user_id=kacper.id)
        assert own.id == unsent.id
        seen = await files.get_readable_file(attached.id, user_id=anna.id)
        assert seen.id == attached.id
        # Not sent anywhere yet: still the uploader's alone.
        with pytest.raises(NotFoundError):
            await files.get_readable_file(unsent.id, user_id=anna.id)
        with pytest.raises(NotFoundError):
            await files.get_readable_file(uuid.uuid4(), user_id=anna.id)

        project.visibility = Visibility.PRIVATE.value
        await db.flush()
        with pytest.raises(NotFoundError):
            await files.get_readable_file(attached.id, user_id=stranger.id)


class TestThePeopleQueries:
    async def test_readers_come_newest_first_and_nobody_is_asked_for_nothing(self, db) -> None:
        kacper, anna = await _user(db), await _user(db)
        org = await _org(db, (kacper, "owner"), (anna, "member"))
        chat = await conversation_repo.create_conversation(
            db, organization_id=org.id, user_id=kacper.id, title="t"
        )
        await conversation_repo.mark_read(db, user_id=kacper.id, conversation_id=chat.id)
        await conversation_repo.mark_read(db, user_id=anna.id, conversation_id=chat.id)

        readers = await conversation_repo.readers_of(db, [chat.id])

        assert {user.id for user, _ in readers[chat.id]} == {kacper.id, anna.id}
        times = [read_at for _, read_at in readers[chat.id]]
        assert times == sorted(times, reverse=True)
        assert await conversation_repo.readers_of(db, []) == {}
        assert await conversation_repo.users_by_id(db, []) == {}
        assert await conversation_repo.running_users(db, []) == {}

    async def test_the_person_working_is_the_one_whose_run_began_first(self, db) -> None:
        kacper, anna = await _user(db), await _user(db)
        org = await _org(db, (kacper, "owner"), (anna, "member"))
        agent = await _agent(db, org, kacper)
        chat = await conversation_repo.create_conversation(
            db, organization_id=org.id, user_id=kacper.id, title="t"
        )
        now = datetime.now(UTC)
        for user, ago, status in (
            (anna, 30, "running"),
            (kacper, 10, "running"),
            (kacper, 60, "completed"),
            (None, 90, "running"),
        ):
            db.add(
                AgentRun(
                    id=uuid.uuid4(),
                    organization_id=org.id,
                    agent_id=agent.id,
                    conversation_id=chat.id,
                    user_id=user.id if user else None,
                    status=status,
                    started_at=now - timedelta(seconds=ago),
                )
            )
        await db.flush()

        assert await conversation_repo.running_users(db, [chat.id]) == {chat.id: anna.id}


async def test_an_api_context_reads_a_project_chat_through_its_own_grants(db) -> None:
    """A caller's own `ctx` is used as it stands, not rebuilt from membership."""
    kacper = await _user(db)
    org = await _org(db, (kacper, "owner"))
    project = await _project(db, org, kacper, visibility=Visibility.PRIVATE.value)
    chat = await conversation_repo.create_conversation(
        db, organization_id=org.id, user_id=kacper.id, title="Plan", project_id=project.id
    )
    stranger = await _user(db)
    ctx = AuthContext(user_id=stranger.id, organization_id=org.id, role="viewer")

    with pytest.raises(NotFoundError):
        await ConversationService(db).get_conversation(
            chat.id, organization_id=org.id, user_id=stranger.id, ctx=ctx
        )
