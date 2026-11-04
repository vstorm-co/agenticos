"""The queries the platform's background initiative stands on, against a real database (#2301).

Each is Postgres's answer and not a mock's: a proposal made twice is one row, a
person's requests are theirs and nobody else's, their background spend is only
their background runs, and the nightly sweep reaches only organizations whose
starter agent is published.
"""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets import FunctionToolset
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.permissions import AuthContext
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


async def _turned_on(db, org: Organization) -> None:
    """Proactivity on, on a model of the organization's own, as the settings save it."""
    from app.db.models.credential import ModelProfile
    from app.repositories import organization_repo

    profile = ModelProfile(
        id=uuid.uuid4(),
        organization_id=org.id,
        label="Haiku",
        provider="anthropic",
        model="claude-haiku-5-5",
    )
    db.add(profile)
    await db.flush()
    await organization_repo.set_proactivity(
        db, org, enabled=True, model_profile_id=profile.id, days=[1, 2, 3], hour=6, timing="fixed"
    )


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
    async def test_active_members_of_organizations_that_turned_it_on(self, db) -> None:
        """Off is the default: an organization reaches nobody until it turns the
        look on, with a model; and a person who opted out is never reached."""
        owner = await _person(db, time_zone="Europe/Warsaw")
        suspended = await _person(db, active=False)
        declined = await _person(db)
        declined.proactive_opt_out = True
        org = await _organization(db, owner)
        await _join(db, org, suspended)
        await _join(db, org, declined)
        await _agent(db, org)
        await _turned_on(db, org)
        unpublished_owner = await _person(db)
        unpublished = await _organization(db, unpublished_owner)
        await _agent(db, unpublished, published=False)
        await _turned_on(db, unpublished)
        other_owner = await _person(db)
        other = await _organization(db, other_owner)
        await _agent(db, other, slug="support")
        await _turned_on(db, other)
        off_owner = await _person(db)
        off = await _organization(db, off_owner)
        await _agent(db, off)
        await db.flush()

        candidates = await member_repo.sweep_candidates(db, agent_slug="agenticos")

        (reached,) = [candidate for candidate in candidates if candidate.user_id == owner.id]
        assert reached.organization_id == org.id
        assert reached.time_zone == "Europe/Warsaw"
        assert (reached.days, reached.hour, reached.timing) == ([1, 2, 3], 6, "fixed")
        assert all(
            candidate.user_id
            not in {suspended.id, declined.id, unpublished_owner.id, other_owner.id, off_owner.id}
            for candidate in candidates
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


class TestTheProactivitySettings:
    async def test_they_start_off_on_weekdays_at_five_with_no_greeting(self, db) -> None:
        owner = await _person(db)
        org = await _organization(db, owner)
        await db.refresh(org)

        assert org.proactive_enabled is False
        assert org.proactive_model_profile_id is None
        assert (org.proactive_days, org.proactive_hour, org.proactive_timing) == (
            [1, 2, 3, 4, 5],
            5,
            "fixed",
        )
        assert (org.welcome_dm_enabled, org.welcome_dm_text) == (False, None)

    async def test_an_hour_past_the_day_or_an_unknown_timing_is_refused(self, db) -> None:
        from sqlalchemy.exc import IntegrityError

        from app.repositories import organization_repo

        owner = await _person(db)
        org = await _organization(db, owner)
        for hour, timing in ((24, "fixed"), (5, "whenever")):
            async with db.begin_nested():
                with pytest.raises(IntegrityError):
                    await organization_repo.set_proactivity(
                        db,
                        org,
                        enabled=False,
                        model_profile_id=None,
                        days=[1],
                        hour=hour,
                        timing=timing,  # ty: ignore[invalid-argument-type] - the database's refusal is the subject
                    )

    async def test_the_greeting_is_written_as_given(self, db) -> None:
        from app.repositories import organization_repo

        owner = await _person(db)
        org = await _organization(db, owner)

        await organization_repo.set_welcome_dm(db, org, enabled=True, text="Hi from {bot}")

        assert (org.welcome_dm_enabled, org.welcome_dm_text) == (True, "Hi from {bot}")


class TestPersonalStarters:
    async def test_they_are_kept_per_organization(self, db):
        """Codex on #2324: written from one organization's week, so another
        organization the same person belongs to offers none of them."""
        from app.core.permissions import AuthContext, OrgRoleName
        from app.services.suggestions import SuggestionService

        person = await _person(db)
        here = await _organization(db, person)
        elsewhere = await _organization(db, person)
        member = await member_repo.get(db, organization_id=here.id, user_id=person.id)
        assert member is not None

        await member_repo.set_personal_starters(db, member, starters=["Plan my week"], at=_NOW)

        def ctx(org: Organization) -> AuthContext:
            return AuthContext(user_id=person.id, organization_id=org.id, role=OrgRoleName.MEMBER)

        service = SuggestionService(db)
        assert await service.starters(ctx(here)) == ["Plan my week"]
        assert await service.starters(ctx(elsewhere)) == []
        assert member.personal_starters_at == _NOW


class TestTheSuggestionHistory:
    async def test_every_proposal_newest_first_and_a_dismissed_one_waits_again(self, db) -> None:
        from app.db.models.suggestion import SuggestionStatus

        owner = await _person(db)
        other = await _person(db)
        org = await _organization(db, owner)
        made = []
        for index, (person, key) in enumerate(((owner, "a"), (owner, "b"), (other, "c"))):
            suggestion = await suggestion_repo.propose(
                db,
                organization_id=org.id,
                user_id=person.id,
                kind="routine",
                title=f"Routine {index}",
                detail=None,
                payload={},
                dedupe_key=f"routine:{key}",
            )
            assert suggestion is not None
            suggestion.created_at = _NOW + timedelta(minutes=index)
            made.append(suggestion)
        await db.flush()
        first, second, _ = made
        await suggestion_repo.decide(db, suggestion=first, status=SuggestionStatus.DISMISSED)

        history = await suggestion_repo.list_all(
            db, organization_id=org.id, user_id=owner.id, limit=10
        )
        assert [s.id for s in history] == [second.id, first.id]
        assert await suggestion_repo.list_all(
            db, organization_id=org.id, user_id=owner.id, limit=1
        ) == [second]

        reopened = await suggestion_repo.reopen(db, suggestion=first)
        assert (reopened.status, reopened.decided_at) == (SuggestionStatus.OPEN.value, None)


class TestDeletingTheModelItRunsOn:
    async def test_proactivity_running_on_it_is_switched_off_and_nothing_else(self, db) -> None:
        from app.repositories import organization_repo

        owner = await _person(db)
        org = await _organization(db, owner)
        await _turned_on(db, org)
        model = org.proactive_model_profile_id
        assert model is not None

        await organization_repo.stop_proactivity_on(
            db, organization_id=org.id, model_profile_id=uuid.uuid4()
        )
        await db.refresh(org)
        assert org.proactive_enabled is True

        await organization_repo.set_watch_policy(db, org, enabled=True, min_minutes=30)
        await organization_repo.stop_proactivity_on(
            db, organization_id=org.id, model_profile_id=model
        )
        await db.refresh(org)
        assert org.proactive_enabled is False
        assert org.proactive_watches_enabled is False
        assert org.proactive_watch_min_minutes == 30


async def _own_connection(db, person: User, *, name: str = "github"):
    from app.db.models.mcp_connection import McpConnection

    connection = McpConnection(
        id=uuid.uuid4(),
        scope="user",
        user_id=person.id,
        name=f"{name}-{uuid.uuid4().hex[:6]}",
        catalog_key=name,
        url="https://mcp.example.com/mcp",
        secret_key_version=1,
    )
    db.add(connection)
    await db.flush()
    return connection


async def _watch(db, org: Organization, person: User, connection, **fields):
    from app.repositories import watch_repo

    return await watch_repo.create(
        db,
        organization_id=org.id,
        user_id=person.id,
        connection_id=connection.id,
        preset_key=fields.get("preset_key"),
        title=fields.get("title", "Reviews"),
        instructions="Pull requests waiting on my review.",
        urgent=fields.get("urgent", False),
        interval_minutes=fields.get("interval_minutes", 60),
        next_run_at=fields.get("next_run_at", _NOW),
    )


class TestWatches:
    async def test_a_persons_own_watches_and_nobody_elses(self, db) -> None:
        from app.repositories import watch_repo

        person = await _person(db)
        colleague = await _person(db)
        org = await _organization(db, person)
        await _join(db, org, colleague)
        mine = await _own_connection(db, person)
        theirs = await _own_connection(db, colleague)
        first = await _watch(db, org, person, mine, title="First")
        second = await _watch(db, org, person, mine, title="Second")
        other = await _watch(db, org, colleague, theirs)

        listed = await watch_repo.list_own(db, organization_id=org.id, user_id=person.id)
        assert {watch.id for watch in listed} == {first.id, second.id}
        assert first.exclusions == [] and first.is_active is True
        assert (
            await watch_repo.get_own(db, other.id, organization_id=org.id, user_id=person.id)
            is None
        )
        assert (await watch_repo.get_by_id(db, other.id)) is other
        assert "Watch(" in repr(first)

    async def test_due_watches_are_claimed_moved_and_written_down(self, db) -> None:
        from app.repositories import watch_repo

        person = await _person(db)
        org = await _organization(db, person)
        connection = await _own_connection(db, person)
        due = await _watch(db, org, person, connection, next_run_at=_NOW - timedelta(minutes=1))
        later = await _watch(db, org, person, connection, next_run_at=_NOW + timedelta(hours=1))
        paused = await _watch(db, org, person, connection, next_run_at=_NOW - timedelta(hours=1))
        await watch_repo.update_fields(db, watch=paused, changes={"is_active": False})

        claimed = await watch_repo.claim_due(db, now=_NOW, limit=50)
        assert due.id in {watch.id for watch in claimed}
        assert {later.id, paused.id}.isdisjoint({watch.id for watch in claimed})

        await watch_repo.schedule(db, watch_id=due.id, next_run_at=_NOW + timedelta(hours=2))
        await watch_repo.mark_ran(db, watch=due, at=_NOW)
        await db.refresh(due)
        assert due.next_run_at == _NOW + timedelta(hours=2)
        assert due.last_run_at == _NOW

    async def test_a_cadence_under_fifteen_minutes_is_refused_by_the_database(self, db) -> None:
        from sqlalchemy.exc import IntegrityError

        person = await _person(db)
        org = await _organization(db, person)
        connection = await _own_connection(db, person)
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await _watch(db, org, person, connection, interval_minutes=5)

    async def test_findings_are_kept_per_watch_and_go_with_it_and_with_the_connection(
        self, db
    ) -> None:
        from app.repositories import watch_repo

        person = await _person(db)
        org = await _organization(db, person)
        connection = await _own_connection(db, person)
        watch = await _watch(db, org, person, connection)
        for n in range(3):
            await suggestion_repo.propose(
                db,
                organization_id=org.id,
                user_id=person.id,
                kind="finding",
                title=f"Review #{n}",
                detail=None,
                payload={"server": "github", "account": None, "url": None},
                dedupe_key=f"finding:{n}",
                watch_id=watch.id,
                urgent=n == 2,
            )

        # One transaction stamps all three alike, so only how many is asserted.
        titles = await suggestion_repo.titles_for_watch(db, watch_id=watch.id, limit=2)
        assert len(titles) == 2 and set(titles) <= {"Review #0", "Review #1", "Review #2"}
        (urgent,) = [
            item
            for item in await suggestion_repo.list_open(
                db, organization_id=org.id, user_id=person.id
            )
            if item.urgent
        ]
        assert urgent.watch_id == watch.id
        await suggestion_repo.decide(db, suggestion=urgent, status=SuggestionStatus.DISMISSED)
        other = await _watch(db, org, person, connection)
        assert await suggestion_repo.open_findings_by_watch(db, watch_ids=[watch.id, other.id]) == {
            watch.id: 2
        }
        assert await suggestion_repo.open_findings_by_watch(db, watch_ids=[]) == {}

        await watch_repo.delete(db, watch)
        assert await suggestion_repo.list_open(db, organization_id=org.id, user_id=person.id) == []

        survivor = await _watch(db, org, person, connection)
        await db.delete(connection)
        await db.flush()
        db.expunge(survivor)
        assert await watch_repo.get_by_id(db, survivor.id) is None


class TestTheMorningBriefing:
    async def test_only_open_findings_not_sent_at_once_and_in_no_briefing_wait(self, db) -> None:
        from app.repositories import organization_repo

        person = await _person(db)
        org = await _organization(db, person)
        await organization_repo.set_watch_policy(db, org, enabled=True, min_minutes=60)
        connection = await _own_connection(db, person)
        watch = await _watch(db, org, person, connection)
        made = {}
        for key, urgent in (
            ("waits", False),
            ("urgent", True),
            ("briefed", False),
            ("done", False),
        ):
            made[key] = await suggestion_repo.propose(
                db,
                organization_id=org.id,
                user_id=person.id,
                kind="finding",
                title=key,
                detail=None,
                payload={},
                dedupe_key=f"finding:{key}",
                watch_id=watch.id,
                urgent=urgent,
            )
        await suggestion_repo.mark_briefed(db, suggestion_ids=[made["briefed"].id], at=_NOW)
        await suggestion_repo.decide(db, suggestion=made["done"], status=SuggestionStatus.ACCEPTED)
        waits_id = made["waits"].id

        waiting = await suggestion_repo.unbriefed_findings(
            db, organization_id=org.id, user_id=person.id
        )
        assert [finding.title for finding in waiting] == ["waits"]
        (reached,) = [
            candidate
            for candidate in await member_repo.briefing_candidates(db)
            if candidate.user_id == person.id
        ]
        assert reached.organization_id == org.id

        await suggestion_repo.mark_briefed(db, suggestion_ids=[waits_id], at=_NOW)
        assert all(
            candidate.user_id != person.id
            for candidate in await member_repo.briefing_candidates(db)
        )

    async def test_an_organization_with_watches_off_briefs_nobody(self, db) -> None:
        person = await _person(db)
        org = await _organization(db, person)
        await suggestion_repo.propose(
            db,
            organization_id=org.id,
            user_id=person.id,
            kind="finding",
            title="x",
            detail=None,
            payload={},
            dedupe_key="finding:off",
        )
        assert all(
            candidate.user_id != person.id
            for candidate in await member_repo.briefing_candidates(db)
        )


async def test_proactive_heartbeat_and_cancelled_usage_survive_the_job_rollback(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import run_heartbeat as heartbeat
    from app.services.proactive._thinker import ProactiveThinker

    user = await _person(db)
    organization = await _organization(db, user)
    agent = await _agent(db, organization)
    await db.commit()
    ctx = AuthContext(user_id=user.id, organization_id=organization.id, role="owner")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def context() -> AsyncGenerator[AsyncSession]:
        async with factory() as held:
            yield held
            await held.commit()

    monkeypatch.setattr(heartbeat, "get_db_context", context)
    monkeypatch.setattr(heartbeat.settings, "RUN_HEARTBEAT_SECONDS", 0.01)
    entered = asyncio.Event()

    async def read_account() -> str:
        entered.set()
        await asyncio.Event().wait()
        return "unreachable"

    request = SimpleNamespace(
        build=lambda: TestModel(), label="Test", model="test", provider="test", secret_id=None
    )
    with (
        patch.object(ProactiveThinker, "allowance", AsyncMock(return_value=uuid.uuid4())),
        patch(
            "app.services.proactive._thinker.ModelProfileService.resolve",
            AsyncMock(return_value=request),
        ),
    ):
        task = asyncio.create_task(
            ProactiveThinker(db).think(
                ctx,
                feature="watches",
                output_type=str,
                instructions="Read.",
                prompt="Read.",
                toolsets=[FunctionToolset([read_account])],
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), 10)
            async with context() as observer:
                run_id = (
                    await observer.scalars(select(AgentRun.id).where(AgentRun.agent_id == agent.id))
                ).one()
                old = datetime.now(UTC) - timedelta(minutes=10)
                await observer.execute(
                    update(AgentRun)
                    .where(AgentRun.id == run_id)
                    .values(started_at=old, updated_at=old, heartbeat_at=None)
                )
            async with asyncio.timeout(10):
                while True:
                    async with context() as observer:
                        beat = await observer.scalar(
                            select(AgentRun.heartbeat_at).where(AgentRun.id == run_id)
                        )
                    if beat is not None:
                        break
                    await asyncio.sleep(0.01)
            async with context() as observer:
                assert (
                    await agent_run_repo.fail_stale_runs(
                        observer,
                        older_than=datetime.now(UTC) - timedelta(seconds=120),
                        ended_at=datetime.now(UTC),
                        error="stale",
                    )
                    == []
                )
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await db.rollback()
            async with context() as observer:
                run = await observer.get(AgentRun, run_id)
                assert run is not None and run.status == RunStatus.CANCELLED.value
                assert run.input_tokens > 0 and run.output_tokens > 0
                assert run.ended_at is not None
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
