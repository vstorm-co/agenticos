"""Tests for scheduling an agent to run itself.

The value here is almost entirely in the refusals: an agent the caller cannot
run, a cron expression that does not parse, a creator who lost access between scheduling
and firing, and a budget that must stop a fired run rather than be retried into
spending the same money again. The registry's own refusals (a missing agent, one
the caller may not run, another tenant's) are proven against the real
`resolve_access` in `tests/test_agent_registry.py`; here `service.agents.get` is
mocked, so these tests are about triggers, not about re-proving that.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.config import settings
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_run import RunStatus, RunSurface
from app.schemas.agent_trigger import TriggerCreate, TriggerRead, TriggerUpdate
from app.services.agent_trigger import (
    AgentTriggerService,
    EventFireDecision,
    _next_fire_from,
    _update_action,
)
from app.services.portals import RegisteredWebhook, WebhookRegistrationForbidden

_SIGNING_SECRET = "a-signing-secret-16-plus"

pytestmark = pytest.mark.anyio

_ORG = uuid.uuid4()
_CALLER = uuid.uuid4()


def _ctx(role: str = OrgRoleName.OWNER) -> AuthContext:
    return AuthContext(user_id=_CALLER, organization_id=_ORG, role=role)


def _named(**attributes: object) -> MagicMock:
    """A stand-in with a real `.name` (MagicMock(name=...) names the mock instead)."""
    mock = MagicMock(**{key: value for key, value in attributes.items() if key != "name"})
    mock.name = attributes["name"]
    return mock


def _agent(*, agent_id: uuid.UUID | None = None, name: str = "Nightly") -> MagicMock:
    return _named(id=agent_id or uuid.uuid4(), name=name)


def _service(agent: MagicMock | None = None) -> AgentTriggerService:
    service = AgentTriggerService(MagicMock())
    service.db.flush = AsyncMock()
    # `create` refreshes the row before returning it, so it serializes without a
    # MissingGreenlet on a live session; the mock must await.
    service.db.refresh = AsyncMock()
    # `spawn_after_commit` queues on `Session.info`, a plain dict SQLAlchemy keeps
    # per unit of work. A MagicMock would swallow the append and leave the queued
    # coroutine un-awaited.
    service.db.info = {}
    service.agents = MagicMock()
    service.agents.get = AsyncMock(return_value=agent or _agent())
    return service


async def _run_deferred(db: MagicMock) -> None:
    """Run what the session deferred, as `_managed_session` does after its commit."""
    for queue in db.info.values():
        for deferred in queue:
            await deferred.coro


def _trigger(**overrides: object) -> MagicMock:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "organization_id": _ORG,
        "agent_id": uuid.uuid4(),
        "created_by_user_id": _CALLER,
        "is_active": True,
        "environment_id": None,
        "trigger_type": "schedule",
        "schedule_kind": "interval",
        "interval_seconds": 300,
        "cron_expression": None,
        "event_source": None,
        "event_config": {},
        "event_secret_encrypted": None,
        "secret_key_version": None,
        "prompt": "summarise the day",
        "next_fire_at": datetime(2026, 1, 1, tzinfo=UTC),
        "last_fired_at": None,
        "last_run_id": None,
        "conversation_id": None,
        "connection_id": None,
        "portal_key": None,
        "delivery_mode": None,
        "provider_webhook_id": None,
        "provider_target": None,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


def _interval(
    interval_seconds: int = 300, environment_id: uuid.UUID | None = None
) -> TriggerCreate:
    return TriggerCreate(
        prompt="summarise the day",
        schedule_kind="interval",
        interval_seconds=interval_seconds,
        environment_id=environment_id,
    )


def _github_event(**overrides: object) -> TriggerCreate:
    fields: dict[str, object] = {
        "prompt": "triage the issue",
        "trigger_type": "event",
        "event_source": "github",
        "event_secret": _SIGNING_SECRET,
    }
    fields.update(overrides)
    return TriggerCreate(**fields)


def _event_trigger(**overrides: object) -> MagicMock:
    fields: dict[str, object] = {
        "trigger_type": "event",
        "event_source": "github",
        "event_config": {"actions": ["opened"]},
        "event_secret_encrypted": "sealed-ciphertext",
        "secret_key_version": 1,
        "interval_seconds": None,
        "next_fire_at": None,
    }
    fields.update(overrides)
    return _trigger(**fields)


class TestScheduleMath:
    def test_an_interval_trigger_fires_one_interval_from_now(self):
        now = datetime(2026, 1, 1, tzinfo=UTC)
        trigger = _trigger(interval_seconds=600)
        assert _next_fire_from(trigger, now=now) == now + timedelta(seconds=600)

    def test_a_cron_trigger_fires_at_its_next_matching_instant(self):
        """`0 9 * * *` from 10:00 is tomorrow at 09:00, not one interval later -
        and evaluated in UTC, the tz the row is stored and compared in."""
        now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        trigger = _trigger(schedule_kind="cron", interval_seconds=None, cron_expression="0 9 * * *")
        assert _next_fire_from(trigger, now=now) == datetime(2026, 1, 2, 9, 0, tzinfo=UTC)

    @pytest.mark.parametrize(
        ("changes", "action"),
        [
            ({"is_active": True}, "agent.trigger_resumed"),
            ({"is_active": False}, "agent.trigger_paused"),
            ({"prompt": "x"}, "agent.trigger_updated"),
        ],
    )
    def test_pause_and_resume_are_named_apart_from_an_ordinary_edit(self, changes, action):
        assert _update_action(changes) == action


class TestCreate:
    async def test_scheduling_demands_permission_to_run_the_agent(self):
        """Creating a schedule is asserting 'run this agent, repeatedly, as me'."""
        service = _service()
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
        ):
            # A conversation_id already set short-circuits the eager run-log open,
            # which its own test covers; this one is about the permission floor.
            repo.create = AsyncMock(return_value=_trigger(conversation_id=uuid.uuid4()))
            await service.create(_ctx(), uuid.uuid4(), _interval())
        assert service.agents.get.call_args.kwargs["perm"].value == "agents:run"

    async def test_a_cron_schedule_is_persisted_with_its_next_fire_computed(self):
        agent = _agent()
        service = _service(agent)
        cron = TriggerCreate(prompt="run", schedule_kind="cron", cron_expression="0 9 * * *")
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
        ):
            repo.create = AsyncMock(
                return_value=_trigger(
                    schedule_kind="cron",
                    interval_seconds=None,
                    cron_expression="0 9 * * *",
                    conversation_id=uuid.uuid4(),
                )
            )
            await service.create(_ctx(), agent.id, cron)
        assert repo.create.call_args.kwargs["cron_expression"] == "0 9 * * *"
        assert repo.create.call_args.kwargs["interval_seconds"] is None
        # The next 09:00 UTC, not an interval out - so the fire lands on the hour.
        assert repo.create.call_args.kwargs["next_fire_at"].hour == 9

    def test_an_unparsable_cron_is_a_422_at_the_schema(self):
        """The database CHECK cannot judge a crontab expression, so the schema
        parses it - a garbled one is a 422 naming the field, never a stored
        schedule that fires nothing."""
        with pytest.raises(PydanticValidationError, match="valid crontab"):
            TriggerCreate(prompt="run", schedule_kind="cron", cron_expression="not a cron")

    def test_a_preset_create_carries_no_event_fields(self):
        """The preset path names a portal and preset instead of a source and
        secret; the service fills the event_* fields from the catalog."""
        create = TriggerCreate(
            prompt="triage",
            trigger_type="event",
            portal_key="github",
            preset_key="issue_opened",
            connection_id=uuid.uuid4(),
            target="acme/api",
        )
        assert create.portal_key == "github"
        assert create.event_source is None

    def test_a_portal_without_a_preset_is_refused(self):
        with pytest.raises(PydanticValidationError, match="given together"):
            TriggerCreate(prompt="x", trigger_type="event", portal_key="github")

    def test_a_preset_alongside_a_hand_set_source_is_refused(self):
        with pytest.raises(PydanticValidationError, match="come from the preset"):
            TriggerCreate(
                prompt="x",
                trigger_type="event",
                portal_key="github",
                preset_key="issue_opened",
                event_source="github",
            )

    def test_a_preset_on_a_schedule_is_refused(self):
        with pytest.raises(PydanticValidationError, match="not valid for a schedule"):
            TriggerCreate(prompt="x", portal_key="github", preset_key="issue_opened")

    async def test_a_new_schedule_is_persisted_and_audited(self):
        agent = _agent()
        service = _service(agent)
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()) as audit,
        ):
            repo.create = AsyncMock(
                return_value=_trigger(agent_id=agent.id, conversation_id=uuid.uuid4())
            )
            await service.create(_ctx(), agent.id, _interval(interval_seconds=900))

        assert repo.create.call_args.kwargs["created_by_user_id"] == _CALLER
        assert repo.create.call_args.kwargs["interval_seconds"] == 900
        # First fire is one interval out, not immediate.
        assert repo.create.call_args.kwargs["next_fire_at"] > datetime.now(UTC)
        assert audit.call_args.kwargs["action"] == "agent.trigger_created"

    async def test_creating_a_schedule_opens_its_run_log_conversation_eagerly(self):
        """The sidebar item must be clickable before the first fire, so the
        run-log conversation is opened at create, not lazily on the first fire."""
        agent = _agent(name="Nightly")
        service = _service(agent)
        conversation = MagicMock(id=uuid.uuid4())
        trigger = _trigger(agent_id=agent.id, conversation_id=None)
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.conversation_repo") as conversations,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
        ):
            repo.create = AsyncMock(return_value=trigger)
            conversations.create_conversation = AsyncMock(return_value=conversation)
            await service.create(_ctx(), agent.id, _interval())
        conversations.create_conversation.assert_awaited_once()
        assert conversations.create_conversation.call_args.kwargs["title"] == "Nightly - scheduled"
        assert trigger.conversation_id == conversation.id

    async def test_a_schedule_can_name_the_environment_it_fires(self):
        agent = _agent()
        service = _service(agent)
        environment = MagicMock(agent_id=agent.id)
        environment.id = uuid.uuid4()
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.agent_environment_repo") as environments,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
        ):
            repo.create = AsyncMock(return_value=_trigger(conversation_id=uuid.uuid4()))
            environments.get = AsyncMock(return_value=environment)
            await service.create(_ctx(), agent.id, _interval(environment_id=environment.id))
        assert repo.create.call_args.kwargs["environment_id"] == environment.id

    async def test_another_agents_environment_cannot_be_scheduled(self):
        agent = _agent()
        service = _service(agent)
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.agent_environment_repo") as environments,
        ):
            environments.get = AsyncMock(return_value=MagicMock(agent_id=uuid.uuid4()))
            repo.create = AsyncMock()
            with pytest.raises(NotFoundError, match="Environment"):
                await service.create(_ctx(), agent.id, _interval(environment_id=uuid.uuid4()))
            repo.create.assert_not_called()

    async def test_a_missing_environment_is_refused(self):
        agent = _agent()
        service = _service(agent)
        with (
            patch("app.services.agent_trigger.agent_environment_repo") as environments,
        ):
            environments.get = AsyncMock(return_value=None)
            with pytest.raises(NotFoundError, match="Environment"):
                await service.create(_ctx(), agent.id, _interval(environment_id=uuid.uuid4()))


def _read() -> TriggerRead:
    return TriggerRead(
        id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        is_active=True,
        trigger_type="schedule",
        schedule_kind="interval",
        interval_seconds=300,
        prompt="run",
        next_fire_at=datetime(2026, 1, 1, tzinfo=UTC),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


class TestReading:
    async def test_a_listing_is_scoped_to_the_callers_organization(self):
        agent = _agent()
        service = _service(agent)
        with patch("app.services.agent_trigger.agent_trigger_repo") as repo:
            repo.list_for_agent = AsyncMock(return_value=[])
            await service.list_for_agent(_ctx(), agent.id)
        assert repo.list_for_agent.call_args.kwargs["organization_id"] == _ORG

    async def test_seeing_the_schedules_needs_only_permission_to_see_the_agent(self):
        service = _service()
        with patch("app.services.agent_trigger.agent_trigger_repo") as repo:
            repo.list_for_agent = AsyncMock(return_value=[])
            await service.list_for_agent(_ctx(OrgRoleName.VIEWER), uuid.uuid4())
        assert service.agents.get.call_args.kwargs == {}


class TestOrgListing:
    async def test_the_org_listing_is_filtered_to_agents_the_caller_can_reach(self):
        service = _service()
        reachable = uuid.uuid4()
        with (
            patch(
                "app.services.agent_trigger.visible_resource_ids",
                new=AsyncMock(return_value=[reachable]),
            ),
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
        ):
            repo.list_for_organization = AsyncMock(return_value=([(_read(), "Nightly")], 1))
            items, total = await service.list_for_organization(_ctx())
        # The grant ids are the *shared* set, combined by the repo with the
        # owned-or-org-visible predicate - not the whole filter.
        assert repo.list_for_organization.call_args.kwargs["shared_ids"] == [reachable]
        assert repo.list_for_organization.call_args.kwargs["see_all"] is False
        assert repo.list_for_organization.call_args.kwargs["user_id"] == _CALLER
        assert total == 1
        # The row is named with its agent, which a bare trigger does not carry.
        assert items[0].agent_name == "Nightly"

    async def test_a_role_that_reaches_every_agent_asks_for_no_predicate(self):
        """`visible_resource_ids` returning None means "sees all" - `see_all` True."""
        service = _service()
        with (
            patch(
                "app.services.agent_trigger.visible_resource_ids",
                new=AsyncMock(return_value=None),
            ),
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
        ):
            repo.list_for_organization = AsyncMock(return_value=([], 0))
            await service.list_for_organization(_ctx())
        assert repo.list_for_organization.call_args.kwargs["see_all"] is True
        assert repo.list_for_organization.call_args.kwargs["shared_ids"] == []

    async def test_a_caller_with_no_grants_still_reads_owned_and_org_visible(self):
        """An empty grant set is not "nothing" - the repo predicate still shows the
        caller's own and the org-visible agents, so the listing is not
        short-circuited to empty (that under-included, disagreeing with the agent
        page)."""
        service = _service()
        with (
            patch(
                "app.services.agent_trigger.visible_resource_ids",
                new=AsyncMock(return_value=[]),
            ),
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
        ):
            repo.list_for_organization = AsyncMock(return_value=([], 0))
            await service.list_for_organization(_ctx())
        # The repo is called - not skipped - with an empty shared set and see_all
        # false, so it applies the owned-or-org-visible predicate.
        repo.list_for_organization.assert_awaited_once()
        assert repo.list_for_organization.call_args.kwargs["see_all"] is False
        assert repo.list_for_organization.call_args.kwargs["shared_ids"] == []


class TestChangingASchedule:
    async def test_a_trigger_belonging_to_another_agent_is_not_reachable(self):
        """A cross-resource escalation that stays inside one organization."""
        agent = _agent()
        service = _service(agent)
        with patch("app.services.agent_trigger.agent_trigger_repo") as repo:
            repo.get = AsyncMock(return_value=_trigger(agent_id=uuid.uuid4()))
            repo.delete = AsyncMock()
            with pytest.raises(NotFoundError):
                await service.delete(_ctx(), agent.id, uuid.uuid4())
            repo.delete.assert_not_called()

    async def test_a_trigger_from_another_organization_is_not_reachable(self):
        agent = _agent()
        service = _service(agent)
        with patch("app.services.agent_trigger.agent_trigger_repo") as repo:
            repo.get = AsyncMock(return_value=None)
            with pytest.raises(NotFoundError):
                await service.delete(_ctx(), agent.id, uuid.uuid4())
        assert repo.get.call_args.kwargs["organization_id"] == _ORG

    async def test_changing_a_schedule_demands_permission_to_run_the_agent(self):
        agent = _agent()
        service = _service(agent)
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
        ):
            repo.get = AsyncMock(return_value=_trigger(agent_id=agent.id))
            repo.delete = AsyncMock()
            await service.delete(_ctx(), agent.id, repo.get.return_value.id)
        assert service.agents.get.call_args.kwargs["perm"].value == "agents:run"

    async def test_removing_a_schedule_is_recorded(self):
        agent = _agent()
        service = _service(agent)
        trigger = _trigger(agent_id=agent.id)
        audit = AsyncMock()
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.record_audit", new=audit),
        ):
            repo.get = AsyncMock(return_value=trigger)
            repo.delete = AsyncMock()
            await service.delete(_ctx(), agent.id, trigger.id)
        repo.delete.assert_awaited_once_with(service.db, trigger)
        assert audit.call_args.kwargs["action"] == "agent.trigger_deleted"

    @pytest.mark.parametrize(
        ("is_active", "action"),
        [(False, "agent.trigger_paused"), (True, "agent.trigger_resumed")],
    )
    async def test_pausing_and_resuming_are_recorded_as_different_acts(self, is_active, action):
        agent = _agent()
        service = _service(agent)
        trigger = _trigger(agent_id=agent.id)
        audit = AsyncMock()
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.record_audit", new=audit),
        ):
            repo.get = AsyncMock(return_value=trigger)
            repo.update = AsyncMock(return_value=trigger)
            await service.update(_ctx(), agent.id, trigger.id, TriggerUpdate(is_active=is_active))
        changes = repo.update.call_args.kwargs["update_data"]
        assert changes["is_active"] is is_active
        # Resuming a schedule advances its next fire from now; pausing leaves it.
        assert ("next_fire_at" in changes) is is_active
        assert audit.call_args.kwargs["action"] == action

    async def test_retiming_validates_a_named_environment(self):
        agent = _agent()
        service = _service(agent)
        trigger = _trigger(agent_id=agent.id)
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.agent_environment_repo") as environments,
        ):
            repo.get = AsyncMock(return_value=trigger)
            environments.get = AsyncMock(return_value=MagicMock(agent_id=uuid.uuid4()))
            with pytest.raises(NotFoundError, match="Environment"):
                await service.update(
                    _ctx(), agent.id, trigger.id, TriggerUpdate(environment_id=uuid.uuid4())
                )

    async def test_an_omitted_field_is_left_untouched(self):
        """`exclude_unset` - retiming must not clear the environment nobody sent."""
        agent = _agent()
        service = _service(agent)
        trigger = _trigger(agent_id=agent.id)
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.agent_environment_repo") as environments,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
        ):
            repo.get = AsyncMock(return_value=trigger)
            repo.update = AsyncMock(return_value=trigger)
            await service.update(_ctx(), agent.id, trigger.id, TriggerUpdate(interval_seconds=600))
        changes = repo.update.call_args.kwargs["update_data"]
        # The sent field, plus the recomputed next fire; nothing else.
        assert changes["interval_seconds"] == 600
        assert "next_fire_at" in changes
        assert "environment_id" not in changes
        environments.get.assert_not_called()

    async def test_retiming_an_interval_advances_the_next_fire_to_the_new_cadence(self):
        """Shrinking the interval must not wait out the old one - the next fire is
        recomputed from the *new* value, from now."""
        agent = _agent()
        service = _service(agent)
        trigger = _trigger(agent_id=agent.id, interval_seconds=86400)
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
        ):
            repo.get = AsyncMock(return_value=trigger)
            repo.update = AsyncMock(return_value=trigger)
            await service.update(_ctx(), agent.id, trigger.id, TriggerUpdate(interval_seconds=300))
        next_fire = repo.update.call_args.kwargs["update_data"]["next_fire_at"]
        # Five minutes out, not a day - computed from the new 300s.
        assert next_fire < datetime.now(UTC) + timedelta(seconds=360)


@pytest.fixture
def fired(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """The trigger ids the dispatched background fire was handed, in order.

    `run_now` queues `fire_trigger` for after the commit rather than awaiting
    `fire`, so what was fired is recorded here and not on the service. Every test
    that reaches `_run_deferred` needs this: without it the queued coroutine is the
    real handler, which opens a database session of its own.
    """
    ids: list[uuid.UUID] = []

    async def _fire(trigger_id: uuid.UUID, *, event_context: str | None = None) -> None:
        ids.append(trigger_id)

    monkeypatch.setattr("app.worker.background.trigger_fire.fire_trigger", _fire)
    return ids


class TestRunningNow:
    async def test_running_now_demands_permission_to_run_the_agent(self, fired):
        """The same floor as scheduling it - `agents:run` on the agent, per row."""
        agent = _agent()
        service = _service(agent)
        trigger = _trigger(agent_id=agent.id)
        with patch("app.services.agent_trigger.agent_trigger_repo") as repo:
            repo.get = AsyncMock(return_value=trigger)
            await service.run_now(_ctx(), agent.id, trigger.id)
            await _run_deferred(service.db)
        assert service.agents.get.call_args.kwargs["perm"].value == "agents:run"

    async def test_running_now_answers_before_the_run_it_dispatches(self, fired):
        """#658: the fire is handed over, not awaited inside the request.

        Nothing has run by the time the caller is answered; the fire starts when
        the session commits.
        """
        agent = _agent()
        service = _service(agent)
        service.fire = AsyncMock()
        trigger = _trigger(agent_id=agent.id)
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
        ):
            repo.get = AsyncMock(return_value=trigger)
            await service.run_now(_ctx(), agent.id, trigger.id)
            service.fire.assert_not_awaited()
            assert fired == []
            await _run_deferred(service.db)
        assert fired == [trigger.id]

    async def test_running_now_fires_without_rescheduling(self, fired):
        """A manual fire is one extra run, not a reschedule - next_fire_at stands."""
        agent = _agent()
        service = _service(agent)
        original_next = datetime(2026, 1, 1, tzinfo=UTC)
        trigger = _trigger(agent_id=agent.id, next_fire_at=original_next)
        with patch("app.services.agent_trigger.agent_trigger_repo") as repo:
            repo.get = AsyncMock(return_value=trigger)
            result = await service.run_now(_ctx(), agent.id, trigger.id)
            await _run_deferred(service.db)
        assert trigger.next_fire_at == original_next
        assert result is trigger

    async def test_running_now_is_audited_under_the_caller_not_the_creator(self, fired):
        """The run runs as the creator, but who pressed the button - and spent the
        money - is a separate fact, recorded under the caller."""
        agent = _agent()
        service = _service(agent)
        trigger = _trigger(agent_id=agent.id)
        audit = AsyncMock()
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.record_audit", new=audit),
        ):
            repo.get = AsyncMock(return_value=trigger)
            await service.run_now(_ctx(), agent.id, trigger.id)
            await _run_deferred(service.db)
        assert audit.call_args.kwargs["action"] == "agent.trigger_run_now"
        assert audit.call_args.kwargs["actor_user_id"] == _CALLER

    async def test_running_now_on_another_agents_trigger_is_not_reachable(self, fired):
        agent = _agent()
        service = _service(agent)
        with patch("app.services.agent_trigger.agent_trigger_repo") as repo:
            repo.get = AsyncMock(return_value=_trigger(agent_id=uuid.uuid4()))
            with pytest.raises(NotFoundError):
                await service.run_now(_ctx(), agent.id, uuid.uuid4())
            await _run_deferred(service.db)
        assert fired == []


class TestClaiming:
    async def test_claiming_advances_each_trigger_so_no_later_tick_re_fires_it(self):
        service = _service()
        now = datetime(2026, 6, 1, tzinfo=UTC)
        trigger = _trigger(interval_seconds=300)
        with patch("app.services.agent_trigger.agent_trigger_repo") as repo:
            repo.claim_due = AsyncMock(return_value=[trigger])
            claimed = await service.claim_and_advance(now=now)
        assert trigger.next_fire_at == now + timedelta(seconds=300)
        assert trigger.last_fired_at == now
        service.db.flush.assert_awaited()
        assert claimed == [trigger]

    async def test_a_quiet_tick_claims_nothing_and_advances_nothing(self):
        service = _service()
        with patch("app.services.agent_trigger.agent_trigger_repo") as repo:
            repo.claim_due = AsyncMock(return_value=[])
            claimed = await service.claim_and_advance(now=datetime(2026, 6, 1, tzinfo=UTC))
        assert claimed == []


class TestFiring:
    def _patches(self):
        return (
            patch("app.services.agent_trigger.agent_trigger_repo"),
            patch("app.services.agent_trigger.member_repo"),
            patch("app.services.agent_trigger.conversation_repo"),
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
            patch("app.services.agent_runner.AgentRunnerService"),
        )

    async def test_a_deleted_trigger_does_nothing(self):
        service = _service()
        repo_p, member_p, *_ = self._patches()
        with repo_p as repo, member_p as members:
            repo.get_by_id = AsyncMock(return_value=None)
            members.get = AsyncMock()
            await service.fire(uuid.uuid4())
        members.get.assert_not_called()

    async def test_a_disabled_trigger_does_nothing(self):
        service = _service()
        repo_p, member_p, *_ = self._patches()
        with repo_p as repo, member_p as members:
            repo.get_by_id = AsyncMock(return_value=_trigger(is_active=False))
            members.get = AsyncMock()
            await service.fire(uuid.uuid4())
        members.get.assert_not_called()

    async def test_a_trigger_whose_creator_left_the_org_is_disabled_not_run(self):
        service = _service()
        trigger = _trigger()
        repo_p, member_p, conv_p, _audit, runner_p = self._patches()
        with repo_p as repo, member_p as members, conv_p, runner_p as runner_cls:
            repo.get_by_id = AsyncMock(return_value=trigger)
            members.get = AsyncMock(return_value=None)
            await service.fire(trigger.id)
        assert trigger.is_active is False
        runner_cls.assert_not_called()

    async def test_a_trigger_whose_creator_column_was_cleared_is_disabled(self):
        """A user deleted outright nulls `created_by_user_id` via SET NULL."""
        service = _service()
        trigger = _trigger(created_by_user_id=None)
        repo_p, member_p, conv_p, _audit, runner_p = self._patches()
        with repo_p as repo, member_p as members, conv_p, runner_p as runner_cls:
            repo.get_by_id = AsyncMock(return_value=trigger)
            members.get = AsyncMock(return_value=None)
            await service.fire(trigger.id)
        assert trigger.is_active is False
        members.get.assert_not_called()
        runner_cls.assert_not_called()

    async def test_a_trigger_whose_grant_on_this_agent_was_revoked_is_disabled_not_retried(self):
        """The pre-check is grants-aware (`resolve_access`), not a role check. A
        creator who kept a role with `agents:run` but lost the grant on *this*
        agent is refused here, before a run, and the refusal is caught rather than
        raised into a Prefect retry."""
        service = _service()
        service.agents.get = AsyncMock(side_effect=NotFoundError(message="nope"))
        trigger = _trigger()
        audit = AsyncMock()
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.member_repo") as members,
            patch("app.services.agent_trigger.record_audit", new=audit),
            patch("app.services.agent_runner.AgentRunnerService") as runner_cls,
        ):
            repo.get_by_id = AsyncMock(return_value=trigger)
            members.get = AsyncMock(return_value=MagicMock(role=OrgRoleName.MEMBER))
            await service.fire(trigger.id)
        assert trigger.is_active is False
        assert audit.call_args.kwargs["action"] == "agent.trigger_disabled"
        assert audit.call_args.kwargs["actor_user_id"] is None
        assert audit.call_args.kwargs["details"]["reason"] == "creator_cannot_run_agent"
        runner_cls.assert_not_called()

    async def test_a_fired_run_runs_as_the_creator_and_is_stamped_schedule(self):
        agent = _agent()
        service = _service(agent)
        trigger = _trigger(agent_id=agent.id, conversation_id=None)
        run = MagicMock(id=uuid.uuid4(), status=RunStatus.COMPLETED.value)
        conversation = MagicMock(id=uuid.uuid4())
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.member_repo") as members,
            patch("app.services.agent_trigger.conversation_repo") as conversations,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
            patch("app.services.agent_runner.AgentRunnerService") as runner_cls,
        ):
            repo.get_by_id = AsyncMock(return_value=trigger)
            members.get = AsyncMock(return_value=MagicMock(role=OrgRoleName.OWNER))
            conversations.create_conversation = AsyncMock(return_value=conversation)
            runner = runner_cls.return_value
            runner.execute = AsyncMock(return_value=("done", run))
            await service.fire(trigger.id)

        run_ctx = runner.execute.call_args.args[0]
        assert run_ctx.user_id == _CALLER
        assert runner.execute.call_args.kwargs["surface"] is RunSurface.SCHEDULE
        assert runner.execute.call_args.kwargs["conversation_id"] == conversation.id
        assert trigger.last_run_id == run.id

    async def test_the_run_log_conversation_is_opened_once_and_reused(self):
        agent = _agent()
        service = _service(agent)
        existing = uuid.uuid4()
        trigger = _trigger(agent_id=agent.id, conversation_id=existing)
        run = MagicMock(id=uuid.uuid4(), status=RunStatus.COMPLETED.value)
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.member_repo") as members,
            patch("app.services.agent_trigger.conversation_repo") as conversations,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
            patch("app.services.agent_runner.AgentRunnerService") as runner_cls,
        ):
            repo.get_by_id = AsyncMock(return_value=trigger)
            members.get = AsyncMock(return_value=MagicMock(role=OrgRoleName.OWNER))
            conversations.create_conversation = AsyncMock()
            runner = runner_cls.return_value
            runner.execute = AsyncMock(return_value=("done", run))
            await service.fire(trigger.id)

        conversations.create_conversation.assert_not_called()
        assert runner.execute.call_args.kwargs["conversation_id"] == existing

    async def test_a_fired_run_over_budget_is_recorded_and_not_retried(self):
        """The issue's own line: the run ends BUDGET_EXCEEDED and fire returns
        normally, so Prefect does not retry it into spending more."""
        agent = _agent()
        service = _service(agent)
        trigger = _trigger(agent_id=agent.id, conversation_id=uuid.uuid4())
        run = MagicMock(id=uuid.uuid4(), status=RunStatus.BUDGET_EXCEEDED.value)
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.member_repo") as members,
            patch("app.services.agent_trigger.conversation_repo"),
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
            patch("app.services.agent_runner.AgentRunnerService") as runner_cls,
        ):
            repo.get_by_id = AsyncMock(return_value=trigger)
            members.get = AsyncMock(return_value=MagicMock(role=OrgRoleName.OWNER))
            runner = runner_cls.return_value
            runner.execute = AsyncMock(return_value=("", run))
            await service.fire(trigger.id)  # must not raise
        assert trigger.last_run_id == run.id
        assert trigger.is_active is True

    async def test_access_withdrawn_mid_run_disables_rather_than_retries(self):
        agent = _agent()
        service = _service(agent)
        trigger = _trigger(agent_id=agent.id, conversation_id=uuid.uuid4())
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.member_repo") as members,
            patch("app.services.agent_trigger.conversation_repo"),
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
            patch("app.services.agent_runner.AgentRunnerService") as runner_cls,
        ):
            repo.get_by_id = AsyncMock(return_value=trigger)
            members.get = AsyncMock(return_value=MagicMock(role=OrgRoleName.OWNER))
            runner = runner_cls.return_value
            runner.execute = AsyncMock(side_effect=AuthorizationError(message="withdrawn"))
            await service.fire(trigger.id)  # must not raise
        assert trigger.is_active is False


class TestCreatingAnEventTrigger:
    async def test_an_event_trigger_seals_its_secret_and_has_no_next_fire(self):
        agent = _agent()
        service = _service(agent)
        sealed = MagicMock(ciphertext="CIPHERTEXT", key_version=3)
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.seal", return_value=sealed) as seal_fn,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
        ):
            repo.create = AsyncMock(
                return_value=_event_trigger(agent_id=agent.id, conversation_id=uuid.uuid4())
            )
            await service.create(_ctx(), agent.id, _github_event())
        # The plaintext secret is sealed; only the ciphertext travels onward.
        assert seal_fn.call_args.args[0] == _SIGNING_SECRET
        assert repo.create.call_args.kwargs["event_secret_encrypted"] == "CIPHERTEXT"
        assert repo.create.call_args.kwargs["secret_key_version"] == 3
        assert repo.create.call_args.kwargs["trigger_type"] == "event"
        assert repo.create.call_args.kwargs["event_source"] == "github"
        # An event trigger is never due on the clock.
        assert repo.create.call_args.kwargs["next_fire_at"] is None

    async def test_creating_an_event_trigger_never_audits_its_secret(self):
        agent = _agent()
        service = _service(agent)
        audit = AsyncMock()
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch(
                "app.services.agent_trigger.seal",
                return_value=MagicMock(ciphertext="CT", key_version=1),
            ),
            patch("app.services.agent_trigger.record_audit", new=audit),
        ):
            repo.create = AsyncMock(
                return_value=_event_trigger(agent_id=agent.id, conversation_id=uuid.uuid4())
            )
            await service.create(_ctx(), agent.id, _github_event())
        details = audit.call_args.kwargs["details"]
        assert details["trigger_type"] == "event"
        assert details["event_source"] == "github"
        # Neither the plaintext secret nor its ciphertext reaches the trail.
        assert _SIGNING_SECRET not in str(details)
        assert "CT" not in str(details)

    async def test_creating_an_event_trigger_opens_a_triggered_run_log(self):
        agent = _agent(name="Nightly")
        service = _service(agent)
        trigger = _event_trigger(agent_id=agent.id, conversation_id=None)
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch(
                "app.services.agent_trigger.seal",
                return_value=MagicMock(ciphertext="CT", key_version=1),
            ),
            patch("app.services.agent_trigger.conversation_repo") as conversations,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
        ):
            repo.create = AsyncMock(return_value=trigger)
            conversations.create_conversation = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
            await service.create(_ctx(), agent.id, _github_event())
        # An event trigger's run log is "triggered", not "scheduled".
        assert conversations.create_conversation.call_args.kwargs["title"] == "Nightly - triggered"


class TestEventTriggerSchema:
    def test_an_event_trigger_requires_a_source(self):
        with pytest.raises(PydanticValidationError, match="event_source is required"):
            TriggerCreate(prompt="x", trigger_type="event", event_secret=_SIGNING_SECRET)

    def test_an_event_trigger_requires_a_secret(self):
        with pytest.raises(PydanticValidationError, match="event_secret is required"):
            TriggerCreate(prompt="x", trigger_type="event", event_source="github")

    def test_an_event_trigger_rejects_an_interval(self):
        with pytest.raises(PydanticValidationError, match="interval_seconds is not valid"):
            TriggerCreate(
                prompt="x",
                trigger_type="event",
                event_source="github",
                event_secret=_SIGNING_SECRET,
                interval_seconds=300,
            )

    def test_an_event_trigger_rejects_a_cron_expression(self):
        with pytest.raises(
            PydanticValidationError, match="cron_expression is not valid for an event"
        ):
            TriggerCreate(
                prompt="x",
                trigger_type="event",
                event_source="github",
                event_secret=_SIGNING_SECRET,
                cron_expression="0 9 * * *",
            )

    def test_a_schedule_rejects_an_event_source(self):
        with pytest.raises(PydanticValidationError, match="event_source is not valid"):
            TriggerCreate(prompt="x", interval_seconds=300, event_source="github")

    def test_a_schedule_rejects_a_secret(self):
        with pytest.raises(PydanticValidationError, match="event_secret is not valid"):
            TriggerCreate(prompt="x", interval_seconds=300, event_secret=_SIGNING_SECRET)

    def test_a_schedule_rejects_an_event_config(self):
        with pytest.raises(PydanticValidationError, match="event_config is not valid"):
            TriggerCreate(prompt="x", interval_seconds=300, event_config={})

    def test_a_github_config_defaults_to_issue_creation(self):
        trigger = _github_event()
        assert trigger.event_config == {"actions": ["opened"]}

    def test_an_unknown_config_key_is_refused(self):
        with pytest.raises(PydanticValidationError):
            TriggerCreate(
                prompt="x",
                trigger_type="event",
                event_source="github",
                event_secret=_SIGNING_SECRET,
                event_config={"unknown_filter": 1},
            )

    def test_a_secret_below_the_floor_is_refused(self):
        with pytest.raises(PydanticValidationError):
            TriggerCreate(
                prompt="x", trigger_type="event", event_source="email", event_secret="short"
            )

    def test_an_email_config_is_normalised_with_both_filters(self):
        trigger = TriggerCreate(
            prompt="x",
            trigger_type="event",
            event_source="email",
            event_secret=_SIGNING_SECRET,
            event_config={"subject_contains": "urgent"},
        )
        assert trigger.event_config == {"subject_contains": "urgent", "sender_contains": None}

    def test_a_linkedin_config_is_normalised_with_both_filters(self):
        trigger = TriggerCreate(
            prompt="x",
            trigger_type="event",
            event_source="linkedin",
            event_secret=_SIGNING_SECRET,
            event_config={"author_contains": "Jane"},
        )
        assert trigger.event_config == {"author_contains": "Jane", "text_contains": None}

    def test_the_generic_webhook_takes_no_filter(self):
        """Filtering is the sender's job; a key here would be stored to mean
        nothing, so the empty config model refuses it."""
        trigger = TriggerCreate(
            prompt="x", trigger_type="event", event_source="webhook", event_secret=_SIGNING_SECRET
        )
        assert trigger.event_config == {}
        with pytest.raises(PydanticValidationError):
            TriggerCreate(
                prompt="x",
                trigger_type="event",
                event_source="webhook",
                event_secret=_SIGNING_SECRET,
                event_config={"path_contains": "x"},
            )

    def test_an_event_read_exposes_its_webhook_url_on_the_public_api_host(self):
        read = TriggerRead(
            id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            is_active=True,
            trigger_type="event",
            schedule_kind="interval",
            event_source="github",
            prompt="x",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        # The full URL on the deployment's public base, not a bare path a browser
        # would resolve against the dashboard origin (a different host).
        base = settings.PUBLIC_BASE_URL.rstrip("/")
        assert read.webhook_url == f"{base}/api/v1/webhooks/triggers/github/{read.id}"

    def test_a_schedule_read_has_no_webhook_url(self):
        assert _read().webhook_url is None

    @pytest.mark.parametrize("field", ["prompt", "interval_seconds", "is_active"])
    def test_an_explicit_null_for_a_not_null_field_is_a_422(self, field):
        """`{"is_active": null}` maps to a NOT NULL column; caught here it is a 422
        naming the field, not an IntegrityError 500 the update guard exists to
        avoid but `exclude_unset` cannot see (a sent null looks omitted)."""
        with pytest.raises(PydanticValidationError, match="cannot be set to null"):
            TriggerUpdate.model_validate({field: None})

    def test_environment_id_may_be_set_to_null_to_return_to_the_default(self):
        """The one field whose null is meaningful, not an error."""
        assert TriggerUpdate.model_validate({"environment_id": None}).environment_id is None


class TestPreparingAnEventFire:
    """`prepare_event_fire` orchestrates the verifiers; the crypto itself is proven
    in `test_trigger_events.py`, so here `trigger_events` is mocked and what is
    asserted is the branching - what is ignored, what is a 403, what fires."""

    async def test_an_unknown_trigger_is_ignored(self):
        service = _service()
        with patch("app.services.agent_trigger.agent_trigger_repo") as repo:
            repo.get_by_id = AsyncMock(return_value=None)
            decision = await service.prepare_event_fire(
                "github", uuid.uuid4(), body=b"{}", headers={}
            )
        assert decision is None

    async def test_a_schedule_trigger_at_this_url_is_ignored(self):
        service = _service()
        with patch("app.services.agent_trigger.agent_trigger_repo") as repo:
            repo.get_by_id = AsyncMock(return_value=_trigger())
            decision = await service.prepare_event_fire(
                "github", uuid.uuid4(), body=b"{}", headers={}
            )
        assert decision is None

    async def test_a_delivery_to_the_wrong_source_is_ignored(self):
        service = _service()
        with patch("app.services.agent_trigger.agent_trigger_repo") as repo:
            repo.get_by_id = AsyncMock(return_value=_event_trigger())  # source is github
            decision = await service.prepare_event_fire(
                "email", uuid.uuid4(), body=b"{}", headers={}
            )
        assert decision is None

    async def test_an_inactive_event_trigger_is_ignored(self):
        service = _service()
        with patch("app.services.agent_trigger.agent_trigger_repo") as repo:
            repo.get_by_id = AsyncMock(return_value=_event_trigger(is_active=False))
            decision = await service.prepare_event_fire(
                "github", uuid.uuid4(), body=b"{}", headers={}
            )
        assert decision is None

    async def test_a_signature_that_does_not_verify_is_a_403(self):
        service = _service()
        trigger = _event_trigger()
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.unseal", return_value="secret"),
            patch("app.services.agent_trigger.trigger_events") as events,
        ):
            repo.get_by_id = AsyncMock(return_value=trigger)
            events.verify_signature = MagicMock(return_value=False)
            with pytest.raises(AuthorizationError):
                await service.prepare_event_fire("github", trigger.id, body=b"{}", headers={})

    async def test_a_payload_the_filter_rejects_is_ignored(self):
        service = _service()
        trigger = _event_trigger()
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.unseal", return_value="secret"),
            patch("app.services.agent_trigger.trigger_events") as events,
        ):
            repo.get_by_id = AsyncMock(return_value=trigger)
            events.verify_signature = MagicMock(return_value=True)
            events.event_matches = MagicMock(return_value=False)
            decision = await service.prepare_event_fire(
                "github", trigger.id, body=b'{"action": "closed"}', headers={}
            )
        assert decision is None

    async def test_a_verified_matching_delivery_returns_a_fire_decision(self):
        service = _service()
        trigger = _event_trigger()
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.unseal", return_value="secret"),
            patch("app.services.agent_trigger.trigger_events") as events,
        ):
            repo.get_by_id = AsyncMock(return_value=trigger)
            events.verify_signature = MagicMock(return_value=True)
            events.event_matches = MagicMock(return_value=True)
            events.render_context = MagicMock(return_value="ISSUE #7 opened")
            decision = await service.prepare_event_fire(
                "github", trigger.id, body=b'{"action": "opened"}', headers={}
            )
        assert decision == EventFireDecision(trigger_id=trigger.id, event_context="ISSUE #7 opened")

    async def test_a_body_that_is_not_json_is_a_400(self):
        service = _service()
        trigger = _event_trigger()
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.unseal", return_value="secret"),
            patch("app.services.agent_trigger.trigger_events") as events,
        ):
            repo.get_by_id = AsyncMock(return_value=trigger)
            events.verify_signature = MagicMock(return_value=True)
            with pytest.raises(BadRequestError):
                await service.prepare_event_fire("github", trigger.id, body=b"not json", headers={})

    async def test_a_body_that_is_a_json_array_is_a_400(self):
        service = _service()
        trigger = _event_trigger()
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.unseal", return_value="secret"),
            patch("app.services.agent_trigger.trigger_events") as events,
        ):
            repo.get_by_id = AsyncMock(return_value=trigger)
            events.verify_signature = MagicMock(return_value=True)
            with pytest.raises(BadRequestError, match="JSON object"):
                await service.prepare_event_fire("github", trigger.id, body=b"[]", headers={})


class TestFiringAnEvent:
    async def test_an_event_fire_appends_its_context_to_the_prompt(self):
        """A scheduled fire sends the prompt as-is; an event fire appends the
        rendered payload, so the agent sees which issue or email set it off."""
        agent = _agent()
        service = _service(agent)
        trigger = _event_trigger(
            agent_id=agent.id, prompt="Triage it", conversation_id=uuid.uuid4()
        )
        run = MagicMock(id=uuid.uuid4(), status=RunStatus.COMPLETED.value)
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.member_repo") as members,
            patch("app.services.agent_trigger.conversation_repo"),
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
            patch("app.services.agent_runner.AgentRunnerService") as runner_cls,
        ):
            repo.get_by_id = AsyncMock(return_value=trigger)
            members.get = AsyncMock(return_value=MagicMock(role=OrgRoleName.OWNER))
            runner = runner_cls.return_value
            runner.execute = AsyncMock(return_value=("done", run))
            await service.fire(trigger.id, event_context="A GitHub issue #7 was opened")
        assert runner.execute.call_args.args[2] == "Triage it\n\nA GitHub issue #7 was opened"


class TestEventTriggerRestrictions:
    async def test_retiming_an_event_trigger_is_refused(self):
        """A cadence is meaningless on an event trigger, and setting one would trip
        the shape CHECK as a 500 - so the service refuses it as a 400."""
        agent = _agent()
        service = _service(agent)
        trigger = _event_trigger(agent_id=agent.id)
        with patch("app.services.agent_trigger.agent_trigger_repo") as repo:
            repo.get = AsyncMock(return_value=trigger)
            repo.update = AsyncMock()
            with pytest.raises(BadRequestError, match="cadence"):
                await service.update(
                    _ctx(), agent.id, trigger.id, TriggerUpdate(interval_seconds=600)
                )
            repo.update.assert_not_called()

    async def test_retiming_a_cron_schedule_to_an_interval_switches_it(self):
        """Sending an interval to a cron schedule switches its kind in place -
        editing the cadence, not deleting and recreating. The opposite field is
        cleared so the resolved row is a valid interval schedule."""
        agent = _agent()
        service = _service(agent)
        trigger = _trigger(
            agent_id=agent.id,
            schedule_kind="cron",
            interval_seconds=None,
            cron_expression="0 9 * * *",
        )
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
        ):
            repo.get = AsyncMock(return_value=trigger)
            repo.update = AsyncMock(return_value=trigger)
            await service.update(_ctx(), agent.id, trigger.id, TriggerUpdate(interval_seconds=600))
        changes = repo.update.call_args.kwargs["update_data"]
        assert changes["schedule_kind"] == "interval"
        assert changes["interval_seconds"] == 600
        assert changes["cron_expression"] is None
        assert changes["next_fire_at"] is not None

    async def test_switching_an_interval_schedule_to_cron_in_place(self):
        """The other direction: a named `schedule_kind` with its expression retimes
        an interval schedule onto a clock, clearing the interval it no longer uses."""
        agent = _agent()
        service = _service(agent)
        trigger = _trigger(agent_id=agent.id, interval_seconds=3600)
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
        ):
            repo.get = AsyncMock(return_value=trigger)
            repo.update = AsyncMock(return_value=trigger)
            await service.update(
                _ctx(),
                agent.id,
                trigger.id,
                TriggerUpdate(schedule_kind="cron", cron_expression="0 9 * * *"),
            )
        changes = repo.update.call_args.kwargs["update_data"]
        assert changes["schedule_kind"] == "cron"
        assert changes["cron_expression"] == "0 9 * * *"
        assert changes["interval_seconds"] is None

    async def test_switching_to_an_interval_without_a_value_is_refused(self):
        """Naming `interval` on a cron schedule with no interval to fall back on is a
        400 for the field, not a row the shape CHECK rejects as a 500."""
        agent = _agent()
        service = _service(agent)
        trigger = _trigger(
            agent_id=agent.id,
            schedule_kind="cron",
            interval_seconds=None,
            cron_expression="0 9 * * *",
        )
        with patch("app.services.agent_trigger.agent_trigger_repo") as repo:
            repo.get = AsyncMock(return_value=trigger)
            repo.update = AsyncMock()
            with pytest.raises(BadRequestError, match="interval_seconds"):
                await service.update(
                    _ctx(),
                    agent.id,
                    trigger.id,
                    TriggerUpdate(schedule_kind="interval"),
                )
            repo.update.assert_not_called()

    async def test_an_unschedulable_cron_on_update_is_refused(self):
        """A cron that croniter cannot parse is a 400 naming the field, not a row
        the shape CHECK accepts and the heartbeat never fires."""
        agent = _agent()
        service = _service(agent)
        trigger = _trigger(agent_id=agent.id, interval_seconds=3600)
        with patch("app.services.agent_trigger.agent_trigger_repo") as repo:
            repo.get = AsyncMock(return_value=trigger)
            repo.update = AsyncMock()
            with pytest.raises(BadRequestError, match="crontab"):
                await service.update(
                    _ctx(),
                    agent.id,
                    trigger.id,
                    TriggerUpdate(cron_expression="not a cron"),
                )
            repo.update.assert_not_called()


def _preset_create(**overrides: object) -> TriggerCreate:
    fields: dict[str, object] = {
        "prompt": "triage the issue",
        "trigger_type": "event",
        "portal_key": "github",
        "preset_key": "issue_opened",
        "connection_id": uuid.uuid4(),
        "target": "acme/api",
    }
    fields.update(overrides)
    return TriggerCreate(**fields)


class TestCreatingFromAPortalPreset:
    """The preset path: the source and filter come from the catalog, the secret is
    minted, and an auto_webhook portal with a scope-bearing account registers the
    hook - any miss leaving the trigger manual rather than half-set."""

    async def test_a_preset_auto_registers_the_hook_when_the_account_can(self):
        agent = _agent()
        service = _service(agent)
        service.connections.webhook_access_token = AsyncMock(return_value="tok")
        adapter = MagicMock()
        adapter.register_webhook = AsyncMock(
            return_value=RegisteredWebhook(provider_webhook_id="hook-1")
        )
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
            patch("app.services.agent_trigger.portals.get_adapter", return_value=adapter),
        ):
            repo.create = AsyncMock(
                return_value=_event_trigger(conversation_id=uuid.uuid4(), delivery_mode="manual")
            )
            result = await service.create(_ctx(), agent.id, _preset_create())
        assert result.delivery_mode == "auto_webhook"
        assert result.provider_webhook_id == "hook-1"
        assert result.provider_target == "acme/api"
        # The minted plaintext secret is what the provider signs with, not the sealed one.
        assert adapter.register_webhook.await_args.kwargs["secret"]
        # The preset's normalized config and the connection reached the repo.
        assert repo.create.await_args.kwargs["event_source"] == "github"
        assert repo.create.await_args.kwargs["event_config"] == {"actions": ["opened"]}
        assert repo.create.await_args.kwargs["portal_key"] == "github"

    async def test_a_missing_scope_leaves_the_trigger_manual(self):
        agent = _agent()
        service = _service(agent)
        service.connections.webhook_access_token = AsyncMock(return_value=None)
        adapter = MagicMock()
        adapter.register_webhook = AsyncMock()
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
            patch("app.services.agent_trigger.portals.get_adapter", return_value=adapter),
        ):
            repo.create = AsyncMock(
                return_value=_event_trigger(conversation_id=uuid.uuid4(), delivery_mode="manual")
            )
            result = await service.create(_ctx(), agent.id, _preset_create())
        assert result.delivery_mode == "manual"
        adapter.register_webhook.assert_not_awaited()

    async def test_a_provider_refusal_falls_back_to_manual(self):
        agent = _agent()
        service = _service(agent)
        service.connections.webhook_access_token = AsyncMock(return_value="tok")
        adapter = MagicMock()
        adapter.register_webhook = AsyncMock(side_effect=WebhookRegistrationForbidden())
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
            patch("app.services.agent_trigger.portals.get_adapter", return_value=adapter),
        ):
            repo.create = AsyncMock(
                return_value=_event_trigger(conversation_id=uuid.uuid4(), delivery_mode="manual")
            )
            result = await service.create(_ctx(), agent.id, _preset_create())
        assert result.delivery_mode == "manual"
        assert result.provider_webhook_id is None

    async def test_a_portal_with_no_adapter_stays_manual(self):
        agent = _agent()
        service = _service(agent)
        service.connections.webhook_access_token = AsyncMock()
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
            patch("app.services.agent_trigger.portals.get_adapter", return_value=None),
        ):
            repo.create = AsyncMock(
                return_value=_event_trigger(conversation_id=uuid.uuid4(), delivery_mode="manual")
            )
            result = await service.create(_ctx(), agent.id, _preset_create())
        assert result.delivery_mode == "manual"
        service.connections.webhook_access_token.assert_not_awaited()

    async def test_a_manual_delivery_portal_never_attempts_registration(self):
        agent = _agent()
        service = _service(agent)
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
            patch("app.services.agent_trigger.portals.get_adapter") as get_adapter,
        ):
            repo.create = AsyncMock(
                return_value=_event_trigger(
                    event_source="email", conversation_id=uuid.uuid4(), delivery_mode="manual"
                )
            )
            result = await service.create(
                _ctx(),
                agent.id,
                _preset_create(portal_key="email", preset_key="any_email", target=None),
            )
        assert result.delivery_mode == "manual"
        get_adapter.assert_not_called()

    async def test_an_unknown_preset_is_refused(self):
        agent = _agent()
        service = _service(agent)
        with patch("app.services.agent_trigger.agent_trigger_repo") as repo:
            repo.create = AsyncMock()
            with pytest.raises(BadRequestError):
                await service.create(_ctx(), agent.id, _preset_create(preset_key="no-such-preset"))
        repo.create.assert_not_called()


class TestDeletingDeregistersItsWebhook:
    def _deletable(self, agent, **overrides):
        fields: dict[str, object] = {
            "agent_id": agent.id,
            "provider_webhook_id": "hook-1",
            "connection_id": uuid.uuid4(),
            "portal_key": "github",
            "provider_target": "acme/api",
        }
        fields.update(overrides)
        return _event_trigger(**fields)

    async def test_an_auto_registered_hook_is_deregistered(self):
        agent = _agent()
        service = _service(agent)
        service.connections.webhook_access_token = AsyncMock(return_value="tok")
        adapter = MagicMock()
        adapter.delete_webhook = AsyncMock()
        trigger = self._deletable(agent)
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
            patch("app.services.agent_trigger.portals.get_adapter", return_value=adapter),
        ):
            repo.get = AsyncMock(return_value=trigger)
            repo.delete = AsyncMock()
            await service.delete(_ctx(), agent.id, trigger.id)
        adapter.delete_webhook.assert_awaited_once()
        repo.delete.assert_awaited_once()

    async def test_a_trigger_with_no_hook_deregisters_nothing(self):
        agent = _agent()
        service = _service(agent)
        trigger = _trigger(agent_id=agent.id)  # a schedule: no provider hook
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
            patch("app.services.agent_trigger.portals.get_adapter") as get_adapter,
        ):
            repo.get = AsyncMock(return_value=trigger)
            repo.delete = AsyncMock()
            await service.delete(_ctx(), agent.id, trigger.id)
        get_adapter.assert_not_called()
        repo.delete.assert_awaited_once()

    async def test_an_unknown_portal_deregisters_nothing_but_still_deletes(self):
        agent = _agent()
        service = _service(agent)
        trigger = self._deletable(agent, portal_key="ghost-portal")
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
        ):
            repo.get = AsyncMock(return_value=trigger)
            repo.delete = AsyncMock()
            await service.delete(_ctx(), agent.id, trigger.id)
        repo.delete.assert_awaited_once()

    async def test_a_gone_token_stops_the_deregister(self):
        agent = _agent()
        service = _service(agent)
        service.connections.webhook_access_token = AsyncMock(return_value=None)
        adapter = MagicMock()
        adapter.delete_webhook = AsyncMock()
        trigger = self._deletable(agent)
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
            patch("app.services.agent_trigger.portals.get_adapter", return_value=adapter),
        ):
            repo.get = AsyncMock(return_value=trigger)
            repo.delete = AsyncMock()
            await service.delete(_ctx(), agent.id, trigger.id)
        adapter.delete_webhook.assert_not_awaited()
        repo.delete.assert_awaited_once()

    async def test_a_provider_error_never_blocks_the_delete(self):
        agent = _agent()
        service = _service(agent)
        service.connections.webhook_access_token = AsyncMock(side_effect=RuntimeError("down"))
        trigger = self._deletable(agent)
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
            patch(
                "app.services.agent_trigger.portals.get_adapter",
                return_value=MagicMock(delete_webhook=AsyncMock()),
            ),
        ):
            repo.get = AsyncMock(return_value=trigger)
            repo.delete = AsyncMock()
            await service.delete(_ctx(), agent.id, trigger.id)
        repo.delete.assert_awaited_once()
