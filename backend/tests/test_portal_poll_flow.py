"""The heartbeat that reads connected accounts, and the order it does things in.

The adapter's own failures are `test_gmail_polling.py`. What is here is the part
that decides whether work is lost: which grants a tick claims, what one poll's
events fire, and - the one that matters most - that the cursor advances only
together with the fires it read, in the same transaction.
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.portals import PolledEvent, PolledEvents, PortalUnreachable

pytestmark = pytest.mark.anyio


def _grant(**overrides):
    fields: dict[str, object] = {
        "id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "portal_key": "google",
        "purpose": "portal",
        "poll_cursor": {"history_id": "500"},
        "polled_at": None,
        "last_status": "ok",
        "last_error": None,
        "is_enabled": True,
    }
    fields.update(overrides)
    return MagicMock(**fields)


def _event(identifier: str = "gmail:m1", **payload):
    return PolledEvent(
        delivery_id=identifier,
        payload={"subject": "Invoice", "from": "billing@acme.test", "labels": ["INBOX"], **payload},
    )


class _Recorder:
    """What the flow did, in the order it did it.

    The order is the assertion: a cursor written before a dispatch is a batch of
    messages the mailbox says were handled and nothing handled.
    """

    def __init__(self) -> None:
        self.steps: list[str] = []


def _service(recorder: _Recorder, *, read: object, decisions: list):
    """A connection service and a trigger service that record their calls."""
    connections = MagicMock()
    connections.claim_grants_to_poll = AsyncMock(return_value=[_grant()])

    async def poll_grant(grant, *, places):
        recorder.steps.append("poll")
        return read

    async def store_cursor(grant, *, cursor):
        recorder.steps.append(f"cursor:{cursor['history_id']}")

    connections.poll_grant = poll_grant
    connections.store_poll_cursor = store_cursor

    triggers = MagicMock()

    async def prepare(*, organization_id, event_source, events):
        recorder.steps.append(f"match:{event_source}:{len(events)}")
        return decisions

    async def disable(*, organization_id, event_source, reason, places=None):
        recorder.steps.append(f"disable:{reason}:{sorted(places) if places else 'all'}")
        return 1

    triggers.prepare_polled_fires = prepare
    triggers.polled_places = AsyncMock(return_value={})
    triggers.disable_polled = disable
    return connections, triggers


def _queueing(triggers: MagicMock, recorder: _Recorder, dispatch=None) -> None:
    """Record each fire the trigger service queues, as the poll asks for it."""

    async def queue_fire(trigger_id, *, organization_id, event_context=None, claimed_at=None):
        recorder.steps.append(f"fire:{trigger_id}")
        if dispatch is not None:
            await dispatch()

    triggers.queue_fire = queue_fire


async def _run(recorder: _Recorder, *, read, decisions, dispatch=None):
    """The flow, with its two services and its dispatcher swapped out."""
    from app.worker.tasks import trigger_tasks

    connections, triggers = _service(recorder, read=read, decisions=decisions)
    _queueing(triggers, recorder, dispatch)

    session = MagicMock()

    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc):
            return False

    async def already_configured():
        return None

    with (
        patch.object(trigger_tasks, "get_worker_db_context", lambda: _Ctx()),
        patch.object(trigger_tasks, "_ensure_trigger_dedupe", already_configured),
        patch("app.services.mcp_connection.McpConnectionService", return_value=connections),
        patch("app.services.agent_trigger.AgentTriggerService", return_value=triggers),
    ):
        await trigger_tasks.poll_portal_grants()


class TestTheOrderOfWork:
    async def test_the_cursor_advances_after_the_fires_are_queued(self):
        """Fires and cursor are one transaction, and the cursor is written last.

        A cursor committed without its fires would leave a mailbox that says every
        message was handled while nothing handled any of them - silently, for ever.
        Together, a crash re-reads them and the delivery-id claim dedups:
        at-least-once with the duplicate suppressed.
        """
        recorder = _Recorder()
        decision = SimpleNamespace(trigger_id=uuid.uuid4(), event_context="An email arrived.")

        await _run(
            recorder,
            read=PolledEvents(events=(_event(),), cursor={"history_id": "600"}),
            decisions=[decision],
        )

        assert recorder.steps == [
            "poll",
            "match:gmail:1",
            f"fire:{decision.trigger_id}",
            "cursor:600",
        ]

    async def test_a_fire_that_cannot_be_queued_keeps_the_cursor_where_it_was(self):
        """A queueing that raised fails the grant: the cursor is not stored, so the
        window is re-read next tick rather than marked handled - unlike a webhook,
        no provider resends a polled message."""
        recorder = _Recorder()
        decision = SimpleNamespace(trigger_id=uuid.uuid4(), event_context="a")

        async def refused():
            raise RuntimeError("the database went away")

        await _run(
            recorder,
            read=PolledEvents(events=(_event(),), cursor={"history_id": "601"}),
            decisions=[decision],
            dispatch=refused,
        )

        assert "cursor:601" not in recorder.steps

    async def test_a_grant_that_cannot_be_read_advances_no_cursor(self):
        """`poll_grant` answering `None` is a mailbox to try again in a minute, not
        one to mark as read."""
        recorder = _Recorder()

        await _run(recorder, read=None, decisions=[])

        assert recorder.steps == ["poll"]

    async def test_nothing_new_still_advances_the_cursor(self):
        """An empty poll moved the mailbox's position forward; not storing it would
        re-ask the same window every minute for ever."""
        recorder = _Recorder()

        await _run(
            recorder, read=PolledEvents(events=(), cursor={"history_id": "700"}), decisions=[]
        )

        assert recorder.steps == ["poll", "match:gmail:0", "cursor:700"]

    async def test_a_revoked_grant_turns_its_triggers_off_and_reads_nothing(self):
        """Retrying a refused grant every minute fires nothing and says nothing
        (#1984): the triggers stop, visibly, and no cursor moves."""
        from app.services.mcp_connection import RevokedGrant

        recorder = _Recorder()

        await _run(recorder, read=RevokedGrant(), decisions=[])

        assert recorder.steps == ["poll", "disable:mailbox_access_revoked:all"]

    async def test_a_folder_that_cannot_be_read_turns_off_only_its_triggers(self):
        """The account answered; one place did not. The rest of the poll is fired
        and stored as usual."""
        recorder = _Recorder()

        await _run(
            recorder,
            read=PolledEvents(
                events=(), cursor={"history_id": "800"}, unreadable=frozenset({"|invoices"})
            ),
            decisions=[],
        )

        assert recorder.steps == [
            "poll",
            "disable:mailbox_folder_unreadable:['|invoices']",
            "match:gmail:0",
            "cursor:800",
        ]


class TestOneMailboxIsOneTenant:
    """The isolation the tick did not have, and the reason it needs it.

    `poll_grant` answers `None` for every recoverable provider failure, so anything
    that raises out of it is a shape nobody anticipated - a MIME tree from an
    attacker-chosen email, a documented object arriving as `null`. Without the
    guard the tick dies on it and dies again every minute, so one malformed message
    in one organization's mailbox stops polling for every other organization on the
    deployment.
    """

    async def _run_two(self, first_raises: Exception | None):
        from app.worker.tasks import trigger_tasks

        recorder = _Recorder()
        one, two = _grant(portal_key="google"), _grant(portal_key="google")
        connections = MagicMock()
        connections.claim_grants_to_poll = AsyncMock(return_value=[one, two])

        async def poll_grant(grant, *, places):
            recorder.steps.append(f"poll:{grant.id}")
            if grant is one and first_raises is not None:
                raise first_raises
            return PolledEvents(events=(), cursor={"history_id": "900"})

        async def store_cursor(grant, *, cursor):
            recorder.steps.append(f"cursor:{grant.id}")

        connections.poll_grant = poll_grant
        connections.store_poll_cursor = store_cursor
        triggers = MagicMock()
        triggers.prepare_polled_fires = AsyncMock(return_value=[])
        triggers.polled_places = AsyncMock(return_value={})

        session = MagicMock()

        class _Ctx:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *exc):
                return False

        with (
            patch.object(trigger_tasks, "get_worker_db_context", lambda: _Ctx()),
            patch("app.services.mcp_connection.McpConnectionService", return_value=connections),
            patch("app.services.agent_trigger.AgentTriggerService", return_value=triggers),
        ):
            await trigger_tasks.poll_portal_grants()
        return recorder, one, two

    async def test_a_mailbox_that_raises_does_not_stop_the_others(self):
        recorder, one, two = await self._run_two(AttributeError("'NoneType' has no 'get'"))

        assert f"poll:{two.id}" in recorder.steps
        assert f"cursor:{two.id}" in recorder.steps
        # And the one that raised advanced no cursor: its window is unread.
        assert f"cursor:{one.id}" not in recorder.steps

    async def test_the_tick_finishes_rather_than_failing_the_job(self):
        # A raising sweep is a failed job and an alert; a logged grant is the
        # thing to fix. The distinction is the point of the guard.
        recorder, _, two = await self._run_two(RuntimeError("nobody saw this coming"))

        assert recorder.steps[-1] == f"cursor:{two.id}"


