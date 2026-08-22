"""What the agent_triggers schema guarantees, against a real database.

The unit tests read the statements back; these run them. Three things a mock
cannot tell you: that the CHECK constraints reject a bad row, that the claim
returns the due, active triggers - orphans included, so they can be disabled -
and - the one the whole no-double-fire design rests on - that a second heartbeat
claiming at the same instant takes none of the rows the first one locked.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.agent_trigger import AgentTrigger, EventSource
from app.db.models.conversation import Conversation
from app.db.models.mcp_connection import McpConnection
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import agent_trigger_repo
from app.repositories.conversation import create_conversation
from app.schemas.agent_trigger import TriggerCreate, TriggerRead, TriggerUpdate
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
    # Published, because a trigger create refuses an agent with no runnable
    # version - the fixture models the agent a routine is actually made on.
    version = AgentVersion(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        version=1,
        spec={"name": agent.name},
    )
    db.add(version)
    await db.flush()
    agent.current_version_id = version.id
    await db.flush()
    return agent


async def _member(db, org: Organization) -> User:
    """A second member of `org`, distinct from its owner - so deleting them tests
    the trigger's SET NULL without tripping the org's RESTRICT on its creator."""
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role="member")
    )
    await db.flush()
    return user


async def _org_connection(db, org: Organization) -> McpConnection:
    connection = McpConnection(
        id=uuid.uuid4(),
        scope="org",
        organization_id=org.id,
        name=f"conn-{uuid.uuid4().hex[:8]}",
        url="https://mcp.example.com/sse",
        secret_key_version=1,
    )
    db.add(connection)
    await db.flush()
    return connection


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

    async def test_a_registered_hook_without_a_connection_is_refused(self, db):
        """ck_trigger_registered_hook_has_connection: a provider webhook id and no
        connection is a hook a delete could never deregister - the account whose
        token registered it is exactly what `delete_webhook` needs."""
        org = await _org(db)
        agent = await _agent(db, org)
        db.add(_trigger(org, agent, provider_webhook_id="12345678", connection_id=None))
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

    async def test_a_posted_event_trigger_without_a_sealed_secret_is_refused(self, db):
        """Without a secret there is nothing to verify a delivery against."""
        org = await _org(db)
        agent = await _agent(db, org)
        db.add(_event(org, agent, event_secret_encrypted=None, secret_key_version=None))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_a_polled_event_trigger_carrying_a_secret_is_refused(self, db):
        """The other direction, and the one that shipped broken.

        Nothing POSTs to a polled source, so a secret on such a row is a
        credential nobody can spend - and the create path minted one anyway,
        answering with a webhook URL and a reveal-once secret for a door that
        refuses a delivery naming `gmail`. The schema forbids the shape now, so
        the mistake cannot be made twice (#1068).
        """
        org = await _org(db)
        agent = await _agent(db, org)
        db.add(_event(org, agent, event_source="gmail"))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_a_polled_event_trigger_with_no_secret_is_accepted(self, db):
        org = await _org(db)
        agent = await _agent(db, org)
        db.add(
            _event(
                org,
                agent,
                event_source="gmail",
                event_secret_encrypted=None,
                secret_key_version=None,
            )
        )
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

    async def test_the_removed_linkedin_source_is_refused(self, db):
        """`linkedin` left the vocabulary with the source's removal; a row
        claiming it would be one no matcher or renderer can ever serve."""
        org = await _org(db)
        agent = await _agent(db, org)
        db.add(_event(org, agent, event_source="linkedin"))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_every_shipped_event_source_is_in_the_vocabulary(self, db):
        """The CHECK's list and the EventSource enum drift apart exactly once -
        when a source is added to the code and not the constraint - so every
        shipped value is written through it here.

        Read off the enum rather than repeated as a literal, which is what let the
        two disagree in the first place: a source renamed in the code left this
        test asserting the old vocabulary and passing (#1068).
        """
        org = await _org(db)
        agent = await _agent(db, org)
        for source in tuple(member.value for member in EventSource):
            # A polled source carries no secret and a posted one must - the shape
            # constraint's other half, so the row has to be built per source
            # rather than from one template.
            polled = source == EventSource.GMAIL.value
            db.add(
                _event(
                    org,
                    agent,
                    event_source=source,
                    event_secret_encrypted=None if polled else "sealed",
                    secret_key_version=None if polled else 1,
                )
            )
        await db.flush()


class TestTheClaimReturnsTheRightRows:
    async def test_the_due_active_triggers_are_claimed_orphans_included(self, db):
        """Due, active, and past its next fire is claimed; not-yet and paused are
        not. An orphaned schedule (null creator) *is* claimed now - not because it
        can fire, but so `claim_and_advance` can disable it rather than leave it
        filtered out of the sweep for ever."""
        org = await _org(db)
        agent = await _agent(db, org)
        due = _trigger(org, agent)
        not_yet = _trigger(org, agent, next_fire_at=datetime.now(UTC) + timedelta(hours=1))
        paused = _trigger(org, agent, is_active=False)
        orphaned = _trigger(org, agent, created_by_user_id=None)
        db.add_all([due, not_yet, paused, orphaned])
        await db.flush()

        claimed = await agent_trigger_repo.claim_due(db, now=datetime.now(UTC))

        assert {t.id for t in claimed} == {due.id, orphaned.id}

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

    async def test_a_trigger_with_a_fire_in_flight_marker_is_skipped_until_the_lease(self, db):
        """The claim sets fire_in_flight_since, so a run slower than its interval is
        not fired on top of itself - the guard `last_run_id` cannot be, since it is
        only written when the run returns. Once the marker is older than the lease - a
        child that died without clearing it - the schedule is freed again."""
        org = await _org(db)
        agent = await _agent(db, org)
        now = datetime.now(UTC)
        in_flight = _trigger(
            org, agent, next_fire_at=now - timedelta(seconds=1), fire_in_flight_since=now
        )
        db.add(in_flight)
        await db.flush()

        assert await agent_trigger_repo.claim_due(db, now=now) == []

        past_lease = now + timedelta(hours=1, minutes=1)
        claimed = await agent_trigger_repo.claim_due(db, now=past_lease)
        assert [t.id for t in claimed] == [in_flight.id]


class TestAnUnlinkedInFlightRunBlocksAReclaim:
    async def test_a_parked_run_never_linked_holds_the_schedule_past_the_lease(self, db):
        """#589: a worker that dies after `_run` commits an `awaiting_approval` row but
        before `fire` stamps `last_run_id` leaves a durable parked run the schedule
        must wait behind - yet `last_run_id` still names the previous terminal run.
        Once the marker lapses the `last_run_id` join alone would reclaim the trigger
        and fire over the pending approval; the conversation reconcile catches the
        unlinked in-flight run and holds it back until the run settles."""
        org = await _org(db)
        agent = await _agent(db, org)
        convo = Conversation(id=uuid.uuid4(), organization_id=org.id, title="run log")
        db.add(convo)
        await db.flush()
        now = datetime.now(UTC)
        # The previous fire: terminal and linked. On its own this lets the claim through.
        previous = AgentRun(
            id=uuid.uuid4(),
            organization_id=org.id,
            agent_id=agent.id,
            conversation_id=convo.id,
            status=RunStatus.COMPLETED.value,
        )
        db.add(previous)
        await db.flush()
        # The parked run a crash left unlinked, with a lapsed marker so nothing but the
        # conversation reconcile can keep the trigger out of the claim.
        parked = AgentRun(
            id=uuid.uuid4(),
            organization_id=org.id,
            agent_id=agent.id,
            conversation_id=convo.id,
            status=RunStatus.AWAITING_APPROVAL.value,
        )
        db.add(parked)
        trigger = _trigger(
            org,
            agent,
            conversation_id=convo.id,
            last_run_id=previous.id,
            next_fire_at=now - timedelta(seconds=1),
            fire_in_flight_since=now - timedelta(hours=2),
        )
        db.add(trigger)
        await db.flush()

        assert await agent_trigger_repo.claim_due(db, now=now) == []

        # Once the parked run settles, the schedule is free to fire again.
        parked.status = RunStatus.COMPLETED.value
        await db.flush()
        claimed = await agent_trigger_repo.claim_due(db, now=now)
        assert [t.id for t in claimed] == [trigger.id]

    async def test_a_delegated_child_in_flight_does_not_block_the_claim(self, db):
        """The reconcile is top-level only: a delegated child shares its parent's
        conversation but is not the fire, so a running delegate under a settled parent
        must not hold the schedule back."""
        org = await _org(db)
        agent = await _agent(db, org)
        convo = Conversation(id=uuid.uuid4(), organization_id=org.id, title="run log")
        db.add(convo)
        await db.flush()
        now = datetime.now(UTC)
        parent = AgentRun(
            id=uuid.uuid4(),
            organization_id=org.id,
            agent_id=agent.id,
            conversation_id=convo.id,
            status=RunStatus.COMPLETED.value,
        )
        db.add(parent)
        await db.flush()
        child = AgentRun(
            id=uuid.uuid4(),
            organization_id=org.id,
            agent_id=agent.id,
            conversation_id=convo.id,
            parent_run_id=parent.id,
            status=RunStatus.RUNNING.value,
        )
        db.add(child)
        trigger = _trigger(
            org,
            agent,
            conversation_id=convo.id,
            last_run_id=parent.id,
            next_fire_at=now - timedelta(seconds=1),
        )
        db.add(trigger)
        await db.flush()

        claimed = await agent_trigger_repo.claim_due(db, now=now)
        assert [t.id for t in claimed] == [trigger.id]


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


class TestClearingTheFireMarker:
    async def test_a_stale_ticket_does_not_clear_a_newer_claims_marker(self, db):
        """A fire that outran the lease ends holding the ticket its own claim
        stamped, while a heartbeat has since committed a newer one for a second
        fire still running. The clear's WHERE re-checks against the committed row,
        so the stale ticket matches nothing and the newer marker stands - and the
        matching ticket, from the fire the marker actually belongs to, clears it."""
        org = await _org(db)
        agent = await _agent(db, org)
        old_ticket = datetime.now(UTC) - timedelta(hours=2)
        newer_claim = datetime.now(UTC)
        trigger = _trigger(org, agent, fire_in_flight_since=newer_claim)
        db.add(trigger)
        await db.flush()

        await agent_trigger_repo.clear_fire_marker(db, trigger_id=trigger.id, claimed_at=old_ticket)
        await db.refresh(trigger)
        assert trigger.fire_in_flight_since == newer_claim

        await agent_trigger_repo.clear_fire_marker(
            db, trigger_id=trigger.id, claimed_at=newer_claim
        )
        await db.refresh(trigger)
        assert trigger.fire_in_flight_since is None

    async def test_a_renewal_moves_only_its_own_marker(self, db):
        """The long-run renewal is the same conditional shape: a stale ticket
        renews nothing and reports the miss, its own ticket moves the marker."""
        org = await _org(db)
        agent = await _agent(db, org)
        stale = datetime.now(UTC) - timedelta(hours=2)
        current = datetime.now(UTC) - timedelta(minutes=30)
        forward = datetime.now(UTC)
        trigger = _trigger(org, agent, fire_in_flight_since=current)
        db.add(trigger)
        await db.flush()

        missed = await agent_trigger_repo.renew_fire_marker(
            db, trigger_id=trigger.id, claimed_at=stale, renewed_at=forward
        )
        assert missed is False
        await db.refresh(trigger)
        assert trigger.fire_in_flight_since == current

        renewed = await agent_trigger_repo.renew_fire_marker(
            db, trigger_id=trigger.id, claimed_at=current, renewed_at=forward
        )
        assert renewed is True
        await db.refresh(trigger)
        assert trigger.fire_in_flight_since == forward


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


class TestTheForeignKeysBehaveAsTheRuntimeExpects:
    """The runtime rests on these `ondelete` rules, and a mock cannot prove them:
    the creator, the conversation and the connection all SET NULL so a schedule
    outlives the row it referenced, while the agent CASCADEs the trigger away with
    it. The one downstream consequence a schema statement cannot show is asserted
    too: an orphaned (null-creator) trigger is claimed and disabled, never run."""

    async def test_deleting_the_creator_nulls_the_column_and_orphan_is_disabled(self, db):
        org = await _org(db)
        agent = await _agent(db, org)
        creator = await _member(db, org)
        trigger = _trigger(org, agent, created_by_user_id=creator.id)
        db.add(trigger)
        await db.flush()

        await db.delete(creator)
        await db.flush()
        await db.refresh(trigger)
        assert trigger.created_by_user_id is None

        # Downstream: the orphan is claimed so it can be disabled, not dispatched.
        live = await AgentTriggerService(db).claim_and_advance(now=datetime.now(UTC))
        assert trigger.id not in {t.id for t in live}
        await db.refresh(trigger)
        assert trigger.is_active is False

    async def test_deleting_the_conversation_nulls_the_column(self, db):
        org = await _org(db)
        agent = await _agent(db, org)
        conversation = await create_conversation(db, organization_id=org.id, title="log")
        trigger = _trigger(org, agent, conversation_id=conversation.id)
        db.add(trigger)
        await db.flush()

        await db.delete(conversation)
        await db.flush()
        await db.refresh(trigger)
        assert trigger.conversation_id is None

    async def test_deleting_the_connection_nulls_the_column(self, db):
        org = await _org(db)
        agent = await _agent(db, org)
        connection = await _org_connection(db, org)
        trigger = _trigger(org, agent, connection_id=connection.id)
        db.add(trigger)
        await db.flush()

        await db.delete(connection)
        await db.flush()
        await db.refresh(trigger)
        assert trigger.connection_id is None

    async def test_deleting_the_agent_cascades_the_trigger(self, db):
        org = await _org(db)
        agent = await _agent(db, org)
        trigger = _trigger(org, agent)
        db.add(trigger)
        await db.flush()
        trigger_id = trigger.id

        await db.delete(agent)
        await db.flush()

        assert await agent_trigger_repo.get_by_id(db, trigger_id) is None


class TestAConnectionIsResolvedForTheCallersOrgAtCreate:
    """A caller supplies `connection_id`; the create path must resolve it against
    the caller's own organization before storing it, so one tenant cannot attach
    another's `mcp_connections.id` to its trigger (Codex P1, #537). A mock proves
    the service calls the lookup; this proves the lookup actually refuses a row
    that lives in another organization."""

    async def test_a_connection_in_another_org_cannot_be_attached(self, db):
        org_a = await _org(db)
        org_b = await _org(db)
        agent = await _agent(db, org_a)
        foreign = await _org_connection(db, org_b)
        ctx = AuthContext(
            user_id=org_a.owner_user.id,  # type: ignore[attr-defined]
            organization_id=org_a.id,
            role=OrgRoleName.OWNER.value,
        )
        with pytest.raises(NotFoundError):
            await AgentTriggerService(db).create(
                ctx,
                agent.id,
                TriggerCreate(
                    prompt="triage",
                    trigger_type="event",
                    portal_key="github",
                    preset_key="issue_opened",
                    connection_id=foreign.id,
                    target="acme/api",
                ),
            )


class TestResumingASchedule:
    async def test_a_resume_recomputes_next_fire_and_survives_the_audit(self, db):
        """Resuming a schedule recomputes its next fire - a datetime that then lands
        in the audit's JSONB `details`. That column's default `json.dumps` cannot
        encode a datetime, so the audit flush raised and the resume 500'd where a
        pause (a bool only) did not. This drives the real service and audit against a
        real session: it fails without the encoder fix and passes with it.
        """
        org = await _org(db)
        agent = await _agent(db, org)
        ctx = AuthContext(
            user_id=org.owner_user.id,  # type: ignore[attr-defined]
            organization_id=org.id,
            role=OrgRoleName.OWNER.value,
        )
        service = AgentTriggerService(db)
        trigger = await service.create(
            ctx, agent.id, TriggerCreate(prompt="summarise", interval_seconds=900)
        )
        await service.update(ctx, agent.id, trigger.id, TriggerUpdate(is_active=False))
        resumed = await service.update(ctx, agent.id, trigger.id, TriggerUpdate(is_active=True))

        assert resumed.is_active is True
        assert resumed.next_fire_at is not None
        # The serialization that 500'd on the session the failed audit flush poisoned.
        assert TriggerRead.model_validate(resumed).is_active is True
