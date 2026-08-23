"""Tests for the trigger repository - the table behind "run this agent on a schedule".

A repository's behaviour *is* the statement it builds, so these read the
statement back rather than counting calls. The claim query is the one that
matters most: a dropped `organization_id` scope on a read is a cross-tenant leak,
and a claim that forgot its `FOR UPDATE SKIP LOCKED` or its terminal-status join
is a double-fire no "the repository was called" assertion would notice. The real
locking and the CHECK constraints are proven against a live database in
`tests/integration/test_agent_trigger_schema.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.db.models.agent_run import RunStatus
from app.db.models.agent_trigger import AgentTrigger
from app.repositories import agent_trigger_repo

pytestmark = pytest.mark.anyio


class _RecordingSession:
    """An `AsyncSession` stand-in that keeps the statements it was given."""

    def __init__(self, *results: object) -> None:
        self._results = list(results)
        self.statements: list[object] = []
        self.added: list[object] = []
        self.deleted: list[object] = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self._results.pop(0)

    def add(self, instance) -> None:
        self.added.append(instance)

    async def delete(self, instance) -> None:
        self.deleted.append(instance)

    async def flush(self) -> None:
        pass

    async def refresh(self, instance) -> None:
        pass


def _filters(session: _RecordingSession) -> dict[str, object]:
    return session.statements[-1].compile(dialect=postgresql.dialect()).params


def _sql(session: _RecordingSession) -> str:
    return str(session.statements[-1].compile(dialect=postgresql.dialect())).lower()


def _scalar(value: object):
    return MagicMock(scalar_one_or_none=MagicMock(return_value=value))


def _scalars(values: list[object]):
    return MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=values))))


def _scalars_first(value: object):
    return MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=value))))


def _count(total: int):
    return MagicMock(scalar_one=MagicMock(return_value=total))


def _rows(values: list[object]):
    return MagicMock(all=MagicMock(return_value=values))


class TestReading:
    async def test_one_trigger_is_read_inside_its_organization(self):
        trigger_id, organization_id = uuid.uuid4(), uuid.uuid4()
        session = _RecordingSession(_scalar(None))
        await agent_trigger_repo.get(session, trigger_id, organization_id=organization_id)
        assert set(_filters(session).values()) >= {trigger_id, organization_id}

    async def test_the_worker_reads_a_trigger_by_id_alone(self):
        """A fired flow has an id and no tenant; the organization is read off the row."""
        trigger_id = uuid.uuid4()
        session = _RecordingSession(_scalar(None))
        await agent_trigger_repo.get_by_id(session, trigger_id)
        assert set(_filters(session).values()) == {trigger_id}

    async def test_a_run_log_conversation_maps_back_to_its_trigger(self):
        """How a conversation read learns the thread is a trigger's run-log. Filtered
        on the conversation alone; the caller scopes the agent it points at to the
        conversation's own organization rather than trusting this across tenants."""
        conversation_id = uuid.uuid4()
        session = _RecordingSession(_scalars_first(None))
        await agent_trigger_repo.get_by_conversation_id(session, conversation_id)
        assert set(_filters(session).values()) == {conversation_id}

    async def test_the_connection_sweep_reads_only_that_accounts_rows_in_the_org(self):
        """`list_for_connection` feeds the pre-delete hook sweep; without the
        organization filter it would hand the sweep another tenant's triggers to
        deregister with this tenant's context."""
        connection_id, organization_id = uuid.uuid4(), uuid.uuid4()
        session = _RecordingSession(_scalars([]))
        await agent_trigger_repo.list_for_connection(
            session, connection_id=connection_id, organization_id=organization_id
        )
        params = _filters(session)
        assert connection_id in params.values()
        assert organization_id in params.values()

    async def test_a_listing_is_scoped_to_the_agent_and_its_organization(self):
        agent_id, organization_id = uuid.uuid4(), uuid.uuid4()
        session = _RecordingSession(_scalars([]))
        await agent_trigger_repo.list_for_agent(
            session, agent_id=agent_id, organization_id=organization_id
        )
        assert set(_filters(session).values()) >= {agent_id, organization_id}

    async def test_the_org_listing_applies_the_agent_visibility_predicate(self):
        """The org-wide read joins the agent for its name and, unless the role sees
        all, restricts to the same owned-or-org-visible-or-shared predicate the
        agent listing uses - never the shared ids alone, which would under-include
        an org-visible agent's triggers."""
        organization_id, user_id = uuid.uuid4(), uuid.uuid4()
        shared_ids = [uuid.uuid4(), uuid.uuid4()]
        session = _RecordingSession(_count(0), _rows([]))
        await agent_trigger_repo.list_for_organization(
            session,
            organization_id=organization_id,
            user_id=user_id,
            see_all=False,
            shared_ids=shared_ids,
        )
        sql = _sql(session)  # the last statement is the rows query, not the count
        assert "join agents" in sql
        assert "order by agent_triggers.created_at desc" in sql
        # The predicate is owned OR org-visible OR shared - all three legs present.
        assert "agents.owner_user_id" in sql
        assert "agents.visibility" in sql
        assert "agent_triggers.agent_id in" in sql
        flat: set[object] = set()
        for value in _filters(session).values():
            flat.update(value if isinstance(value, list) else [value])
        assert {organization_id, user_id, *shared_ids} <= flat

    async def test_the_org_listing_with_see_all_applies_no_visibility_predicate(self):
        """`see_all` is the service saying the role reaches every agent.

        The whole agent row is selected (the service resolves `can_manage` off it),
        so `agents.owner_user_id` appears as a projected column - what must be absent
        is the *predicate* on it, `owner_user_id =`, and the shared-id `IN` leg.
        """
        session = _RecordingSession(_count(0), _rows([]))
        await agent_trigger_repo.list_for_organization(
            session, organization_id=uuid.uuid4(), user_id=uuid.uuid4(), see_all=True, shared_ids=[]
        )
        sql = _sql(session)
        assert "owner_user_id =" not in sql
        assert "agent_triggers.agent_id in" not in sql

    async def test_the_org_listing_without_shared_ids_still_reads_owned_and_org_visible(self):
        """An empty shared set is not "nothing": the caller still sees agents they
        own or that are org-visible, so the predicate stays and the IN leg is a
        constant false rather than an empty IN."""
        session = _RecordingSession(_count(0), _rows([]))
        await agent_trigger_repo.list_for_organization(
            session,
            organization_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            see_all=False,
            shared_ids=[],
        )
        sql = _sql(session)
        assert "agents.owner_user_id" in sql
        assert "agent_triggers.agent_id in" not in sql

    async def test_the_org_listing_returns_the_rows_and_the_total(self):
        trigger = MagicMock()
        session = _RecordingSession(_count(1), _rows([(trigger, "Nightly")]))
        rows, total = await agent_trigger_repo.list_for_organization(
            session, organization_id=uuid.uuid4(), user_id=uuid.uuid4(), see_all=True, shared_ids=[]
        )
        assert total == 1
        assert rows == [(trigger, "Nightly")]