class TestWhichGrantsAreRead:
    async def test_only_polled_portals_are_claimed(self):
        """GitHub is pushed to and must never be polled: a tick that claimed it
        would spend a token exchange a minute to ask a question nobody asked."""
        from app.worker.tasks import trigger_tasks

        connections = MagicMock()
        connections.claim_grants_to_poll = AsyncMock(return_value=[])
        session = MagicMock()

        class _Ctx:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *exc):
                return False

        with (
            patch.object(trigger_tasks, "get_worker_db_context", lambda: _Ctx()),
            patch("app.services.mcp_connection.McpConnectionService", return_value=connections),
        ):
            await trigger_tasks.poll_portal_grants()

        [call] = connections.claim_grants_to_poll.await_args_list
        assert call.kwargs["portal_keys"] == [
            "google",
            "microsoft",
            "google_drive",
            "microsoft_files",
            "google_calendar",
            "outlook_calendar",
        ]


class TestMatchingAPollAgainstTriggers:
    async def _prepare(self, triggers, events):
        from app.services.agent_trigger import AgentTriggerService

        service = AgentTriggerService(MagicMock())
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.trigger_dedupe") as dedupe,
        ):
            repo.list_active_for_event_source = AsyncMock(return_value=triggers)
            dedupe.claim_event_delivery = AsyncMock(return_value=True)
            return await service.prepare_polled_fires(
                organization_id=uuid.uuid4(), event_source="gmail", events=events
            )

    def _trigger(self, config):
        return MagicMock(id=uuid.uuid4(), event_config=config)

    async def test_one_message_can_fire_several_triggers(self):
        """Unlike a webhook, whose URL names exactly one. "Any message" and
        "marked important" on one mailbox is the shape the presets invite."""
        any_message = self._trigger({})
        important = self._trigger({"label": "IMPORTANT"})

        decisions = await self._prepare(
            [any_message, important], [_event(labels=["INBOX", "IMPORTANT"])]
        )

        assert {one.trigger_id for one in decisions} == {any_message.id, important.id}

    async def test_a_filter_that_does_not_match_fires_nothing(self):
        decisions = await self._prepare(
            [self._trigger({"subject_contains": "receipt"})], [_event(subject="Invoice")]
        )

        assert decisions == []

    async def test_the_context_the_fire_appends_is_rendered_once_per_trigger(self):
        decisions = await self._prepare([self._trigger({})], [_event()])

        assert "An email arrived" in decisions[0].event_context

    async def test_no_triggers_on_the_source_is_no_work(self):
        """A connected mailbox with nothing watching it: the poll still advances the
        cursor, and this answers before a single filter is evaluated."""
        assert await self._prepare([], [_event()]) == []


