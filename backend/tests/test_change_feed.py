"""Change feed paths the end-to-end tests do not reach (#2061): which writes are
changes, what happens without Redis, and the traffic the middleware leaves alone."""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import Response, StreamingResponse
from httpx import ASGITransport, AsyncClient
from starlette.middleware.gzip import GZipMiddleware

from app.api.public_api import PUBLIC
from app.api.routes.v1.change_events import change_events
from app.clients.redis import RedisClient
from app.core.config import settings
from app.schemas.change_event import ChangeEvent
from app.services import change_feed
from app.services.change_feed import ChangeFeedMiddleware, ChangeOrigin, change_for

pytestmark = pytest.mark.anyio

V1 = settings.API_V1_STR
ORIGIN = ChangeOrigin(
    organization_id=uuid.uuid4(), actor_user_id=uuid.uuid4(), actor_name="Ada", surface="mcp"
)


def _change(
    method: str, path: str, params: dict[str, Any], body: bytes = b""
) -> ChangeEvent | None:
    return change_for(method=method, path=V1 + path, path_params=params, origin=ORIGIN, body=body)


@pytest.fixture
def redis() -> Any:
    client = MagicMock(spec=RedisClient)
    client.raw = MagicMock()
    client.raw.publish = AsyncMock()
    change_feed.configure(client)
    yield client
    change_feed.configure(None)


class TestWhatIsAChange:
    def test_running_or_validating_an_agent_changes_nothing(self) -> None:
        agent_id = str(uuid.uuid4())

        assert _change("POST", f"/agents/{agent_id}/run", {"agent_id": agent_id}) is None
        assert _change("POST", f"/agents/{agent_id}/validate", {"agent_id": agent_id}) is None

    @pytest.mark.parametrize("prefix", ["/apps", "/artifacts"])
    def test_following_a_page_is_the_follower_s_business(self, prefix: str) -> None:
        artifact_id = str(uuid.uuid4())

        followed = _change("PUT", f"{prefix}/{artifact_id}/follow", {"artifact_id": artifact_id})

        assert followed is None

    @pytest.mark.parametrize("prefix", ["/apps", "/artifacts"])
    def test_an_app_changed_at_either_path_is_announced(self, prefix: str) -> None:
        """`/artifacts` is the deprecated alias of `/apps` (#2071); both are changes."""
        artifact_id = uuid.uuid4()

        changed = _change("PATCH", f"{prefix}/{artifact_id}", {"artifact_id": str(artifact_id)})

        assert changed is not None
        assert (changed.resource, changed.id) == ("artifact", artifact_id)

    def test_a_route_outside_the_feed_changes_nothing(self) -> None:
        assert _change("POST", "/ml/privacy/pii", {}) is None

    def test_a_clone_is_a_new_agent_read_from_the_answer(self) -> None:
        source, copy = str(uuid.uuid4()), uuid.uuid4()

        cloned = _change(
            "POST", f"/agents/{source}/clone", {"agent_id": source}, f'{{"id": "{copy}"}}'.encode()
        )

        assert cloned is not None
        assert (cloned.resource, cloned.id, cloned.action) == ("agent", copy, "created")

    def test_a_create_whose_answer_names_no_row_is_announced_without_one(self) -> None:
        for body in (b"", b"[]", b'{"id": "not-a-uuid"}', b"\x89PNG"):
            created = _change("POST", "/kb", {}, body)
            assert created is not None
            assert (created.id, created.action) == (None, "created")

    def test_removing_a_row_s_child_updates_the_row(self) -> None:
        kb_id, doc_id = str(uuid.uuid4()), str(uuid.uuid4())

        removed = _change(
            "DELETE", f"/kb/{kb_id}/documents/{doc_id}", {"kb_id": kb_id, "doc_id": doc_id}
        )

        assert removed is not None
        assert (removed.resource, str(removed.id), removed.action) == (
            "knowledge_base",
            kb_id,
            "updated",
        )

    def test_the_assistant_s_settings_are_a_change_to_the_organization(self) -> None:
        """Codex on #2062: other tabs kept the old greeting, model or switch."""
        changed = _change("PATCH", "/assistant", {})

        assert changed is not None
        assert (changed.resource, changed.action) == ("organization", "updated")

    def test_a_member_and_the_organization_are_told_apart(self) -> None:
        org_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())

        removed = _change(
            "DELETE",
            f"/orgs/{org_id}/members/{user_id}",
            {"org_id": org_id, "target_user_id": user_id},
        )
        retention = _change("PUT", f"/orgs/{org_id}/retention", {"org_id": org_id})

        assert removed is not None and retention is not None
        assert (removed.resource, str(removed.id), removed.action) == ("member", user_id, "deleted")
        assert (retention.resource, str(retention.id), retention.action) == (
            "organization",
            org_id,
            "updated",
        )