class TestWriting:
    async def test_create_builds_the_row_from_its_arguments(self):
        session = _RecordingSession()
        organization_id, agent_id, creator = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        now = datetime(2026, 1, 1, tzinfo=UTC)
        trigger = await agent_trigger_repo.create(
            session,
            organization_id=organization_id,
            agent_id=agent_id,
            created_by_user_id=creator,
            prompt="summarise",
            trigger_type="schedule",
            schedule_kind="interval",
            interval_seconds=300,
            cron_expression=None,
            event_source=None,
            event_config={},
            event_secret_encrypted=None,
            secret_key_version=None,
            environment_id=None,
            next_fire_at=now,
            name="Nightly",
        )
        assert session.added == [trigger]
        assert trigger.name == "Nightly"
        assert (trigger.organization_id, trigger.agent_id, trigger.interval_seconds) == (
            organization_id,
            agent_id,
            300,
        )

    async def test_update_applies_only_the_fields_it_is_given(self):
        session = _RecordingSession()
        trigger = MagicMock()
        await agent_trigger_repo.update(session, trigger=trigger, update_data={"is_active": False})
        assert trigger.is_active is False

    async def test_update_with_nothing_to_change_is_a_no_op(self):
        """The service can send an empty change set (all fields unset); the row
        is flushed unchanged rather than the loop assuming at least one field."""
        session = _RecordingSession()
        trigger = AgentTrigger(schedule_kind="interval")
        returned = await agent_trigger_repo.update(session, trigger=trigger, update_data={})
        assert returned is trigger

    async def test_delete_removes_the_row(self):
        session = _RecordingSession()
        trigger = AgentTrigger()
        await agent_trigger_repo.delete(session, trigger)
        assert session.deleted == [trigger]