class TestReadingAGrant:
    async def _poll(
        self,
        *,
        token,
        adapter_result=None,
        raises=None,
        needs_consent=False,
        renewed=None,
        refresh_left=True,
    ):
        from app.services.mcp_connection import McpConnectionService

        service = McpConnectionService(MagicMock())
        grant = _grant()
        adapter = MagicMock()
        if raises is not None:
            adapter.poll = AsyncMock(side_effect=raises)
        else:
            adapter.poll = AsyncMock(return_value=adapter_result)
        refresh = AsyncMock(return_value=renewed)
        payload = MagicMock(refresh_token="rt" if refresh_left else None)
        with (
            patch("app.services.mcp_connection.portals") as portals_module,
            patch("app.services.mcp_connection._oauth_access_token", AsyncMock(return_value=token)),
            patch(
                "app.services.mcp_connection.grant_needs_consent",
                MagicMock(return_value=needs_consent),
            ),
            patch("app.services.mcp_connection._refresh_under_lock", refresh),
            patch("app.services.mcp_connection._decode_payload", MagicMock(return_value=payload)),
            patch("app.services.mcp_connection.mcp_connection_repo") as repo,
        ):
            portals_module.get_adapter.return_value = adapter
            portals_module.PortalError = PortalUnreachable
            repo.update = AsyncMock()
            read = await service.poll_grant(grant)
            self.refresh, self.adapter = refresh, adapter
            return read, repo

    async def test_a_grant_whose_token_will_not_renew_is_marked_and_skipped(self):
        """A token endpoint that is down. Marked so the card says the mailbox
        stopped working, and tried again next tick."""
        read, repo = await self._poll(token=None)

        assert read is None
        assert repo.update.await_args.kwargs["update_data"]["last_status"] == "error"

    async def test_a_grant_only_a_new_consent_can_fix_is_revoked(self):
        """The refresh token is gone - refused as `invalid_grant` and dropped - so
        the card asks for a reconnect and the caller stops the triggers."""
        from app.services.mcp_connection import GRANT_REVOKED, RevokedGrant

        read, repo = await self._poll(token=None, needs_consent=True)

        assert isinstance(read, RevokedGrant)
        assert repo.update.await_args.kwargs["update_data"]["last_error"] == GRANT_REVOKED

    async def test_a_token_refused_again_after_a_refresh_is_revoked(self):
        """A 401 for a token this side still held to be good, and again for the one
        a refresh gave: an administrator withdrew consent. Asking again next
        minute would be refused again."""
        from app.services.mcp_connection import RevokedGrant

        read, _ = await self._poll(
            token="t", raises=PortalUnreachable(details={"status": 401}), renewed="t2"
        )

        assert isinstance(read, RevokedGrant)
        assert self.refresh.await_args.kwargs == {"rejected": "t"}
        assert self.adapter.poll.await_count == 2

    async def test_a_token_that_expired_early_is_refreshed_and_read_again(self):
        """Codex on #2195: a 401 proves only that this access token is unusable,
        not that the grant is - one refresh and one retry before any trigger stops."""
        read_ok = MagicMock()

        read, _ = await self._poll(
            token="t",
            raises=[PortalUnreachable(details={"status": 401}), read_ok],
            renewed="t2",
        )

        assert read is read_ok
        assert self.adapter.poll.await_args.kwargs["access_token"] == "t2"

    async def test_a_401_with_no_refresh_token_left_is_revoked(self):
        from app.services.mcp_connection import RevokedGrant

        read, _ = await self._poll(
            token="t", raises=PortalUnreachable(details={"status": 401}), refresh_left=False
        )

        assert isinstance(read, RevokedGrant)
        assert self.adapter.poll.await_count == 1

    async def test_a_401_whose_refresh_fails_for_now_is_tried_next_tick(self):
        """The token endpoint is down: nothing says the grant is dead."""
        read, repo = await self._poll(token="t", raises=PortalUnreachable(details={"status": 401}))

        assert read is None
        assert repo.update.await_args.kwargs["update_data"]["last_status"] == "error"

    async def test_a_provider_failure_says_nothing_of_the_providers_own_words(self):
        """A portal's error body echoes the request, and the request carries a
        bearer token (#423)."""
        read, repo = await self._poll(
            token="t", raises=PortalUnreachable(details={"status": 500, "secret": "tok"})
        )

        assert read is None
        recorded = repo.update.await_args.kwargs["update_data"]["last_error"]
        assert "tok" not in recorded
        assert "refused or could not be reached" in recorded

    async def test_a_working_read_clears_a_previous_failure(self):
        """A mailbox that started answering again stops saying it did not: the card
        reads `last_error`, so leaving it set would keep reporting a fixed problem."""
        from app.services.mcp_connection import McpConnectionService

        service = McpConnectionService(MagicMock())
        grant = _grant(last_status="error", last_error="The provider refused")
        adapter = MagicMock()
        adapter.poll = AsyncMock(return_value=PolledEvents(events=(), cursor={"history_id": "1"}))
        with (
            patch("app.services.mcp_connection.portals") as portals_module,
            patch("app.services.mcp_connection._oauth_access_token", AsyncMock(return_value="t")),
            patch("app.services.mcp_connection.mcp_connection_repo") as repo,
        ):
            portals_module.get_adapter.return_value = adapter
            portals_module.PortalError = PortalUnreachable
            repo.update = AsyncMock()
            read = await service.poll_grant(grant)

        assert read is not None
        assert repo.update.await_args.kwargs["update_data"] == {
            "last_status": "ok",
            "last_error": None,
        }

    async def test_a_read_that_was_already_working_writes_nothing(self):
        """No status write per minute per mailbox for a connection that is fine."""
        read, repo = await self._poll(
            token="t", adapter_result=PolledEvents(events=(), cursor={"history_id": "1"})
        )

        assert read is not None
        repo.update.assert_not_called()

    async def test_a_portal_with_no_adapter_is_not_polled(self):
        from app.services.mcp_connection import McpConnectionService

        service = McpConnectionService(MagicMock())
        with patch("app.services.mcp_connection.portals") as portals_module:
            portals_module.get_adapter.return_value = None
            assert await service.poll_grant(_grant()) is None