class TestConsoleOnlyRoutes:
    def test_stopping_a_parked_run_announces_its_updated_state(self) -> None:
        run = uuid.uuid4()
        changed = _change("POST", f"/runs/{run}/cancel", {"run_id": str(run)})
        assert changed is not None
        assert (changed.resource, changed.id, changed.action) == ("run", run, "updated")

    """The routes only the console calls, which publish since #2099."""

    @pytest.mark.parametrize(
        ("prefix", "resource"),
        [
            ("/agents", "agent"),
            ("/skills", "skill"),
            ("/context", "context"),
            ("/kb", "knowledge_base"),
            ("/apps", "artifact"),
            ("/artifacts", "artifact"),
            ("/secrets", "secret"),
            ("/mcp-connections", "mcp_connection"),
        ],
    )
    def test_sharing_a_row_updates_that_row(self, prefix: str, resource: str) -> None:
        row, person = uuid.uuid4(), str(uuid.uuid4())

        granted = _change("PUT", f"{prefix}/{row}/sharing/grants", {"resource_id": str(row)})
        revoked = _change(
            "DELETE",
            f"{prefix}/{row}/sharing/grants/{person}",
            {"resource_id": str(row), "subject_user_id": person},
        )

        for change in (granted, revoked):
            assert change is not None
            assert (change.resource, change.id, change.action) == (resource, row, "updated")

    def test_a_routine_changed_names_the_agent_it_belongs_to(self) -> None:
        agent, trigger = uuid.uuid4(), str(uuid.uuid4())
        params = {"agent_id": str(agent), "trigger_id": trigger}

        created = _change("POST", f"/agents/{agent}/triggers", {"agent_id": str(agent)})
        removed = _change("DELETE", f"/agents/{agent}/triggers/{trigger}", params)
        fired = _change("POST", f"/agents/{agent}/triggers/{trigger}/run", params)

        for change in (created, removed):
            assert change is not None
            assert (change.resource, change.id, change.action) == ("trigger", agent, "updated")
        assert fired is None

    def test_an_embed_is_not_an_agent(self) -> None:
        embed = str(uuid.uuid4())

        assert _change("POST", "/agents/embeds", {}, f'{{"id": "{embed}"}}'.encode()) is None
        assert _change("PATCH", f"/agents/embeds/{embed}", {"embed_id": embed}) is None

    def test_starting_an_oauth_dance_or_probing_a_server_changes_nothing(self) -> None:
        server = str(uuid.uuid4())

        assert _change("POST", "/mcp-connections/oauth/start", {}) is None
        assert _change("POST", f"/mcp-connections/{server}/test", {"connection_id": server}) is None

    def test_a_channel_bot_is_created_and_removed(self) -> None:
        bot = uuid.uuid4()

        created = _change("POST", "/channels/bots", {}, f'{{"id": "{bot}"}}'.encode())
        removed = _change("DELETE", f"/channels/bots/{bot}", {"bot_id": str(bot)})

        assert created is not None and removed is not None
        assert (created.resource, created.id, created.action) == ("channel", bot, "created")
        assert (removed.id, removed.action) == (bot, "deleted")

    def test_an_inbox_written_in_bulk_names_no_row(self) -> None:
        """Marking everything read answers with a count, not a row it created."""
        for path in ("/notifications/mark-all-read", "/notifications/preferences"):
            changed = _change("POST", path, {}, b'{"id": "not-a-row", "count": 3}')
            assert changed is not None
            assert (changed.resource, changed.id, changed.action) == (
                "notification",
                None,
                "updated",
            )


