"""A later turn puts back an attachment its own turn stopped before writing (#2481).

The file is linked to the message it arrived with before the run starts, so a
turn that failed before the file reached the workspace left a file nobody would
ever write and nobody could attach again. The next turn of the same agent now
asks for the person's files on its interrupted turns and writes back the ones
its workspace lacks.

Against a real database because what may be written is decided by a WHERE
clause: the thread, its organization, the agent, the run's ending and the
file's owner. A file of another conversation, person, organization or agent
must never land in this run's workspace, and a file a finished turn left
behind is not put back.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import BadRequestError
from app.db.models.agent import Agent
from app.db.models.agent_run import (
    AgentRun,
    ApprovalDecidedVia,
    ApprovalStatus,
    RunStatus,
    ToolApproval,
)
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import chat_file as chat_file_repo
from app.services import attachments as attachments_module
from app.services.attachments import (
    AttachmentRouter,
    find_earlier_attachments,
    restore_earlier_attachments,
    workspace_path,
)
from app.services.conversation import ConversationService
from tests.workspaces import ShellFailing, document_workspace

pytestmark = [pytest.mark.anyio, pytest.mark.security]

CSV = b"month,total\njan,10\n"
_START = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)


async def _member(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _organization(db) -> Organization:
    founder = await _member(db)
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization


async def _agent(db, organization: Organization) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=organization.id,
        slug=f"clerk-{uuid.uuid4().hex[:8]}",
        name="Clerk",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    return agent


async def _conversation(db, owner: User, organization: Organization) -> Conversation:
    conversation = Conversation(
        id=uuid.uuid4(), user_id=owner.id, organization_id=organization.id, title="Numbers"
    )
    db.add(conversation)
    await db.flush()
    return conversation


class _Thread:
    """One conversation, its runs stamped a minute apart so their order is not `now()`'s."""

    def __init__(self, db, conversation: Conversation) -> None:
        self.db = db
        self.conversation = conversation
        self.turns = 0

    async def turn(
        self,
        author: User,
        agent: Agent,
        status: RunStatus,
        *,
        ended_after: int = 0,
        key_scopes: list[str] | None = None,
        publisher_fallback: bool = False,
    ) -> Message:
        """A prompt and the run that answered it, linked the way the chat links them.

        `ended_after` is how many minutes the run went on for, so a later turn can
        start before it ended. `key_scopes` makes it a key's run, and
        `publisher_fallback` the publisher's standing in for a visitor.
        """
        self.turns += 1
        started = _START + timedelta(minutes=self.turns)
        run = AgentRun(
            id=uuid.uuid4(),
            organization_id=self.conversation.organization_id,
            agent_id=agent.id,
            user_id=author.id,
            conversation_id=self.conversation.id,
            status=status.value,
            created_at=started,
            ended_at=started + timedelta(minutes=ended_after, seconds=30),
            key_scopes=key_scopes,
            initiated_by_publisher_fallback=publisher_fallback,
        )
        run.earlier_attachments_checked = True
        self.db.add(run)
        await self.db.flush()
        message = Message(
            id=uuid.uuid4(),
            conversation_id=self.conversation.id,
            role="user",
            content="here",
            author_user_id=author.id,
            run_id=run.id,
        )
        self.db.add(message)
        await self.db.flush()
        return message


async def _attached(db, owner: User, message: Message, *, filename: str = "report.csv") -> ChatFile:
    """An upload linked to a turn, the way `persist_user_turn` links one before the run."""
    chat_file = ChatFile(
        id=uuid.uuid4(),
        user_id=owner.id,
        filename=filename,
        mime_type="text/csv",
        size=len(CSV),
        storage_path=f"uploads/{uuid.uuid4().hex}.csv",
        file_type="text",
        parsed_content=CSV.decode(),
    )
    db.add(chat_file)
    await db.flush()
    await ConversationService(db).link_files_to_message(
        message.id, [str(chat_file.id)], user_id=owner.id
    )
    return chat_file