class TestStoringTheCursor:
    async def test_it_writes_the_cursor_and_when_it_was_read(self):
        from app.services.mcp_connection import McpConnectionService

        service = McpConnectionService(MagicMock())
        with patch("app.services.mcp_connection.mcp_connection_repo") as repo:
            repo.update = AsyncMock()
            await service.store_poll_cursor(_grant(), cursor={"history_id": "900"})

        written = repo.update.await_args.kwargs["update_data"]
        assert written["poll_cursor"] == {"history_id": "900"}
        assert isinstance(written["last_checked_at"], datetime)


class TestClaimingGrants:
    async def test_it_asks_for_grants_older_than_the_interval(self):
        from app.services.mcp_connection import McpConnectionService

        service = McpConnectionService(MagicMock())
        with patch("app.services.mcp_connection.mcp_connection_repo") as repo:
            repo.claim_portal_grants_to_poll = AsyncMock(return_value=[])
            await service.claim_grants_to_poll(portal_keys=["google"])

        asked = repo.claim_portal_grants_to_poll.await_args.kwargs
        assert asked["portal_keys"] == ["google"]
        assert asked["not_polled_since"] < datetime.now(UTC)


class TestTheRefusalsAroundIt:
    """The branches a poller only reaches when something is wrong."""

    async def test_a_manual_portal_is_never_blocked_from_connecting(self):
        """It needs no account: the *user* wires the relay."""
        from app.services import portal_catalog
        from app.services.agent_trigger import _connect_blocked_by

        manual = portal_catalog.PortalEntry(
            key="relay",
            name="Relay",
            description="…",
            category="productivity",
            event_source="webhook",
            delivery=portal_catalog.DeliveryMode.MANUAL,
            presets=(),
        )
        assert _connect_blocked_by(manual, oauth_apps=0) is None

    async def test_a_webhook_portal_with_no_catalog_entry_cannot_be_connected(self):
        """A grant is staged on an MCP catalog entry, so a portal with none has
        nowhere to put one - and offering Connect would only fail."""
        from app.services import portal_catalog
        from app.services.agent_trigger import _connect_blocked_by

        orphan = portal_catalog.PortalEntry(
            key="orphan",
            name="Orphan",
            description="…",
            category="productivity",
            event_source="webhook",
            delivery=portal_catalog.DeliveryMode.AUTO_WEBHOOK,
            presets=(),
        )
        assert _connect_blocked_by(orphan, oauth_apps=1) == "oauth_unavailable"

    async def test_a_target_listing_for_a_portal_with_no_adapter_is_empty(self):
        """A portal that names a target kind but ships no adapter: the picker falls
        back to free text rather than the create being blocked."""
        from app.services.agent_trigger import AgentTriggerService

        service = AgentTriggerService(MagicMock())
        service.agents = MagicMock(get=AsyncMock())
        with (
            patch("app.services.agent_trigger.portal_catalog") as catalog,
            patch("app.services.agent_trigger.portals") as portals_module,
        ):
            catalog.get_portal.return_value = MagicMock(target_kind="repo", read_scopes=())
            portals_module.get_adapter.return_value = None
            assert (
                await service.list_portal_targets(
                    MagicMock(), "whatever", uuid.uuid4(), agent_id=uuid.uuid4()
                )
                == []
            )

    async def test_a_message_a_trigger_already_saw_fires_it_no_second_time(self):
        """The claim is per trigger *and* per delivery, so a re-read of one message
        fires nothing again - which is what makes advancing the cursor last safe."""
        from app.services.agent_trigger import AgentTriggerService

        service = AgentTriggerService(MagicMock())
        trigger = MagicMock(id=uuid.uuid4(), event_config={})
        with (
            patch("app.services.agent_trigger.agent_trigger_repo") as repo,
            patch("app.services.agent_trigger.trigger_dedupe") as dedupe,
        ):
            repo.list_active_for_event_source = AsyncMock(return_value=[trigger])
            dedupe.claim_event_delivery = AsyncMock(return_value=False)
            decisions = await service.prepare_polled_fires(
                organization_id=uuid.uuid4(), event_source="gmail", events=[_event()]
            )

        assert decisions == []

    async def test_the_base_adapter_has_no_poll_at_all(self):
        """A portal is correct as manual the day it is added: the base raises rather
        than being abstract, so half a portal degrades instead of crashing."""
        from app.services.portals import WebhookRegistrationUnavailable
        from app.services.portals.base import PortalAdapter

        with pytest.raises(WebhookRegistrationUnavailable):
            await PortalAdapter().poll(access_token="t", cursor=None)


