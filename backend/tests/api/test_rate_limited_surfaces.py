"""Which routes the rate limit is actually wired to.

`app/services/rate_limit.py` is tested on its own; this asserts the part that
was missing for the whole life of the product. The limiter that existed before
#39 was configured, registered on the app and reached by no route, and nothing
failed - which is precisely why the wiring needs a test of its own rather than
being taken on trust from a decorator being present in a diff.

Both halves are here on purpose: that a public surface refuses, and that the
console's own routes do not. "Limits apply to the public surfaces" is a product
decision, and a blanket middleware quietly metering the dashboard would be a
different one.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.api.routes.v1.embed import embed_socket
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.services import rate_limit

pytestmark = pytest.mark.anyio

_CALLER = uuid4()
_ORGANIZATION = uuid4()


@pytest.fixture(autouse=True)
def _no_limiter():
    rate_limit.configure(None)
    yield
    rate_limit.configure(None)
    app.dependency_overrides.clear()


def _redis(used: int) -> MagicMock:
    """A limiter whose window already holds `used` attempts including this one."""
    client = MagicMock()
    client.count_in_window = AsyncMock(return_value=used)
    return client


@pytest.fixture
def signed_in(mock_redis: MagicMock):
    context = AuthContext(
        user_id=_CALLER, organization_id=_ORGANIZATION, role=OrgRoleName.OWNER.value
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
    return context


class TestThePublicRunApi:
    async def test_a_caller_over_its_allowance_is_refused_with_429(self, signed_in):
        rate_limit.configure(_redis(used=999))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/api/v1/agents/{uuid4()}/run", json={"prompt": "hello"})

        assert response.status_code == 429
        assert response.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"

    async def test_the_refusal_says_when_to_come_back(self, signed_in):
        """A 429 with no interval is a client's excuse to retry immediately."""
        rate_limit.configure(_redis(used=999))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/api/v1/agents/{uuid4()}/run", json={"prompt": "hello"})

        assert response.json()["error"]["details"]["retry_after_seconds"] == 60

    async def test_the_allowance_is_counted_against_the_caller_not_their_address(self, signed_in):
        """An office behind one NAT is not one caller. Keyed on the address, the
        limit would be an outage wearing a limit's clothes.

        The request is allowed through and then fails inside the handler, which
        has no real service behind it - `raise_app_exceptions=False` because what
        is under test is the key the gate counted, not the run.
        """
        client_mock = _redis(used=1)
        rate_limit.configure(client_mock)

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as client:
            await client.post(f"/api/v1/agents/{uuid4()}/run", json={"prompt": "hello"})

        assert client_mock.count_in_window.await_args.args[0] == (
            f"ratelimit:agent_run:user:{_CALLER}"
        )

    async def test_the_console_routes_are_not_metered(self, signed_in):
        """Public surfaces only. A blanket middleware would have limited the
        dashboard too, which is a different decision with its own issue."""
        client_mock = _redis(used=999)
        rate_limit.configure(client_mock)

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/agents")

        assert response.status_code != 429
        client_mock.count_in_window.assert_not_awaited()


class TestTheWidgetsAdmission:
    async def test_a_config_request_over_the_allowance_is_refused(self, mock_redis: MagicMock):
        app.dependency_overrides[deps.get_redis] = lambda: mock_redis
        app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
        rate_limit.configure(_redis(used=999))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/embed/some-key/config")

        assert response.status_code == 429

    async def test_the_hosted_page_is_counted_against_the_page_not_the_caller(
        self, mock_redis: MagicMock
    ):
        """The wiring half of the per-page limit, because the address on this
        request belongs to the frontend server rather than to a visitor: counted
        per address it was one bucket for every hosted page in the deployment, and
        the eleventh visitor of the minute was served a 404 by the page.
        """
        app.dependency_overrides[deps.get_redis] = lambda: mock_redis
        app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
        client_mock = _redis(used=1)
        rate_limit.configure(client_mock)

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as client:
            await client.get("/api/v1/embed/some-key/hosted")

        assert client_mock.count_in_window.await_args.args[0] == (
            "ratelimit:hosted_config:key:some-key"
        )

    async def test_a_hosted_page_over_its_allowance_is_refused(self, mock_redis: MagicMock):
        app.dependency_overrides[deps.get_redis] = lambda: mock_redis
        app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
        rate_limit.configure(_redis(used=999))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/embed/some-key/hosted")

        assert response.status_code == 429

    async def test_the_logo_is_gated_too(self, mock_redis: MagicMock):
        """The most expensive public route here - two queries, a stat and a file -
        and the last one to get a gate. Per address, because unlike `/hosted`
        beside it this one is fetched by the visitor's own browser as an `<img>`.
        """
        app.dependency_overrides[deps.get_redis] = lambda: mock_redis
        app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
        rate_limit.configure(_redis(used=999))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/embed/some-key/logo")

        assert response.status_code == 429

    async def test_the_widget_script_is_gated_too(self, mock_redis: MagicMock):
        """ "Static script" is what it looks like from outside. From in here it is
        a row read per request, and a five-minute cache is a browser's courtesy
        rather than a ceiling a caller has to respect.
        """
        app.dependency_overrides[deps.get_redis] = lambda: mock_redis
        app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
        rate_limit.configure(_redis(used=999))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/embed/some-key/widget.js")

        assert response.status_code == 429

    async def test_a_socket_over_the_allowance_closes_with_its_own_code(self):
        """4029, not 4003. "Not allowed here" and "allowed but too fast" ask a
        client for opposite things - stop for ever, and retry later - so a client
        that cannot tell them apart either hammers a refusal or abandons a limit.

        The handler is called directly rather than through a client: the async
        client speaks no WebSocket, and `TestClient` would run the lifespan,
        which replaces the limiter under test with the deployment's own. Nothing
        here reaches the database, which is the point - the limit is counted
        before the key is looked up, so an unbounded probe for live keys is not
        free.
        """
        rate_limit.configure(_redis(used=999))
        socket = MagicMock(headers={}, client=MagicMock(host="203.0.113.9"))
        socket.accept = AsyncMock()
        socket.close = AsyncMock()

        await embed_socket(websocket=socket, public_key="k", token=None)

        assert socket.close.await_args.kwargs["code"] == 4029
        socket.receive_json.assert_not_called()
