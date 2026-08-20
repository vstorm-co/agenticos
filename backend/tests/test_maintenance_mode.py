"""A maintenance window that actually holds the API shut.

Two things are asserted here and the second is the one that matters. That a window
refuses ordinary traffic is the easy half - if it only hid the console, a page
somebody already has open would go on talking to an agent, and that is a banner
rather than a maintenance mode.

The hard half is that it **cannot lock its own operator out**. An administrator who
turns maintenance on and then cannot sign in to turn it off has no console, no
route and no recourse; the allow-list is what stops that, and every entry in it is
tested by name rather than by prefix so that shortening one is a failure here.

It also fails *open*. A gate that cannot read its own switch - a Redis blip, a
migration that has not run - must not close the API, because the alternative turns
an infrastructure hiccup into a total outage nobody scheduled.
"""

from __future__ import annotations

import contextlib
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core import maintenance
from app.core.maintenance import (
    CACHE_KEY,
    CACHE_TTL_SECONDS,
    RETRY_AFTER_SECONDS,
    MaintenanceModeMiddleware,
)

pytestmark = pytest.mark.anyio


@contextlib.asynccontextmanager
async def _no_db():
    """A session context whose settings row nobody reads - the cache answers first."""
    yield MagicMock()
    raise AssertionError("the database was read when the cache should have answered")


@pytest.fixture
def redis(monkeypatch) -> MagicMock:
    stub = MagicMock()
    stub.get = AsyncMock(return_value=None)
    stub.set = AsyncMock(return_value=True)
    maintenance.configure(stub)
    yield stub
    maintenance.configure(None)


@pytest.fixture
def row(monkeypatch) -> MagicMock:
    """The settings row the gate reads through to on a cache miss."""
    holder = MagicMock()
    holder.value = None

    @contextlib.asynccontextmanager
    async def _db():
        yield MagicMock()

    stub = MagicMock()
    stub.get = AsyncMock(side_effect=lambda _db: holder.value)
    monkeypatch.setattr(maintenance, "get_db_context", _db)
    monkeypatch.setattr(maintenance, "deployment_settings_repo", stub)
    return holder