class TestWhereAnOutlookPollLooks:
    """The places the poller reads, and the triggers it stops (#1984)."""

    @staticmethod
    def _trigger(config: dict, *, minutes_ago: int, edited_minutes_ago: int | None = None):
        now = datetime.now(UTC).replace(microsecond=0)
        return MagicMock(
            id=uuid.uuid4(),
            event_config=config,
            created_at=now - timedelta(minutes=minutes_ago),
            updated_at=(
                None if edited_minutes_ago is None else now - timedelta(minutes=edited_minutes_ago)
            ),
        )

    async def _with(self, triggers, call):
        from app.services.agent_trigger import AgentTriggerService

        service = AgentTriggerService(MagicMock())
        with patch("app.services.agent_trigger.agent_trigger_repo") as repo:
            repo.list_active_for_event_source = AsyncMock(return_value=triggers)
            disabled = AsyncMock()
            with patch.object(AgentTriggerService, "_disable", disabled):
                result = await call(service)
        return result, disabled

    async def test_each_place_is_keyed_to_its_earliest_trigger(self):
        older = self._trigger({"folder": "inbox"}, minutes_ago=30)
        newer = self._trigger({"folder": "Inbox", "has_attachments": True}, minutes_ago=5)
        archive = self._trigger({"folder": "archive"}, minutes_ago=1)

        places, _ = await self._with(
            [newer, older, archive],
            lambda service: service.polled_places(
                organization_id=uuid.uuid4(), event_source="outlook"
            ),
        )

        assert places == {"|inbox": older.created_at, "|archive": archive.created_at}

    async def test_a_trigger_moved_to_another_folder_starts_there_from_the_move(self):
        """Codex on #2195: keyed to its creation, a month-old trigger moved to a
        folder nobody watched read that folder's month of mail as news."""
        moved = self._trigger(
            {"folder": "Invoices"}, minutes_ago=60 * 24 * 30, edited_minutes_ago=1
        )

        places, _ = await self._with(
            [moved],
            lambda service: service.polled_places(
                organization_id=uuid.uuid4(), event_source="outlook"
            ),
        )

        assert places == {"|invoices": moved.updated_at}

    async def test_a_source_read_whole_has_no_places(self):
        places, _ = await self._with(
            [self._trigger({"label": "INBOX"}, minutes_ago=1)],
            lambda service: service.polled_places(
                organization_id=uuid.uuid4(), event_source="gmail"
            ),
        )

        assert places == {}

    async def test_a_revoked_grant_stops_every_trigger_on_the_source(self):
        triggers = [self._trigger({}, minutes_ago=1), self._trigger({"folder": "x"}, minutes_ago=1)]

        stopped, disabled = await self._with(
            triggers,
            lambda service: service.disable_polled(
                organization_id=uuid.uuid4(), event_source="outlook", reason="revoked"
            ),
        )

        assert stopped == 2
        assert [call.kwargs["reason"] for call in disabled.await_args_list] == ["revoked"] * 2

    async def test_an_unreadable_place_stops_only_its_triggers(self):
        inbox = self._trigger({}, minutes_ago=1)
        shared = self._trigger({"mailbox": "ops@corp.test"}, minutes_ago=1)

        stopped, disabled = await self._with(
            [inbox, shared],
            lambda service: service.disable_polled(
                organization_id=uuid.uuid4(),
                event_source="outlook",
                reason="unreadable",
                places=frozenset({"ops@corp.test|inbox"}),
            ),
        )

        assert stopped == 1
        assert disabled.await_args.args == (shared,)