class TestRuns:
    def test_a_run_event_is_the_run_s_own_and_names_no_one_as_its_author(self) -> None:
        run = MagicMock(organization_id=uuid.uuid4(), id=uuid.uuid4(), user_id=None)

        event = change_feed.run_event(run, "created")

        assert (event.resource, event.id, event.action) == ("run", run.id, "created")
        assert (event.surface, event.actor_user_id, event.actor_name) == ("run", None, None)
        assert event.organization_id == run.organization_id

    async def test_a_run_s_change_is_published_to_its_organization(self, redis: Any) -> None:
        run = MagicMock(organization_id=uuid.uuid4(), id=uuid.uuid4(), user_id=uuid.uuid4())

        await change_feed.publish_run(run, "updated")

        [call] = redis.raw.publish.await_args_list
        assert call.args[0] == f"changes:{run.organization_id}"
        assert ChangeEvent.model_validate_json(call.args[1]).actor_user_id == run.user_id

    async def test_without_redis_a_run_is_not_even_read(self) -> None:
        """On every run's path: a process with nothing to publish to does no work."""
        change_feed.configure(None)
        run = MagicMock(spec=[])

        await change_feed.publish_run(run, "created")

    async def test_a_worker_connects_once_and_keeps_its_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A routine's run publishes from the worker, which the API lifespan
        never configured."""
        made: list[MagicMock] = []

        def client() -> MagicMock:
            made.append(MagicMock(spec=RedisClient, connect=AsyncMock()))
            return made[-1]

        monkeypatch.setattr(change_feed, "RedisClient", client)
        change_feed.configure(None)
        try:
            await change_feed.connect_in_worker()
            await change_feed.connect_in_worker()
        finally:
            connected = change_feed._redis
            change_feed.configure(None)

        assert len(made) == 1
        made[0].connect.assert_awaited_once()
        assert connected is made[0]


class TestPublishing:
    async def test_without_redis_nothing_is_published_and_nothing_fails(self) -> None:
        change_feed.configure(None)
        event = _change("POST", "/kb", {})
        assert event is not None

        await change_feed.publish(event)

    async def test_a_publish_that_fails_is_logged_not_raised(
        self, redis: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        redis.raw.publish.side_effect = ConnectionError("redis is down")
        event = _change("POST", "/kb", {})
        assert event is not None

        await change_feed.publish(event)

        assert "change_feed_publish_failed" in caplog.text

    async def test_a_socket_without_redis_is_closed_rather_than_left_silent(self) -> None:
        change_feed.configure(None)
        socket = MagicMock()
        socket.close = AsyncMock()

        await change_feed.stream_changes(socket, organization_id=uuid.uuid4(), auth_token="t")

        socket.close.assert_awaited_once_with(code=1011, reason="Live updates are unavailable")


def _app() -> FastAPI:
    """A public and a console-only write, each recording a change origin the way
    the auth dependencies do."""
    app = FastAPI()
    public = APIRouter(dependencies=[PUBLIC])
    console = APIRouter()

    @public.post("/kb")
    async def create(request: Request) -> dict[str, str]:
        request.state.change_origin = ORIGIN
        return {"id": str(uuid.uuid4())}

    @public.post("/kb/anonymous")
    async def anonymous() -> dict[str, str]:
        return {}

    @console.post("/context")
    async def console_only(request: Request) -> dict[str, str]:
        request.state.change_origin = ORIGIN
        return {"id": str(uuid.uuid4())}

    @public.post("/ml/pii")
    async def analyse(request: Request) -> dict[str, str]:
        request.state.change_origin = ORIGIN
        return {}

    @public.post("/skills")
    async def oversized(request: Request) -> StreamingResponse:
        request.state.change_origin = ORIGIN
        head = f'{{"id": "{LONG_ID}", "body": "'.encode()
        return StreamingResponse(iter([head, b"x" * 200_000, b"x" * 200_000, b'"}']))

    @public.post("/apps")
    async def oversized_without_a_leading_id(request: Request) -> StreamingResponse:
        request.state.change_origin = ORIGIN
        head = f'{{"body": "{uuid.uuid4()}'.encode()
        return StreamingResponse(iter([head, b"x" * 300_000, f'", "id": "{LONG_ID}"}}'.encode()]))

    @public.get("/kb")
    async def read(request: Request) -> dict[str, str]:
        request.state.change_origin = ORIGIN
        return {}

    app.include_router(public, prefix=V1)
    app.include_router(console, prefix=V1)
    app.add_middleware(ChangeFeedMiddleware)
    return app


LONG_ID = uuid.uuid4()


class TestMiddleware:
    async def test_every_write_by_a_known_caller_is_published(self, redis: Any) -> None:
        """A console-only route publishes as a public one does (#2099): sharing and
        routines are written through routes no API key may call."""
        async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as http:
            await http.get(f"{V1}/kb")
            await http.post(f"{V1}/kb/anonymous")
            console = await http.post(f"{V1}/context")
            await http.post(f"{V1}/ml/pii")
            created = await http.post(f"{V1}/kb")

        channels, events = zip(
            *(
                (call.args[0], ChangeEvent.model_validate_json(call.args[1]))
                for call in redis.raw.publish.await_args_list
            ),
            strict=True,
        )
        assert set(channels) == {f"changes:{ORIGIN.organization_id}"}
        assert [(event.resource, str(event.id)) for event in events] == [
            ("context", console.json()["id"]),
            ("knowledge_base", created.json()["id"]),
        ]

    async def test_a_long_answer_is_still_read_for_the_id_it_opens_with(self, redis: Any) -> None:
        """Codex on #2062: a create answering past the limit published no id, and a
        reader who sees only their own rows was never told of it."""
        async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as http:
            await http.post(f"{V1}/skills")
            await http.post(f"{V1}/apps")

        skill, app = (
            ChangeEvent.model_validate_json(call.args[1])
            for call in redis.raw.publish.await_args_list
        )
        assert (skill.resource, skill.id) == ("skill", LONG_ID)
        # An id further in than was kept is not guessed at.
        assert (app.resource, app.id) == ("artifact", None)

    async def test_lifespan_and_socket_traffic_passes_straight_through(self) -> None:
        inner = AsyncMock()
        middleware = ChangeFeedMiddleware(inner)
        receive, send = AsyncMock(), AsyncMock()

        await middleware({"type": "lifespan"}, receive, send)

        inner.assert_awaited_once_with({"type": "lifespan"}, receive, send)


def _compressing_app() -> FastAPI:
    """The real stacking: GZip inside the change feed, so a create's answer
    reaches the feed compressed."""
    app = FastAPI()
    public = APIRouter(dependencies=[PUBLIC])
    created = str(uuid.uuid4())

    @public.post("/kb")
    async def create(request: Request) -> dict[str, str]:
        request.state.change_origin = ORIGIN
        return {"id": created, "description": "x" * 4096}

    @public.post("/skills")
    async def mislabelled(request: Request) -> Response:
        request.state.change_origin = ORIGIN
        return Response(b"not gzip at all", headers={"content-encoding": "gzip"})

    app.include_router(public, prefix=V1)
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(ChangeFeedMiddleware)
    app.state.created = created
    return app


class TestCompressedAnswers:
    async def test_a_compressed_create_is_read_for_its_id(self, redis: Any) -> None:
        app = _compressing_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as http:
            answer = await http.post(f"{V1}/kb", headers={"Accept-Encoding": "gzip"})

        assert answer.headers["content-encoding"] == "gzip"
        [call] = redis.raw.publish.await_args_list
        assert str(ChangeEvent.model_validate_json(call.args[1]).id) == app.state.created

    async def test_an_answer_that_will_not_inflate_names_no_row(self, redis: Any) -> None:
        transport = ASGITransport(app=_compressing_app())
        # Raw: the client would refuse to inflate it too.
        async with (
            AsyncClient(transport=transport, base_url="http://t") as http,
            http.stream("POST", f"{V1}/skills") as answer,
        ):
            [chunk async for chunk in answer.aiter_raw()]

        [call] = redis.raw.publish.await_args_list
        assert ChangeEvent.model_validate_json(call.args[1]).id is None


class TestRoute:
    async def test_the_socket_is_accepted_on_the_negotiated_subprotocol_then_streamed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stream = AsyncMock()
        monkeypatch.setattr(change_feed, "stream_changes", stream)
        socket = MagicMock()
        socket.accept = AsyncMock()
        socket.state.accept_subprotocol = "events"
        socket.state.auth_token = "token"
        organization = MagicMock(id=uuid.uuid4())

        await change_events(socket, organization)

        socket.accept.assert_awaited_once_with(subprotocol="events")
        stream.assert_awaited_once_with(socket, organization_id=organization.id, auth_token="token")


class TestTheTab:
    def test_a_well_formed_tab_id_is_echoed_and_anything_else_is_dropped(self) -> None:
        tab = str(uuid.uuid4())

        assert change_feed.console_tab(tab) == tab
        assert change_feed.console_tab(None) is None
        assert change_feed.console_tab("x" * 65) is None
        assert change_feed.console_tab("<script>") is None

    def test_the_change_carries_the_tab_that_made_it(self) -> None:
        origin = ChangeOrigin(
            organization_id=uuid.uuid4(),
            actor_user_id=uuid.uuid4(),
            actor_name="Ada",
            surface="console",
            tab="tab-1",
        )

        event = change_for(method="POST", path=f"{V1}/kb", path_params={}, origin=origin, body=b"")

        assert event is not None and event.origin_tab == "tab-1"
