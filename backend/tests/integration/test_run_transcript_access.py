"""Reading a run's transcript, against Postgres - authorized, not owned.

The three claims this issue turns on are claims about which rows a query lands
on and which tenant a read is bounded to, so a mocked session cannot make them:

- a colleague holding `runs:view` reads a run *somebody else started*, because
  authority over a run is the organization's and not its starter's;
- the same read for *another tenant's* run is refused exactly as a run that never
  existed is - same exception, same message, same `details` keys - so the
  response cannot be used to discover that the run exists;
- the conversation endpoint one route over is left owner-scoped, so making a
  run's transcript readable by a colleague did not widen who can read the private
  thread it sits in. The last is what stops this being "fixed" by loosening the
  wrong thing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.user import User
from app.services.agent_runner import AgentRunnerService
from app.services.conversation import ConversationService

pytestmark = pytest.mark.anyio

_START = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)


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


async def _org(db) -> tuple[Organization, User]:
    owner = await _user(db)
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(organization)
    await db.flush()
    return organization, owner


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


async def _conversation(db, organization: Organization, owner: User) -> Conversation:
    conversation = Conversation(
        id=uuid.uuid4(),
        user_id=owner.id,
        organization_id=organization.id,
        title="Quarterly numbers",
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def _run(
    db,
    organization: Organization,
    agent: Agent,
    *,
    conversation: Conversation | None,
) -> AgentRun:
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=organization.id,
        agent_id=agent.id,
        conversation_id=None if conversation is None else conversation.id,
        status="completed",
        started_at=_START,
        ended_at=_START + timedelta(minutes=1),
    )
    db.add(run)
    await db.flush()
    return run


async def _turn(
    db, conversation: Conversation, run: AgentRun, *, role: str, content: str, at: datetime
) -> Message:
    message = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        run_id=run.id,
        role=role,
        content=content,
        created_at=at,
    )
    db.add(message)
    await db.flush()
    return message


def _operator(organization: Organization, user_id: uuid.UUID) -> AuthContext:
    """A colleague who holds `runs:view` - operator does - and is not the owner."""
    return AuthContext(
        user_id=user_id, organization_id=organization.id, role=OrgRoleName.OPERATOR.value
    )


class TestAColleagueReadsARunTheyDidNotStart:
    async def test_the_transcript_is_the_runs_turns_in_order(self, db) -> None:
        organization, owner = await _org(db)
        agent = await _agent(db, organization)
        conversation = await _conversation(db, organization, owner)
        run = await _run(db, organization, agent, conversation=conversation)
        await _turn(db, conversation, run, role="user", content="how many are open?", at=_START)
        await _turn(
            db,
            conversation,
            run,
            role="assistant",
            content="two",
            at=_START + timedelta(minutes=1),
        )

        colleague = await _user(db)
        got_run, messages, total = await AgentRunnerService(db).get_run_transcript(
            _operator(organization, colleague.id), run.id
        )

        assert colleague.id != owner.id
        assert got_run.id == run.id
        assert [message.content for message in messages] == ["how many are open?", "two"]
        assert total == 2


class TestAnotherTenantsRunIsRefusedAsAMissingOne:
    async def test_the_cross_tenant_read_and_the_unknown_id_answer_alike(self, db) -> None:
        home, owner = await _org(db)
        agent = await _agent(db, home)
        conversation = await _conversation(db, home, owner)
        theirs = await _run(db, home, agent, conversation=conversation)
        await _turn(db, conversation, theirs, role="user", content="secret", at=_START)

        # A caller in a different organization, holding `runs:view` there.
        outsider = await _user(db)
        other, _ = await _org(db)
        service = AgentRunnerService(db)
        ctx = _operator(other, outsider.id)

        with pytest.raises(NotFoundError) as cross_tenant:
            await service.get_run_transcript(ctx, theirs.id)
        with pytest.raises(NotFoundError) as unknown:
            await service.get_run_transcript(ctx, uuid.uuid4())

        # Same status, same body shape - the neighbour's run is indistinguishable
        # from one that never existed.
        assert cross_tenant.value.message == unknown.value.message == "Run not found"
        assert cross_tenant.value.code == unknown.value.code
        assert (
            set(cross_tenant.value.details or {}) == set(unknown.value.details or {}) == {"run_id"}
        )


class TestARunWithNoConversationReportsNoTranscript:
    async def test_a_null_conversation_reads_as_no_transcript_not_an_empty_thread(self, db) -> None:
        organization, _ = await _org(db)
        agent = await _agent(db, organization)
        run = await _run(db, organization, agent, conversation=None)

        colleague = await _user(db)
        got_run, messages, total = await AgentRunnerService(db).get_run_transcript(
            _operator(organization, colleague.id), run.id
        )

        assert got_run.conversation_id is None
        assert (messages, total) == ([], 0)


class TestTheConversationEndpointStaysOwnerScoped:
    async def test_a_colleague_who_may_read_the_run_still_cannot_read_the_thread(self, db) -> None:
        """The guard against fixing this by loosening the wrong route.

        The same colleague who reads the run's transcript above is refused the
        conversation the run sits in: a run is the organization's, a thread is a
        person's, and this proves the second rule was not relaxed to satisfy the
        first.
        """
        organization, owner = await _org(db)
        agent = await _agent(db, organization)
        conversation = await _conversation(db, organization, owner)
        run = await _run(db, organization, agent, conversation=conversation)
        await _turn(db, conversation, run, role="user", content="how many are open?", at=_START)

        colleague = await _user(db)
        with pytest.raises(NotFoundError):
            await ConversationService(db).list_messages(
                conversation.id, organization_id=organization.id, user_id=colleague.id
            )
