"""The authoring assistant's tables and evidence reads against Postgres.

What only a database shows:

- the evidence the assistant may read never includes an eval run, a Builder
  test or a delegate's run, and comes rated-down-with-a-comment first;
- the runs that opened a skill are found by the `load_capability` call;
- an agent holds at most one open batch, whatever two writers attempt;
- a hunk decision is a compare-and-set: only one of two decisions lands;
- and nothing is read across organizations.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunSurface
from app.db.models.authoring import AuthoringStatus, BatchStatus, HunkStatus
from app.db.models.conversation import Conversation, Message, ToolCall
from app.db.models.message_rating import MessageRating
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import authoring_repo

pytestmark = pytest.mark.anyio

_LONG_AGO = datetime.now(UTC) - timedelta(days=30)


async def _org(db: AsyncSession) -> tuple[Organization, User]:
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
    )
    db.add(org)
    await db.flush()
    return org, user


async def _agent(db: AsyncSession, org: Organization, user: User) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        owner_user_id=user.id,
        visibility="org",
        slug=f"clerk-{uuid.uuid4().hex[:8]}",
        name="Clerk",
        status="draft",
        draft_spec={"name": "Clerk"},
    )
    db.add(agent)
    await db.flush()
    return agent


async def _run(
    db: AsyncSession,
    org: Organization,
    agent: Agent,
    user: User,
    *,
    rating: int | None = None,
    comment: str | None = None,
    surface: RunSurface = RunSurface.WEB,
    status: str = "completed",
    is_test: bool = False,
    parent: AgentRun | None = None,
    started_at: datetime | None = None,
    tool: tuple[str, dict[str, str]] | None = None,
) -> AgentRun:
    conversation = Conversation(id=uuid.uuid4(), organization_id=org.id, user_id=user.id)
    db.add(conversation)
    await db.flush()
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        user_id=user.id,
        conversation_id=conversation.id,
        surface=surface.value,
        status=status,
        is_test=is_test,
        parent_run_id=None if parent is None else parent.id,
        started_at=started_at or datetime.now(UTC),
    )
    db.add(run)
    await db.flush()
    answer = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        role="assistant",
        content="An answer",
        agent_id=agent.id,
        run_id=run.id,
    )
    db.add(answer)
    await db.flush()
    if rating is not None:
        db.add(MessageRating(message_id=answer.id, user_id=user.id, rating=rating, comment=comment))
    if tool is not None:
        db.add(
            ToolCall(
                message_id=answer.id,
                tool_call_id=uuid.uuid4().hex,
                tool_name=tool[0],
                args=tool[1],
                started_at=datetime.now(UTC),
            )
        )
    await db.flush()
    return run


class TestEvidence:
    async def test_eval_runs_tests_and_delegates_are_never_evidence(self, db: AsyncSession):
        org, user = await _org(db)
        agent = await _agent(db, org, user)
        kept = await _run(db, org, agent, user, rating=-1)
        await _run(db, org, agent, user, rating=-1, surface=RunSurface.EVAL)
        await _run(db, org, agent, user, rating=-1, is_test=True)
        await _run(db, org, agent, user, rating=-1, parent=kept)

        rows = await authoring_repo.evidence_runs(
            db, organization_id=org.id, agent_id=agent.id, since=_LONG_AGO, limit=10
        )

        assert [row.run.id for row in rows] == [kept.id]

    async def test_a_commented_down_rating_comes_first_and_an_unrated_success_not_at_all(
        self, db: AsyncSession
    ):
        org, user = await _org(db)
        agent = await _agent(db, org, user)
        liked = await _run(db, org, agent, user, rating=1)
        failed = await _run(db, org, agent, user, status="failed")
        disliked = await _run(db, org, agent, user, rating=-1)
        explained = await _run(db, org, agent, user, rating=-1, comment="Wrong refund window")
        await _run(db, org, agent, user)

        rows = await authoring_repo.evidence_runs(
            db, organization_id=org.id, agent_id=agent.id, since=_LONG_AGO, limit=10
        )

        assert [row.run.id for row in rows] == [explained.id, disliked.id, failed.id, liked.id]
        assert rows[0].comments == ["Wrong refund window"]
        assert [row.rating for row in rows] == [-1, -1, 0, 1]

    async def test_evidence_is_bounded_by_window_count_and_organization(self, db: AsyncSession):
        org, user = await _org(db)
        other, other_user = await _org(db)
        agent = await _agent(db, org, user)
        foreign = await _agent(db, other, other_user)
        recent = await _run(db, org, agent, user, rating=-1)
        await _run(
            db, org, agent, user, rating=-1, started_at=datetime.now(UTC) - timedelta(days=60)
        )
        await _run(db, other, foreign, other_user, rating=-1)

        rows = await authoring_repo.evidence_runs(
            db, organization_id=org.id, run_ids=None, since=_LONG_AGO, limit=10
        )
        limited = await authoring_repo.evidence_runs(
            db, organization_id=org.id, run_ids=[recent.id], since=_LONG_AGO, limit=1
        )

        assert [row.run.id for row in rows] == [recent.id]
        assert [row.run.id for row in limited] == [recent.id]

    async def test_the_runs_that_opened_a_skill_are_found_by_its_load_call(self, db: AsyncSession):
        org, user = await _org(db)
        agent = await _agent(db, org, user)
        loaded = await _run(db, org, agent, user, tool=("load_capability", {"id": "refunds"}))
        await _run(db, org, agent, user, tool=("load_capability", {"id": "shipping"}))
        await _run(
            db,
            org,
            agent,
            user,
            surface=RunSurface.EVAL,
            tool=("load_capability", {"id": "refunds"}),
        )

        found = await authoring_repo.runs_that_loaded_skill(
            db, organization_id=org.id, skill_name="refunds", since=_LONG_AGO, limit=10
        )

        assert found == [loaded.id]


class TestProposals:
    async def _batch(self, db: AsyncSession, org: Organization, agent: Agent):
        return await authoring_repo.create_batch(
            db,
            organization_id=org.id,
            agent_id=agent.id,
            request_id=None,
            source_started_at=datetime.now(UTC),
            expected_effect="Answers name the 30-day window",
            evidence_conversation_ids=[],
        )

    async def test_an_agent_holds_one_open_batch(self, db: AsyncSession):
        org, user = await _org(db)
        agent = await _agent(db, org, user)
        first = await self._batch(db, org, agent)

        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await self._batch(db, org, agent)

        await authoring_repo.close_batch(db, batch=first, status=BatchStatus.SUPERSEDED)
        second = await self._batch(db, org, agent)
        open_batch = await authoring_repo.get_open_batch(
            db, organization_id=org.id, agent_id=agent.id, lock=True
        )
        latest = await authoring_repo.latest_batch(db, organization_id=org.id, agent_id=agent.id)

        assert open_batch is not None and open_batch.id == second.id
        assert latest is not None and latest.id == second.id
        assert first.closed_at is not None

    async def test_a_hunk_is_decided_once(self, db: AsyncSession):
        org, user = await _org(db)
        agent = await _agent(db, org, user)
        batch = await self._batch(db, org, agent)
        (hunk,) = await authoring_repo.add_hunks(
            db,
            organization_id=org.id,
            batch_id=batch.id,
            hunks=[{"kind": "instructions", "origin": "improve", "new_text": "Cite the policy."}],
        )

        accepted = await authoring_repo.decide_hunk(
            db,
            organization_id=org.id,
            hunk_id=hunk.id,
            expected=HunkStatus.PENDING,
            status=HunkStatus.ACCEPTED,
            decided_by=user.id,
            values={"accepted_text": "Cite the policy."},
        )
        late = await authoring_repo.decide_hunk(
            db,
            organization_id=org.id,
            hunk_id=hunk.id,
            expected=HunkStatus.PENDING,
            status=HunkStatus.DISMISSED,
            decided_by=user.id,
        )
        undone = await authoring_repo.decide_hunk(
            db,
            organization_id=org.id,
            hunk_id=hunk.id,
            expected=HunkStatus.ACCEPTED,
            status=HunkStatus.PENDING,
            decided_by=user.id,
        )

        assert accepted is not None and accepted.accepted_text == "Cite the policy."
        assert late is None
        assert (
            undone is not None and undone.decided_at is None and undone.decided_by_user_id is None
        )

    async def test_hunks_append_in_order_and_count_while_pending(self, db: AsyncSession):
        org, user = await _org(db)
        agent = await _agent(db, org, user)
        batch = await self._batch(db, org, agent)
        await authoring_repo.add_hunks(
            db,
            organization_id=org.id,
            batch_id=batch.id,
            hunks=[{"kind": "instructions", "origin": "improve"}],
        )
        await authoring_repo.add_hunks(
            db,
            organization_id=org.id,
            batch_id=batch.id,
            hunks=[
                {
                    "kind": "tool_override",
                    "origin": "verify",
                    "capability_id": "knowledge",
                    "tool_id": "search_knowledge",
                }
            ],
        )

        hunks = await authoring_repo.list_hunks(db, organization_id=org.id, batch_id=batch.id)
        counts = await authoring_repo.pending_counts(
            db, organization_id=org.id, agent_ids=[agent.id]
        )

        assert [hunk.position for hunk in hunks] == [0, 1]
        assert counts == {agent.id: {"instructions": 1, "tool_override": 1}}
        assert await authoring_repo.pending_counts(db, organization_id=org.id, agent_ids=[]) == {}

    async def test_nothing_is_read_across_organizations(self, db: AsyncSession):
        org, user = await _org(db)
        other, _ = await _org(db)
        agent = await _agent(db, org, user)
        batch = await self._batch(db, org, agent)
        (hunk,) = await authoring_repo.add_hunks(
            db,
            organization_id=org.id,
            batch_id=batch.id,
            hunks=[{"kind": "instructions", "origin": "improve"}],
        )
        request = await authoring_repo.create_request(
            db,
            organization_id=org.id,
            kind="improve",
            target="agent",
            agent_id=agent.id,
            skill_id=None,
            created_by_user_id=user.id,
            estimate_usd=Decimal("0.05"),
            window_days=30,
        )

        locked = await authoring_repo.get_batch(db, batch.id, organization_id=org.id, lock=True)
        unlocked = await authoring_repo.get_open_batch(
            db, organization_id=org.id, agent_id=agent.id
        )

        assert locked is not None and unlocked is not None and locked.id == unlocked.id
        assert await authoring_repo.get_batch(db, batch.id, organization_id=other.id) is None
        assert await authoring_repo.get_hunk(db, hunk.id, organization_id=other.id) is None
        assert await authoring_repo.get_request(db, request.id, organization_id=other.id) is None
        assert (
            await authoring_repo.list_hunks(db, organization_id=other.id, batch_id=batch.id) == []
        )
        assert (
            await authoring_repo.decide_hunk(
                db,
                organization_id=other.id,
                hunk_id=hunk.id,
                expected=HunkStatus.PENDING,
                status=HunkStatus.ACCEPTED,
                decided_by=None,
            )
            is None
        )

    async def test_requests_are_listed_newest_first_per_target(self, db: AsyncSession):
        org, user = await _org(db)
        agent = await _agent(db, org, user)
        request = await authoring_repo.create_request(
            db,
            organization_id=org.id,
            kind="improve",
            target="agent",
            agent_id=agent.id,
            skill_id=None,
            created_by_user_id=user.id,
            estimate_usd=Decimal("0.05"),
            window_days=30,
        )
        await authoring_repo.update_request(
            db, request=request, values={"status": AuthoringStatus.RUNNING.value}
        )
        batch = await self._batch(db, org, agent)
        await authoring_repo.update_batch(db, batch=batch, values={"expected_effect": "x"})

        for_agent = await authoring_repo.list_requests(
            db, organization_id=org.id, agent_id=agent.id
        )
        for_skill = await authoring_repo.list_requests(
            db, organization_id=org.id, skill_id=uuid.uuid4()
        )

        assert [row.id for row in for_agent] == [request.id]
        assert for_agent[0].status == "running"
        assert for_skill == []
        assert batch.expected_effect == "x"