async def call(path: str, *, scope_type: str = "http") -> tuple[int, dict[str, str], bytes]:
    """Drive the middleware over one request and report what came back."""
    downstream_ran: list[bool] = []

    async def downstream(scope, receive, send):
        downstream_ran.append(True)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"downstream"})

    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    await MaintenanceModeMiddleware(downstream)({"type": scope_type, "path": path}, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    headers = {k.decode(): v.decode() for k, v in start.get("headers", [])}
    return start["status"], headers, body


def a_closed_row(message: str | None = "Back at 22:00") -> MagicMock:
    row = MagicMock()
    row.maintenance_mode = True
    row.maintenance_message = message
    return row


class TestAnOpenDeployment:
    async def test_traffic_passes_through(self, redis, row):
        redis.get.return_value = json.dumps({"on": False, "message": None})

        status, _headers, body = await call("/api/v1/agents")

        assert status == 200
        assert body == b"downstream"

    async def test_a_deployment_with_no_settings_row_is_open(self, redis, row):
        row.value = None

        status, _headers, _body = await call("/api/v1/agents")

        assert status == 200


class TestAClosedDeployment:
    async def test_ordinary_traffic_is_refused(self, redis, row):
        row.value = a_closed_row()

        status, _headers, _body = await call("/api/v1/agents")

        assert status == 503

    async def test_the_refusal_is_this_apis_own_error_envelope(self, redis, row):
        """A client parsing our errors should not have to know which layer produced
        one. It is built in the middleware rather than raised, because a middleware
        sits above the exception handlers."""
        row.value = a_closed_row()

        _status, _headers, body = await call("/api/v1/agents")

        assert json.loads(body)["error"]["code"] == "MAINTENANCE_MODE"

    async def test_it_says_what_the_operator_wrote(self, redis, row):
        row.value = a_closed_row("Postgres upgrade, back at 22:00")

        _status, _headers, body = await call("/api/v1/agents")

        assert json.loads(body)["error"]["message"] == "Postgres upgrade, back at 22:00"

    async def test_a_window_with_no_message_still_says_something(self, redis, row):
        row.value = a_closed_row(None)

        _status, _headers, body = await call("/api/v1/agents")

        assert "maintenance" in json.loads(body)["error"]["message"].lower()

    async def test_it_tells_a_client_to_back_off(self, redis, row):
        """Without it a polling client hammers a deployment that is deliberately
        down, which is the traffic a maintenance window exists to stop."""
        row.value = a_closed_row()

        _status, headers, _body = await call("/api/v1/agents")

        assert headers["retry-after"] == str(RETRY_AFTER_SECONDS)

    async def test_a_websocket_connection_is_not_this_middlewares_business(self, redis, row):
        """Not an exemption - a scope that is not `http` has no response to build,
        and the socket routes refuse on their own terms."""
        row.value = a_closed_row()

        status, _headers, body = await call("/api/v1/agent/ws", scope_type="websocket")

        assert status == 200
        assert body == b"downstream"


class TestTheOperatorCanStillGetIn:
    @pytest.mark.parametrize(
        "path",
        [
            "/health",
            "/health/ready",
            "/api/v1/health",
            "/api/v1/branding",
            "/api/v1/branding/logo",
            "/api/v1/auth/login",
            "/api/v1/auth/refresh",
            "/api/v1/admin/settings",
            "/api/v1/admin/users",
            "/docs",
            "/redoc",
            "/openapi.json",
        ],
    )
    async def test_it_stays_reachable_while_the_window_is_open(self, redis, row, path):
        """Named one by one rather than by prefix: shortening this list is how an
        administrator loses the route to the switch, and the failure would only be
        discovered by somebody actually needing it."""
        row.value = a_closed_row()

        status, _headers, _body = await call(path)

        assert status == 200

    async def test_widening_the_path_does_not_widen_the_authority(self, redis, row):
        """`/api/v1/admin/*` is allowed through the gate and still refused by
        `CurrentAppAdmin` behind it. The middleware reads no session at all - doing
        so would mean verifying a token above the dependency graph."""
        row.value = a_closed_row()

        status, _headers, _body = await call("/api/v1/admin/users")

        assert status == 200

    async def test_an_allowed_path_is_not_even_checked(self, redis, row):
        """So a Redis or database problem cannot make the sign-in route unavailable
        during the one window where it is the only way in."""
        row.value = a_closed_row()

        await call("/api/v1/auth/login")

        redis.get.assert_not_called()


class TestTheCache:
    async def test_a_cached_verdict_is_not_re_read_from_the_database(self, redis, monkeypatch):
        """The middleware runs on every request and the settings row changes about
        once a quarter."""
        redis.get.return_value = json.dumps({"on": True, "message": "closed"})
        monkeypatch.setattr(maintenance, "get_db_context", _no_db)

        status, _headers, _body = await call("/api/v1/agents")

        assert status == 503

    async def test_a_miss_reads_through_and_writes_what_it_found(self, redis, row):
        row.value = a_closed_row()

        await call("/api/v1/agents")

        written = json.loads(redis.set.await_args.args[1])
        assert written == {"on": True, "message": "Back at 22:00"}
        assert redis.set.await_args.kwargs["ttl"] == CACHE_TTL_SECONDS

    async def test_it_carries_a_ttl_so_a_lost_write_heals_itself(self, redis, row):
        """The eager publish on save is what makes the switch feel immediate; this is
        the net under it, and without a TTL a write that never reached Redis leaves
        the deployment open through a window somebody scheduled."""
        row.value = a_closed_row()

        await call("/api/v1/agents")

        assert redis.set.await_args.kwargs["ttl"] > 0

    async def test_publishing_with_no_redis_configured_is_not_an_error(self):
        """A test client and any process that never ran the lifespan are in this
        state, and they read the row every time instead - correct and slower, rather
        than a second behaviour."""
        maintenance.configure(None)

        await maintenance.publish(on=True, message="x")

    async def test_a_redis_that_cannot_be_written_does_not_fail_the_save(self, redis):
        """The database is the truth and this is derived, so an administrator's save
        must not fail on a cache. What it costs is bounded by the TTL."""
        redis.set.side_effect = ConnectionError("down")

        await maintenance.publish(on=True, message="x")

    async def test_with_no_redis_at_all_it_reads_the_row_every_time(self, row):
        """The state of a test client and of any process that never ran the lifespan.
        Correct and slower, rather than a gate that stops working without a cache."""
        maintenance.configure(None)
        row.value = a_closed_row()

        status, _headers, _body = await call("/api/v1/agents")

        assert status == 503

    async def test_a_redis_that_cannot_be_read_falls_back_to_the_row(self, redis, row):
        redis.get.side_effect = ConnectionError("down")
        row.value = a_closed_row()

        status, _headers, _body = await call("/api/v1/agents")

        assert status == 503

    async def test_the_key_is_one_name_the_whole_deployment_shares(self):
        """Every worker reads the same verdict, which is the point of putting it in
        the Redis they already share rather than in each process."""
        assert CACHE_KEY == "deployment:maintenance"


class TestItFailsOpen:
    async def test_a_gate_that_cannot_read_its_switch_lets_traffic_through(
        self, redis, row, monkeypatch
    ):
        """Failing shut would turn a Redis blip, or a migration that has not run yet,
        into a total outage nobody asked for."""
        redis.get.return_value = None
        monkeypatch.setattr(
            maintenance,
            "deployment_settings_repo",
            MagicMock(get=AsyncMock(side_effect=RuntimeError("relation does not exist"))),
        )

        status, _headers, body = await call("/api/v1/agents")

        assert status == 200
        assert body == b"downstream"
