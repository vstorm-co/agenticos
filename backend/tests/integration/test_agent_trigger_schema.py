"""What the agent_triggers schema guarantees, against a real database.

The unit tests read the statements back; these run them. Three things a mock
cannot tell you: that the CHECK constraints reject a bad row, that the claim
returns exactly the due-active-attributable triggers, and - the one the whole
no-double-fire design rests on - that a second heartbeat claiming at the same
instant takes none of the rows the first one locked.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import agent_trigger_repo
from app.schemas.agent_trigger import TriggerCreate, TriggerRead
from app.services.agent_trigger import AgentTriggerService

pytestmark = pytest.mark.anyio


async def _org(db) -> Organization:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
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
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role="owner")
    )
    await db.flush()
    org.owner_user = user  # type: ignore[attr-defined]  - test convenience
    return org


async def _agent(db, org: Organization) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=f"a-{uuid.uuid4().hex[:8]}",
        name="Nightly",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    return agent


def _trigger(org: Organization, agent: Agent, **overrides) -> AgentTrigger:
    fields = {
        "id": uuid.uuid4(),
        "organization_id": org.id,
        "agent_id": agent.id,
        "created_by_user_id": org.owner_user.id,  # type: ignore[attr-defined]
        "is_active": True,
        "schedule_kind": "interval",
        "interval_seconds": 300,
        "prompt": "summarise the day",
        "next_fire_at": datetime.now(UTC) - timedelta(seconds=1),
    }
    fields.update(overrides)
    return AgentTrigger(**fields)


def _event(org: Organization, agent: Agent, **overrides) -> AgentTrigger:
    fields = {
        "id": uuid.uuid4(),
        "organization_id": org.id,
        "agent_id": agent.id,
        "created_by_user_id": org.owner_user.id,  # type: ignore[attr-defined]
        "is_active": True,
        "trigger_type": "event",
        "schedule_kind": "interval",
        "interval_seconds": None,
        "cron_expression": None,
        "event_source": "github",
        "event_config": {},
        "event_secret_encrypted": "sealed-ciphertext",
        "secret_key_version": 1,
        "prompt": "triage the issue",
        "next_fire_at": None,
    }
    fields.update(overrides)
    return AgentTrigger(**fields)


class TestTheConstraintsRejectABadRow:
    async def test_an_interval_below_the_floor_is_refused(self, db):
        org = await _org(db)
        agent = await _agent(db, org)
        db.add(_trigger(org, agent, interval_seconds=30))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_an_interval_trigger_must_carry_an_interval(self, db):
        org = await _org(db)
        agent = await _agent(db, org)
        db.add(_trigger(org, agent, schedule_kind="interval", interval_seconds=None))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_a_schedule_kind_outside_the_vocabulary_is_refused(self, db):
        org = await _org(db)
        agent = await _agent(db, org)
        db.add(_trigger(org, agent, schedule_kind="weekly"))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_a_trigger_type_outside_the_vocabulary_is_refused(self, db):
        org = await _org(db)
        agent = await _agent(db, org)
        db.add(_trigger(org, agent, trigger_type="weekly"))
        with pytest.raises(IntegrityError):
            await db.flush()


class TestTheEventShapeRejectsABadRow:
    async def test_a_valid_event_trigger_is_accepted(self, db):
        org = await _org(db)
        agent = await _agent(db, org)
        db.add(_event(org, agent))
        await db.flush()  # the shape CHECK accepts a well-formed event trigger

    async def test_an_event_trigger_with_a_next_fire_is_refused(self, db):
        """An event is never due on the clock; a next fire is a schedule's field."""
        org = await _org(db)
        agent = await _agent(db, org)
        db.add(_event(org, agent, next_fire_at=datetime.now(UTC)))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_an_event_trigger_without_a_sealed_secret_is_refused(self, db):
        """Without a secret there is nothing to verify a delivery against."""
        org = await _org(db)
        agent = await _agent(db, org)
        db.add(_event(org, agent, event_secret_encrypted=None, secret_key_version=None))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_an_event_trigger_carrying_an_interval_is_refused(self, db):
        org = await _org(db)
        agent = await _agent(db, org)
        db.add(_event(org, agent, interval_seconds=300))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_an_event_source_outside_the_vocabulary_is_refused(self, db):
        org = await _org(db)
        agent = await _agent(db, org)
        db.add(_event(org, agent, event_source="gitlab"))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_every_shipped_event_source_is_in_the_vocabulary(self, db):
        """The CHECK's list and the EventSource enum drift apart exactly once -
        when a source is added to the code and not the constraint - so every
        shipped value is written through it here."""
        org = await _org(db)
        agent = await _agent(db, org)
        for source in ("github", "email", "linkedin", "webhook"):
            db.add(_event(org, agent, event_source=source))
        await db.flush()