class TestClaiming:
    async def test_the_claim_is_due_active_and_locked(self):
        """The whole no-double-fire and no-overlap guard lives in this statement."""
        now = datetime(2026, 6, 1, tzinfo=UTC)
        session = _RecordingSession(_scalars([]))
        await agent_trigger_repo.claim_due(session, now=now)

        sql = _sql(session)
        # The lock that keeps two heartbeats off one trigger, and only the trigger.
        assert "for update of agent_triggers skip locked" in sql
        # The no-overlap join: a fire is skipped while its previous run is unfinished.
        assert "left outer join agent_runs" in sql
        # The reconcile that closes the unlinked-run window: a parked top-level run
        # in the trigger's own conversation blocks a claim even when `last_run_id`
        # was never stamped against it (a worker that died before linking it).
        assert "not (exists" in sql
        assert "parent_run_id is null" in sql
        assert now in _filters(session).values()

    async def test_a_crashed_runs_durable_running_row_does_not_wedge_the_schedule(self):
        """The conversation reconcile blocks on `awaiting_approval` alone. A run's
        row is committed `running` before its model is called (#12), so a worker
        that dies mid-run leaves it `running` for ever - a status with no
        resolver. Blocking on it would skip the trigger on every tick for good;
        the scheduled fire's liveness is the lease, not the run row. A parked
        row keeps the block: the person its approval waits on can settle it."""
        session = _RecordingSession(_scalars([]))
        await agent_trigger_repo.claim_due(session, now=datetime(2026, 6, 1, tzinfo=UTC))

        sql = _sql(session)
        exists_clause = sql.split("not (exists", 1)[1].split("))", 1)[0]
        assert "status = " in exists_clause
        assert "status in" not in exists_clause
        assert RunStatus.AWAITING_APPROVAL.value in _filters(session).values()

    async def test_a_claim_returns_the_rows_it_locked(self):
        rows = [MagicMock(), MagicMock()]
        session = _RecordingSession(_scalars(rows))
        claimed = await agent_trigger_repo.claim_due(session, now=datetime(2026, 6, 1, tzinfo=UTC))
        assert claimed == rows

    async def test_a_renewal_moves_only_its_own_ticket_and_reports_a_miss(self):
        """The renewal is the same conditional UPDATE as the clear - a renewer
        racing a heartbeat that already re-claimed must lose, and the `False` it
        answers is what stops the loop touching a marker no longer its own."""
        claimed_at = datetime(2026, 6, 1, tzinfo=UTC)
        renewed_at = datetime(2026, 6, 1, 0, 20, tzinfo=UTC)
        trigger_id = uuid.uuid4()
        session = _RecordingSession(MagicMock(rowcount=1))
        renewed = await agent_trigger_repo.renew_fire_marker(
            session, trigger_id=trigger_id, claimed_at=claimed_at, renewed_at=renewed_at
        )
        assert renewed is True
        sql = _sql(session)
        assert "update agent_triggers set fire_in_flight_since" in sql
        assert "agent_triggers.fire_in_flight_since = " in sql
        params = _filters(session)
        assert claimed_at in params.values()
        assert renewed_at in params.values()

        missed = _RecordingSession(MagicMock(rowcount=0))
        assert (
            await agent_trigger_repo.renew_fire_marker(
                missed, trigger_id=trigger_id, claimed_at=claimed_at, renewed_at=renewed_at
            )
            is False
        )

    async def test_the_marker_clear_is_conditioned_on_its_own_ticket(self):
        """The clear is one UPDATE whose WHERE re-checks the marker against the
        committed row - never a read-compare-assign on session state, which a fire
        that outran the lease would judge against a value cached before the
        re-claim, clearing the newer claim's marker and reopening the trigger."""
        claimed_at = datetime(2026, 6, 1, tzinfo=UTC)
        trigger_id = uuid.uuid4()
        session = _RecordingSession(MagicMock())
        await agent_trigger_repo.clear_fire_marker(
            session, trigger_id=trigger_id, claimed_at=claimed_at
        )

        sql = _sql(session)
        assert "update agent_triggers set fire_in_flight_since" in sql
        assert "agent_triggers.fire_in_flight_since = " in sql
        params = _filters(session)
        assert trigger_id in params.values()
        assert claimed_at in params.values()


class TestListingTriggersForAPolledSource:
    """A poll names a mailbox, not a trigger, so one read can match several.

    A webhook delivery names its trigger in the URL. A polled one does not, so the
    poller asks which of the organization's live triggers watch that source -
    "any message" and "marked important" on one account is the shape the presets
    invite.
    """

    async def test_it_asks_for_this_organizations_live_event_triggers_on_one_source(self):
        organization_id = uuid.uuid4()
        session = _RecordingSession(_scalars([]))

        await agent_trigger_repo.list_active_for_event_source(
            session, organization_id=organization_id, event_source="gmail"
        )

        assert set(_filters(session).values()) >= {organization_id, "gmail", "event"}
        assert "is_active" in _sql(session)
