"""An organization MCP server that stops answering is announced once, and so is its return (#2100).

The first sign of a dead server used to be an agent quietly losing its tools in
front of whoever asked the question. These pin the three places that now notice
- the console's test, the scheduled check and a run's probe - and the rule they
share: an outage is opened and closed once, so a server failing every check
for a day is one notification, and the next outage is another.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.agents.mcp import McpServerSpec, McpToolInfo
from app.agents.spec import OrgMcpServerRef
from app.db.models.mcp_connection import McpConnection
from app.services import mcp_connection as service

pytestmark = pytest.mark.anyio

BEGAN = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)


def _server(**overrides: Any) -> McpConnection:
    connection = McpConnection()
    values: dict[str, Any] = {
        "id": uuid4(),
        "scope": "org",
        "organization_id": uuid4(),
        "user_id": None,
        "name": "linear",
        "url": "https://mcp.linear.app/mcp",
        "is_enabled": True,
        "unreachable_since": None,
        "last_status": None,
        "last_error": None,
    }
    values.update(overrides)
    for key, value in values.items():
        setattr(connection, key, value)
    return connection


class _Notices:
    """What `NotificationService` was asked to say, in order."""

    def __init__(self) -> None:
        self.said: list[tuple[str, UUID, UUID, datetime]] = []

    def __call__(self, db: object) -> _Notices:
        return self

    async def mcp_server_down(
        self, connection: McpConnection, *, organization_id: UUID, since: datetime
    ) -> None:
        self.said.append(("down", connection.id, organization_id, since))

    async def mcp_server_recovered(
        self, connection: McpConnection, *, organization_id: UUID, since: datetime
    ) -> None:
        self.said.append(("recovered", connection.id, organization_id, since))


@pytest.fixture
def notices(monkeypatch: pytest.MonkeyPatch) -> _Notices:
    recorder = _Notices()
    monkeypatch.setattr(service, "NotificationService", recorder)
    return recorder


@pytest.fixture
def outages(monkeypatch: pytest.MonkeyPatch) -> tuple[AsyncMock, AsyncMock]:
    opened, closed = AsyncMock(return_value=True), AsyncMock(return_value=BEGAN)
    monkeypatch.setattr(service.mcp_connection_repo, "open_outage", opened)
    monkeypatch.setattr(service.mcp_connection_repo, "close_outage", closed)
    return opened, closed


class TestRecordReachability:
    async def test_the_check_that_opens_an_outage_tells_people_once(self, notices, outages):
        server = _server()
        opened, _ = outages

        await service.record_reachability(AsyncMock(), server, reachable=False)

        ((kind, server_id, org_id, since),) = notices.said
        assert (kind, server_id, org_id) == ("down", server.id, server.organization_id)
        assert since == opened.call_args.kwargs["at"]

    async def test_a_check_another_beat_to_the_outage_says_nothing(self, notices, outages):
        """Two runs finding the server down at once: one opened it, one is quiet."""
        opened, _ = outages
        opened.return_value = False

        await service.record_reachability(AsyncMock(), _server(), reachable=False)

        assert notices.said == []

    async def test_a_server_down_and_already_recorded_writes_nothing(self, notices, outages):
        """The second check of a dead server is the one that used to be a second alert."""
        opened, closed = outages

        await service.record_reachability(
            AsyncMock(), _server(unreachable_since=BEGAN), reachable=False
        )
        await service.record_reachability(AsyncMock(), _server(), reachable=True)

        opened.assert_not_awaited()
        closed.assert_not_awaited()
        assert notices.said == []

    async def test_recovery_closes_the_outage_it_began_with(self, notices, outages):
        server = _server(unreachable_since=BEGAN)

        await service.record_reachability(AsyncMock(), server, reachable=True)

        assert notices.said == [("recovered", server.id, server.organization_id, BEGAN)]

    async def test_a_recovery_another_check_announced_says_nothing(self, notices, outages):
        _, closed = outages
        closed.return_value = None

        await service.record_reachability(
            AsyncMock(), _server(unreachable_since=BEGAN), reachable=True
        )

        assert notices.said == []

    async def test_a_members_own_server_is_nobody_elses_to_be_told_about(self, notices, outages):
        opened, _ = outages

        await service.record_reachability(
            AsyncMock(), _server(scope="user", organization_id=None), reachable=False
        )

        opened.assert_not_awaited()
        assert notices.said == []


class TestTheConsoleTest:
    async def test_a_test_that_cannot_reach_the_server_opens_an_outage(
        self, monkeypatch, notices, outages
    ):
        server = _server()
        monkeypatch.setattr(service, "_resolve_auth_headers", AsyncMock(return_value={}))
        monkeypatch.setattr(service, "probe_mcp_server", AsyncMock(side_effect=TimeoutError))
        monkeypatch.setattr(service.mcp_connection_repo, "update", AsyncMock(return_value=server))

        _, _, error = await service.McpConnectionService(AsyncMock())._probe(server)

        assert error is not None
        assert [kind for kind, *_ in notices.said] == ["down"]

    async def test_a_grant_to_renew_is_not_an_outage(self, monkeypatch, notices, outages):
        """No credential means nothing was dialled, so nothing is known about the server."""
        server = _server()
        opened, _ = outages
        monkeypatch.setattr(service, "_resolve_auth_headers", AsyncMock(return_value=None))
        monkeypatch.setattr(service.mcp_connection_repo, "update", AsyncMock(return_value=server))

        _, _, error = await service.McpConnectionService(AsyncMock())._probe(server)

        assert error is not None and "authorized" in error
        opened.assert_not_awaited()


class TestTheScheduledCheck:
    async def test_every_server_with_a_credential_is_dialled_and_recorded(
        self, monkeypatch, notices, outages
    ):
        answering, dead, unauthorized = _server(name="a"), _server(name="b"), _server(name="c")
        monkeypatch.setattr(
            service.mcp_connection_repo,
            "list_org_servers_to_check",
            AsyncMock(return_value=[answering, dead, unauthorized]),
        )

        async def headers(db: object, connection: McpConnection) -> dict[str, str] | None:
            return None if connection is unauthorized else {}

        async def probe(url: str, headers: dict[str, str]) -> list[McpToolInfo]:
            if url == dead.url:
                raise TimeoutError
            return [McpToolInfo(name="search", description="")]

        dead.url = "https://dead.example/mcp"
        update = AsyncMock(side_effect=lambda db, *, db_connection, update_data: db_connection)
        monkeypatch.setattr(service, "_resolve_auth_headers", headers)
        monkeypatch.setattr(service, "probe_mcp_server", probe)
        monkeypatch.setattr(service.mcp_connection_repo, "update", update)

        counts = await service.check_organization_servers(AsyncMock())

        assert counts == {"answered": 1, "unreachable": 1, "skipped": 1}
        written = {
            call.kwargs["db_connection"].name: call.kwargs["update_data"]["last_status"]
            for call in update.call_args_list
        }
        assert written == {"a": "ok", "b": "error"}
        assert [(kind, server_id) for kind, server_id, *_ in notices.said] == [("down", dead.id)]


class TestARunsProbe:
    @staticmethod
    def _spawned(monkeypatch: pytest.MonkeyPatch) -> list[list[tuple[UUID, bool]]]:
        """What each run handed on to be recorded after its commit."""
        handed: list[list[tuple[UUID, bool]]] = []

        async def record(observed: list[tuple[UUID, bool]]) -> None:
            return None

        def recorded(observed: list[tuple[UUID, bool]]) -> Any:
            handed.append(observed)
            return record(observed)

        def spawn(db: object, coro: Any, *, name: str) -> None:
            coro.close()

        monkeypatch.setattr(service, "_record_run_reachability", recorded)
        monkeypatch.setattr(service, "spawn_after_commit", spawn)
        return handed

    async def _run(self, monkeypatch, servers: list[McpConnection], dead: set[UUID]) -> None:
        async def probe(specs: list[McpServerSpec]) -> list[tuple[McpServerSpec, object]]:
            return [(spec, None if spec.connection_id in dead else object()) for spec in specs]

        monkeypatch.setattr(service, "probe_toolsets", probe)
        monkeypatch.setattr(service, "_resolve_auth_headers", AsyncMock(return_value={}))
        monkeypatch.setattr(
            service.mcp_connection_repo,
            "get_org_scoped_by_ids",
            AsyncMock(return_value={server.id: server for server in servers}),
        )
        await service.build_toolsets_for_agent(
            AsyncMock(),
            organization_id=uuid4(),
            refs=[OrgMcpServerRef(connection_id=server.id) for server in servers],
        )

    async def test_only_a_change_from_what_was_recorded_is_handed_on(self, monkeypatch):
        """Recorded after the run commits, one server per transaction, and only when
        the run saw something the row does not already say."""
        handed = self._spawned(monkeypatch)
        went_down = _server(name="a")
        came_back = _server(name="b", unreachable_since=BEGAN)
        still_up = _server(name="c")
        still_down = _server(name="d", unreachable_since=BEGAN)

        await self._run(
            monkeypatch,
            [went_down, came_back, still_up, still_down],
            dead={went_down.id, still_down.id},
        )

        assert handed == [[(went_down.id, False), (came_back.id, True)]]

    async def test_a_run_that_finds_everything_as_recorded_hands_nothing_on(self, monkeypatch):
        handed = self._spawned(monkeypatch)

        await self._run(monkeypatch, [_server()], dead=set())

        assert handed == []

    async def test_each_server_is_recorded_in_its_own_transaction(
        self, monkeypatch, notices, outages
    ):
        server = _server()
        sessions: list[object] = []

        @asynccontextmanager
        async def context() -> AsyncIterator[object]:
            db = AsyncMock()
            sessions.append(db)
            yield db

        found = {server.id: server}
        monkeypatch.setattr(service, "get_db_context", context)
        monkeypatch.setattr(
            service.mcp_connection_repo,
            "get_by_id",
            AsyncMock(side_effect=lambda db, connection_id: found.get(connection_id)),
        )

        # The second has been deleted since the run read it: nothing to record.
        await service._record_run_reachability([(server.id, False), (uuid4(), True)])

        assert len(sessions) == 2
        assert [(kind, server_id) for kind, server_id, *_ in notices.said] == [("down", server.id)]
