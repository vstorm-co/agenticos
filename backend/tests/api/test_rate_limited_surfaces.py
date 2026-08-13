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
        """A 429 with no interval is a client's excuse to retry immediately - in
        the Retry-After header a standard client reads, as well as the body."""
        rate_limit.configure(_redis(used=999))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/api/v1/agents/{uuid4()}/run", json={"prompt": "hello"})

        assert response.json()["error"]["details"]["retry_after_seconds"] == 60
        assert response.headers["Retry-After"] == "60"

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
        assert response.headers["Retry-After"] == "60"

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
        and the last one to get a gate.
        """
        app.dependency_overrides[deps.get_redis] = lambda: mock_redis
        app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
        rate_limit.configure(_redis(used=999))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/embed/some-key/logo")

        assert response.status_code == 429

    async def test_the_logo_is_counted_against_the_page_not_the_caller(self, mock_redis: MagicMock):
        """The browser fetches the logo from the page's own origin, so the request
        reaching here is the frontend server's `fetch` and its address is the
        container's - counted per address it was one bucket for every hosted
        page's logo at once. Its own surface, so logo and config do not spend each
        other's allowance.
        """
        app.dependency_overrides[deps.get_redis] = lambda: mock_redis
        app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
        client_mock = _redis(used=1)
        rate_limit.configure(client_mock)

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as client:
            await client.get("/api/v1/embed/some-key/logo")

        assert client_mock.count_in_window.await_args.args[0] == (
            "ratelimit:hosted_logo:key:some-key"
        )

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

    @pytest.mark.parametrize(
        "path", ["some-key/config", "some-key/hosted", "some-key/logo", "some-key/widget.js"]
    )
    async def test_every_refusal_here_is_the_envelope_the_rest_of_the_api_answers(
        self, mock_redis: MagicMock, path: str
    ):
        """These five routes raised a bare `HTTPException`, so they answered
        `{"detail": ...}` where every other error on this API - including the run
        route's own 429 above - answers `{"error": {"code", "message", "details"}}`.
        #516 published this socket as an integration somebody writes a client
        against, and a client should not need to know which route refused it to
        parse the refusal. The interval travels the same way rather than as a
        hardcoded header, so a `Limit` with a different window cannot make it a lie.
        """
        app.dependency_overrides[deps.get_redis] = lambda: mock_redis
        app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
        rate_limit.configure(_redis(used=999))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/embed/{path}")

        assert response.status_code == 429
        assert response.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert response.json()["error"]["details"]["retry_after_seconds"] == 60
        assert response.headers["Retry-After"] == "60"

    async def test_the_script_does_not_spend_the_allowance_admission_needs(
        self, mock_redis: MagicMock
    ):
        """All three shared one key, so a widget page load spent the script, the
        config and the handshake out of one number: twenty admissions a minute was
        about seven page loads for a cold browser. A limit wrong by a factor of
        three is worse than none, because it reads as the number that was set.
        """
        app.dependency_overrides[deps.get_redis] = lambda: mock_redis
        app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
        client_mock = _redis(used=1)
        rate_limit.configure(client_mock)

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as client:
            await client.get("/api/v1/embed/some-key/widget.js")
            script_key = client_mock.count_in_window.await_args.args[0]
            await client.get("/api/v1/embed/some-key/config")
            config_key = client_mock.count_in_window.await_args.args[0]

        assert script_key.startswith("ratelimit:embed_script:ip:")
        assert config_key.startswith("ratelimit:embed_admission:ip:")

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