async def _left(db, thread: _Thread, person: User, agent: Agent, **overrides) -> list[str]:
    """The filenames both reads answer, checked to agree with each other."""
    scope = {
        "conversation_id": thread.conversation.id,
        "organization_id": thread.conversation.organization_id,
        "user_id": person.id,
        "agent_id": agent.id,
        **overrides,
    }
    found = await chat_file_repo.left_by_interrupted_turns(
        db, limit=50, opening_chars=attachments_module._OPENING_CHARS, **scope
    )
    rows = await chat_file_repo.get_many_left_by_interrupted_turns(
        db, [file.id for file in found], **scope
    )
    assert sorted(row.id for row in rows) == sorted(file.id for file in found)
    return [file.filename for file in found]


async def _released(db, message: Message, *, by: User | None) -> None:
    """A click on an approval the turn's run parked on - `None` for an expiry."""
    run = await db.get(AgentRun, message.run_id)
    db.add(
        ToolApproval(
            organization_id=run.organization_id,
            run_id=run.id,
            agent_id=run.agent_id,
            tool_id="send_email",
            status=ApprovalStatus.APPROVED.value if by else ApprovalStatus.EXPIRED.value,
            decided_by_user_id=by.id if by else None,
            decided_via=ApprovalDecidedVia.CLICK.value,
        )
    )
    await db.flush()


@pytest.fixture
def same_session(monkeypatch, db):
    """The restore's own session, pointed at the test's: its rows are not committed."""

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(attachments_module, "get_db_context", session)


@pytest.fixture
def storage(monkeypatch):
    monkeypatch.setattr(
        attachments_module,
        "get_file_storage",
        lambda: SimpleNamespace(load=AsyncMock(return_value=CSV)),
    )


@pytest.fixture
async def world(db):
    person = await _member(db)
    organization = await _organization(db)
    agent = await _agent(db, organization)
    thread = _Thread(db, await _conversation(db, person, organization))
    return SimpleNamespace(person=person, organization=organization, agent=agent, thread=thread)


class TestTheTurnAfterAFailedOne:
    async def test_the_file_is_in_the_workspace_without_a_new_upload(
        self, db, world, same_session, storage
    ) -> None:
        """The issue's sequence, end to end below the socket."""
        first = await world.thread.turn(world.person, world.agent, RunStatus.FAILED)
        report = await _attached(db, world.person, first)

        # The first turn's workspace would not take the write, and the run failed.
        prompt = await AttachmentRouter(ShellFailing(document_workspace())).build_prompt(
            "summarise", [report]
        )
        assert "could not be written" in prompt

        # Attaching it again is refused, as designed: one file, one message (#706).
        with pytest.raises(BadRequestError) as refused:
            await ConversationService(db).list_attached_files(
                [str(report.id)], user_id=world.person.id
            )
        assert refused.value.details["already_attached"] == [str(report.id)]

        # The second turn of the same agent, on a workspace that works.
        workspace = document_workspace()
        earlier = await find_earlier_attachments(
            db,
            conversation_id=world.thread.conversation.id,
            organization_id=world.organization.id,
            user_id=world.person.id,
            agent_id=world.agent.id,
            can_parse=False,
            screen=None,
        )
        assert earlier is not None
        await restore_earlier_attachments(workspace, earlier, can_parse=False)

        assert await workspace.read_bytes(workspace_path(report)) == CSV