class TestTheClaimReturnsTheRightRows:
    async def test_only_the_due_active_attributable_triggers_are_claimed(self, db):
        org = await _org(db)
        agent = await _agent(db, org)
        due = _trigger(org, agent)
        not_yet = _trigger(org, agent, next_fire_at=datetime.now(UTC) + timedelta(hours=1))
        paused = _trigger(org, agent, is_active=False)
        orphaned = _trigger(org, agent, created_by_user_id=None)
        db.add_all([due, not_yet, paused, orphaned])
        await db.flush()

        claimed = await agent_trigger_repo.claim_due(db, now=datetime.now(UTC))

        assert [t.id for t in claimed] == [due.id]

    async def test_a_trigger_whose_last_run_is_unfinished_is_skipped(self, db):
        org = await _org(db)
        agent = await _agent(db, org)
        running = AgentRun(
            id=uuid.uuid4(),
            organization_id=org.id,
            agent_id=agent.id,
            status=RunStatus.RUNNING.value,
        )
        db.add(running)
        await db.flush()
        blocked = _trigger(org, agent, last_run_id=running.id)
        db.add(blocked)
        await db.flush()

        assert await agent_trigger_repo.claim_due(db, now=datetime.now(UTC)) == []

        running.status = RunStatus.COMPLETED.value
        await db.flush()
        claimed = await agent_trigger_repo.claim_due(db, now=datetime.now(UTC))
        assert [t.id for t in claimed] == [blocked.id]


class TestTwoHeartbeatsDoNotDoubleFire:
    async def test_a_row_one_heartbeat_locked_is_skipped_by_the_next(self, db, engine):
        """The whole no-double-fire guarantee: `FOR UPDATE SKIP LOCKED` means a
        second heartbeat claiming at the same instant takes none of the rows the
        first still holds, so one due trigger fires once even when a tick outruns
        its window and overlaps the next."""
        org = await _org(db)
        agent = await _agent(db, org)
        db.add(_trigger(org, agent))
        # Committed, so a second connection can see it at all.
        await db.commit()

        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as first:
            locked = await agent_trigger_repo.claim_due(first, now=datetime.now(UTC))
            assert len(locked) == 1  # the first heartbeat holds the row's lock

            async with factory() as second:
                also = await agent_trigger_repo.claim_due(second, now=datetime.now(UTC))
            assert also == []  # the second heartbeat is handed nothing, not a duplicate


class TestACreatedTriggerSerializes:
    async def test_a_created_trigger_survives_response_serialization(self, db):
        """Creating a trigger opens its run-log conversation, and that flush fires
        the row's `onupdate` for `updated_at`, expiring it on the instance. The
        route then serializes the row to `TriggerRead`, reading every attribute in
        a sync context - so without a final refresh the expired `updated_at` lazy
        -loads into a `MissingGreenlet` and the create is a 500.

        A mocked-service API test cannot see this: it never serializes a live row.
        This drives the real service against a real session and then serializes,
        which is exactly the path that failed. It reproduces the 500 without the
        fix and passes with it.
        """
        org = await _org(db)
        agent = await _agent(db, org)
        ctx = AuthContext(
            user_id=org.owner_user.id,  # type: ignore[attr-defined]
            organization_id=org.id,
            role=OrgRoleName.OWNER.value,
        )
        trigger = await AgentTriggerService(db).create(
            ctx, agent.id, TriggerCreate(prompt="summarise", interval_seconds=900)
        )
        # The line that 500s without the refresh: Pydantic reads updated_at.
        read = TriggerRead.model_validate(trigger)
        assert read.updated_at is not None
        # And the eager run-log conversation is what made updated_at stale.
        assert read.conversation_id is not None
