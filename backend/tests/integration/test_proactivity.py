"""The queries the platform's background initiative stands on, against a real database (#2301).

Each is Postgres's answer and not a mock's: a proposal made twice is one row, a
person's requests are theirs and nobody else's, their background spend is only
their background runs, and the nightly sweep reaches only organizations whose
starter agent is published.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.suggestion import SuggestionStatus
from app.db.models.user import User
from app.repositories import (
    agent_run_repo,
    agent_trigger_repo,
    conversation_repo,
    member_repo,
    suggestion_repo,
)

pytestmark = pytest.mark.anyio

_NOW = datetime.now(UTC)


async def _person(db, *, active: bool = True, time_zone: str | None = None) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@acme.com",
        hashed_password="x",
        is_active=active,
        time_zone=time_zone,
    )
    db.add(user)
    await db.flush()
    return user


async def _organization(db, owner: User) -> Organization:
    org = Organization(
        id=uuid.uuid4(), name="Acme", slug=uuid.uuid4().hex[:12], created_by_user_id=owner.id
    )
    db.add(org)
    await db.flush()
    await _join(db, org, owner)
    return org


async def _join(db, org: Organization, user: User) -> None:
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role="member")
    )
    await db.flush()


async def _agent(
    db, org: Organization, *, slug: str = "agenticos", published: bool = True
) -> Agent:
    agent = Agent(
        id=uuid.uuid4(), organization_id=org.id, slug=slug, name="AgenticOS", draft_spec={}
    )
    db.add(agent)
    await db.flush()
    if published:
        version = AgentVersion(
            id=uuid.uuid4(), organization_id=org.id, agent_id=agent.id, version=1, spec={}
        )
        db.add(version)
        await db.flush()
        agent.current_version_id = version.id
        await db.flush()
    return agent


async def _run(db, org, agent, user, *, surface: RunSurface, cost: str, started_at=_NOW) -> None:
    db.add(
        AgentRun(
            id=uuid.uuid4(),
            organization_id=org.id,
            agent_id=agent.id,
            user_id=user.id,
            status=RunStatus.COMPLETED.value,
            surface=surface.value,
            started_at=started_at,
            cost_usd=Decimal(cost),
        )
    )
    await db.flush()


class TestSuggestions:
    async def test_the_same_proposal_is_one_row_however_often_it_is_made(self, db) -> None:
        user = await _person(db)
        org = await _organization(db, user)
        kwargs = {
            "organization_id": org.id,
            "user_id": user.id,
            "kind": "routine",
            "title": "Every Monday",
            "detail": None,
            "payload": {"prompt": "Summarise"},
            "dedupe_key": "routine:abc",
        }

        first = await suggestion_repo.propose(db, **kwargs)
        assert first is not None
        assert await suggestion_repo.propose(db, **kwargs) is None

        # Dismissed is remembered: still taken, never proposed again.
        await suggestion_repo.decide(db, suggestion=first, status=SuggestionStatus.DISMISSED)
        assert await suggestion_repo.propose(db, **kwargs) is None
        assert await suggestion_repo.list_open(db, organization_id=org.id, user_id=user.id) == []
        assert await suggestion_repo.keys_for(db, organization_id=org.id, user_id=user.id) == {
            "routine:abc"
        }

    async def test_a_suggestion_is_reached_only_by_the_person_it_was_made_to(self, db) -> None:
        owner = await _person(db)
        other = await _person(db)
        org = await _organization(db, owner)
        made = await suggestion_repo.propose(
            db,
            organization_id=org.id,
            user_id=owner.id,
            kind="agent",
            title="An agent",
            detail="why",
            payload={},
            dedupe_key="agent:1",
        )
        assert made is not None

        assert (
            await suggestion_repo.get_own(db, made.id, organization_id=org.id, user_id=other.id)
            is None
        )
        assert (
            await suggestion_repo.get_own(
                db, made.id, organization_id=uuid.uuid4(), user_id=owner.id
            )
            is None
        )
        assert (
            await suggestion_repo.get_own(db, made.id, organization_id=org.id, user_id=owner.id)
        ) == made
        assert [
            s.id
            for s in await suggestion_repo.list_open(db, organization_id=org.id, user_id=owner.id)
        ] == [made.id]


class TestBackgroundSpend:
    async def test_only_the_persons_background_runs_this_month_count(self, db) -> None:
        user = await _person(db)
        other = await _person(db)
        org = await _organization(db, user)
        agent = await _agent(db, org)
        await _run(db, org, agent, user, surface=RunSurface.PROACTIVE, cost="0.10")
        await _run(db, org, agent, user, surface=RunSurface.PROACTIVE, cost="0.05")
        await _run(db, org, agent, user, surface=RunSurface.WEB, cost="5")
        await _run(db, org, agent, other, surface=RunSurface.PROACTIVE, cost="1")
        await _run(
            db,
            org,
            agent,
            user,
            surface=RunSurface.PROACTIVE,
            cost="9",
            started_at=_NOW - timedelta(days=60),
        )

        spent = await agent_run_repo.proactive_spend_since(
            db, organization_id=org.id, user_id=user.id, since=_NOW - timedelta(days=1)
        )

        assert spent == Decimal("0.15")
        assert (
            await agent_run_repo.last_proactive_run_at(db, organization_id=org.id, user_id=user.id)
            == _NOW
        )

    async def test_nobody_looked_at_yet_has_no_last_look(self, db) -> None:
        user = await _person(db)
        org = await _organization(db, user)

        assert (
            await agent_run_repo.last_proactive_run_at(db, organization_id=org.id, user_id=user.id)
            is None
        )
        assert await agent_run_repo.proactive_spend_since(
            db, organization_id=org.id, user_id=user.id, since=_NOW - timedelta(days=1)
        ) == Decimal(0)


class TestAPersonsRequests:
    async def test_their_own_requests_and_nobody_elses(self, db) -> None:
        person = await _person(db)
        colleague = await _person(db)
        org = await _organization(db, person)
        elsewhere = await _organization(db, person)
        mine = Conversation(id=uuid.uuid4(), user_id=person.id, organization_id=org.id)
        shared = Conversation(id=uuid.uuid4(), user_id=colleague.id, organization_id=org.id)
        abroad = Conversation(id=uuid.uuid4(), user_id=person.id, organization_id=elsewhere.id)
        db.add_all([mine, shared, abroad])
        await db.flush()
        db.add_all(
            [
                Message(id=uuid.uuid4(), conversation_id=mine.id, role="user", content="mine"),
                Message(
                    id=uuid.uuid4(), conversation_id=mine.id, role="assistant", content="answer"
                ),
                Message(
                    id=uuid.uuid4(),
                    conversation_id=shared.id,
                    role="user",
                    content="said in a shared chat",
                    author_user_id=person.id,
                ),
                Message(
                    id=uuid.uuid4(),
                    conversation_id=shared.id,
                    role="user",
                    content="the colleague's",
                ),
                Message(id=uuid.uuid4(), conversation_id=abroad.id, role="user", content="abroad"),
            ]
        )
        await db.flush()

        found = await conversation_repo.person_requests_since(
            db,
            organization_id=org.id,
            user_id=person.id,
            since=_NOW - timedelta(days=1),
            limit=10,
        )

        assert sorted(message.content for message in found) == ["mine", "said in a shared chat"]


class TestWhoTheNightlySweepReaches:
    async def test_active_members_of_organizations_with_a_published_starter(self, db) -> None:
        owner = await _person(db, time_zone="Europe/Warsaw")
        suspended = await _person(db, active=False)
        org = await _organization(db, owner)
        await _join(db, org, suspended)
        await _agent(db, org)
        unpublished_owner = await _person(db)
        unpublished = await _organization(db, unpublished_owner)
        await _agent(db, unpublished, published=False)
        other_owner = await _person(db)
        other = await _organization(db, other_owner)
        await _agent(db, other, slug="support")

        candidates = await member_repo.sweep_candidates(db, agent_slug="agenticos")

        assert (org.id, owner.id, "Europe/Warsaw") in candidates
        assert all(
            user_id not in {suspended.id, unpublished_owner.id, other_owner.id}
            for _, user_id, _ in candidates
        )


class TestTheirRoutines:
    async def test_the_prompts_of_routines_they_set_up_here(self, db) -> None:
        person = await _person(db)
        colleague = await _person(db)
        org = await _organization(db, person)
        agent = await _agent(db, org)
        for creator, prompt in ((person, "mine"), (colleague, "theirs")):
            db.add(
                AgentTrigger(
                    id=uuid.uuid4(),
                    organization_id=org.id,
                    agent_id=agent.id,
                    created_by_user_id=creator.id,
                    prompt=prompt,
                    trigger_type="schedule",
                    schedule_kind="interval",
                    interval_seconds=3600,
                    next_fire_at=_NOW + timedelta(hours=1),
                )
            )
        await db.flush()

        assert await agent_trigger_repo.prompts_created_by(
            db, organization_id=org.id, user_id=person.id
        ) == ["mine"]


class TestTheProactivityLimit:
    async def test_it_starts_at_a_dollar_and_zero_is_off_but_never_below(self, db) -> None:
        from sqlalchemy.exc import IntegrityError

        from app.repositories import organization_repo

        owner = await _person(db)
        org = await _organization(db, owner)
        await db.refresh(org)
        assert org.proactive_limit_usd == Decimal("1")

        await organization_repo.set_proactive_limit(db, org, limit_usd=Decimal("0"))
        assert org.proactive_limit_usd == Decimal("0")

        with pytest.raises(IntegrityError):
            await organization_repo.set_proactive_limit(db, org, limit_usd=Decimal("-1"))