class TestWhatATurnMayPutBack:
    async def test_only_interrupted_turns_since_the_agents_last_completed_one(
        self, db, world
    ) -> None:
        """A finished turn had its chance to put a lost file back, so a file somebody
        deleted after it stays deleted; a parked or running turn has not stopped."""
        before = await world.thread.turn(world.person, world.agent, RunStatus.FAILED)
        await _attached(db, world.person, before, filename="before.csv")
        done = await world.thread.turn(world.person, world.agent, RunStatus.COMPLETED)
        await _attached(db, world.person, done, filename="completed.csv")
        for status in (
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.BUDGET_EXCEEDED,
            RunStatus.GUARDRAIL_BLOCKED,
            RunStatus.LOOP_STOPPED,
            RunStatus.AWAITING_APPROVAL,
            RunStatus.AWAITING_ANSWER,
            RunStatus.RUNNING,
        ):
            message = await world.thread.turn(world.person, world.agent, status)
            await _attached(db, world.person, message, filename=f"{status.value}.csv")

        assert sorted(await _left(db, world.thread, world.person, world.agent)) == [
            "budget_exceeded.csv",
            "cancelled.csv",
            "failed.csv",
            "loop_stopped.csv",
        ]

    async def test_a_turn_a_guardrail_blocked_leaves_its_file_where_it_was(self, db, world) -> None:
        """The input edge screened the file's opening lines with the prompt and
        refused the turn: writing the file into the next turn's workspace would hand
        the model what the policy turned away."""
        blocked = await world.thread.turn(world.person, world.agent, RunStatus.GUARDRAIL_BLOCKED)
        await _attached(db, world.person, blocked)

        assert await _left(db, world.thread, world.person, world.agent) == []
        assert (
            await find_earlier_attachments(
                db,
                conversation_id=world.thread.conversation.id,
                organization_id=world.organization.id,
                user_id=world.person.id,
                agent_id=world.agent.id,
                can_parse=False,
                screen=None,
            )
            is None
        )

    @pytest.mark.security
    async def test_a_completed_turn_without_a_workspace_does_not_close_the_window(
        self, db, world
    ) -> None:
        failed = await world.thread.turn(world.person, world.agent, RunStatus.FAILED)
        await _attached(db, world.person, failed)
        done = await world.thread.turn(world.person, world.agent, RunStatus.COMPLETED)
        closing = await db.get(AgentRun, done.run_id)
        closing.earlier_attachments_checked = False
        await db.flush()
        assert await _left(db, world.thread, world.person, world.agent) == ["report.csv"]

    async def test_a_completed_turn_that_looked_for_the_files_closes_the_window(
        self, db, world
    ) -> None:
        """A session's run, released by its own person's click, put them back."""
        failed = await world.thread.turn(world.person, world.agent, RunStatus.FAILED)
        await _attached(db, world.person, failed)
        done = await world.thread.turn(world.person, world.agent, RunStatus.COMPLETED)
        await _released(db, done, by=world.person)

        assert await _left(db, world.thread, world.person, world.agent) == []

    @pytest.mark.parametrize(
        "closing",
        ["api-key", "publisher-for-a-visitor", "released-by-another", "expired"],
    )
    async def test_a_completed_turn_that_never_looked_closes_nothing(
        self, db, world, closing: str
    ) -> None:
        """`AgentRunnerService._assemble` skips the look for a key's run, a publisher
        standing in for a visitor and a resume by another approver - so that run
        finishing is not this person's chance gone."""
        failed = await world.thread.turn(world.person, world.agent, RunStatus.FAILED)
        await _attached(db, world.person, failed)
        done = await world.thread.turn(
            world.person,
            world.agent,
            RunStatus.COMPLETED,
            key_scopes=["agents:run"] if closing == "api-key" else None,
            publisher_fallback=closing == "publisher-for-a-visitor",
        )
        if closing == "released-by-another":
            await _released(db, done, by=await _member(db))
        if closing == "expired":
            await _released(db, done, by=None)

        assert await _left(db, world.thread, world.person, world.agent) == ["report.csv"]

    async def test_another_agents_turn_is_not_this_agents_to_put_back(self, db, world) -> None:
        """Its workspace may be one everybody who runs this agent shares."""
        other = await _agent(db, world.organization)
        message = await world.thread.turn(world.person, other, RunStatus.FAILED)
        await _attached(db, world.person, message)

        assert await _left(db, world.thread, world.person, world.agent) == []
        assert await _left(db, world.thread, world.person, other) == ["report.csv"]

    async def test_another_persons_finished_turn_closes_nothing(self, db, world) -> None:
        """It never put this person's files back, so it is not their chance gone."""
        colleague = await _member(db)
        failed = await world.thread.turn(world.person, world.agent, RunStatus.FAILED)
        await _attached(db, world.person, failed)
        await world.thread.turn(colleague, world.agent, RunStatus.COMPLETED)

        assert await _left(db, world.thread, world.person, world.agent) == ["report.csv"]

    async def test_a_turn_already_running_when_this_one_stopped_closes_nothing(
        self, db, world
    ) -> None:
        """It looked for interrupted turns while this one was still running."""
        failed = await world.thread.turn(
            world.person, world.agent, RunStatus.FAILED, ended_after=10
        )
        await _attached(db, world.person, failed)
        await world.thread.turn(world.person, world.agent, RunStatus.COMPLETED)

        assert await _left(db, world.thread, world.person, world.agent) == ["report.csv"]

    async def test_an_id_from_elsewhere_is_not_read_by_id(self, db, world) -> None:
        """The second read repeats every condition rather than trusting the ids it is
        handed - a file of another agent, person or organization stays out."""
        stranger = await _member(db)
        other_org = await _organization(db)
        their_thread = _Thread(db, await _conversation(db, stranger, other_org))
        theirs = await _attached(
            db,
            stranger,
            await their_thread.turn(stranger, await _agent(db, other_org), RunStatus.FAILED),
        )
        other_agent = await _agent(db, world.organization)
        mine_elsewhere = await _attached(
            db, world.person, await world.thread.turn(world.person, other_agent, RunStatus.FAILED)
        )

        rows = await chat_file_repo.get_many_left_by_interrupted_turns(
            db,
            [theirs.id, mine_elsewhere.id],
            conversation_id=world.thread.conversation.id,
            organization_id=world.organization.id,
            user_id=world.person.id,
            agent_id=world.agent.id,
        )

        assert rows == []

    async def test_another_members_file_on_a_shared_thread_stays_theirs(self, db, world) -> None:
        colleague = await _member(db)
        message = await world.thread.turn(colleague, world.agent, RunStatus.FAILED)
        await _attached(db, colleague, message)

        assert await _left(db, world.thread, world.person, world.agent) == []

    async def test_another_conversation_or_organization_answers_nothing(self, db, world) -> None:
        message = await world.thread.turn(world.person, world.agent, RunStatus.FAILED)
        await _attached(db, world.person, message)
        elsewhere = await _conversation(db, world.person, world.organization)
        other = await _organization(db)

        mine = await _left(db, world.thread, world.person, world.agent)
        in_another_thread = await _left(
            db, world.thread, world.person, world.agent, conversation_id=elsewhere.id
        )
        in_another_org = await _left(
            db, world.thread, world.person, world.agent, organization_id=other.id
        )

        assert mine == ["report.csv"]
        assert in_another_thread == []
        assert in_another_org == []

    async def test_the_newest_are_kept_when_there_are_more_than_the_bound(self, db, world) -> None:
        old = await world.thread.turn(world.person, world.agent, RunStatus.FAILED)
        await _attached(db, world.person, old, filename="old.csv")
        new = await world.thread.turn(world.person, world.agent, RunStatus.FAILED)
        newest = await _attached(db, world.person, new, filename="new.csv")
        # One transaction stamps both rows with the same `now()`.
        newest.created_at = datetime.now(UTC) + timedelta(minutes=5)
        await db.flush()

        found = await chat_file_repo.left_by_interrupted_turns(
            db,
            conversation_id=world.thread.conversation.id,
            organization_id=world.organization.id,
            user_id=world.person.id,
            agent_id=world.agent.id,
            limit=1,
            opening_chars=attachments_module._OPENING_CHARS,
        )

        assert found == [(newest.id, "new.csv", "text", len(CSV), CSV.decode())]
