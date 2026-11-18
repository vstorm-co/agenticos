"""Cached pictures and concurrent event teardown cannot resurrect protected page output."""

import asyncio
import base64
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RunUsage
from redis.exceptions import RedisError

from app.agents.browser_events import BrowserEvent
from app.agents.capabilities.browser_use import _toolset as toolset_module
from app.agents.capabilities.browser_use._page import CdpPage, PagePolicy
from app.agents.capabilities.browser_use._protected import BrowserOutputGuard
from app.agents.capabilities.browser_use._toolset import _live
from app.agents.deps import AgentDeps
from app.services import live_browse
from tests.test_browser_credentials import PASSWORD
from tests.test_browser_use import DONE_ARGS, _browsing_model, _policy, _snapshot
from tests.test_live_browse import CALL, RUN, _access, _meta, _Pipe, _Socket, _Store

pytestmark = [pytest.mark.anyio, pytest.mark.security]
ORIGIN = "https://portal.example.test"


class ProtectedPipe(_Pipe):
    async def execute(self) -> None:
        for name, args in self.ops:
            if name == "delete":
                for key in args:
                    self.store.values.pop(key, None)
                    self.store.lists.pop(key, None)
        await super().execute()


class ProtectedStore(_Store):
    def pipeline(self, *, transaction: bool = False):
        return ProtectedPipe(self)


def protected_event() -> BrowserEvent:
    return BrowserEvent(
        kind="browser_protected",
        call_id="call",
        step=0,
        url=ORIGIN,
        title="Protected browser session",
        output_protected=True,
    )


async def test_protection_removes_old_frame_location_and_trace_before_announcing(
    monkeypatch,
) -> None:
    store = ProtectedStore()
    monkeypatch.setattr(live_browse, "_redis", SimpleNamespace(raw=store))
    frame, location, trace = (
        live_browse._key("run", "call", part) for part in ("frame", "location", "trace")
    )
    store.values.update({frame: PASSWORD, location: PASSWORD})
    store.lists[trace] = [PASSWORD]
    event = protected_event()
    await live_browse.protect_view("run", "call", event)
    assert frame not in store.values
    assert store.values[location] == event.model_dump_json()
    assert store.lists[trace] == [event.model_dump_json()]
    assert store.published == [(live_browse._key("run", "call", "events"), event.model_dump_json())]
    assert PASSWORD not in repr(store.values) + repr(store.lists) + repr(store.published)
    assert live_browse.credential_redis().raw is store


@pytest.mark.parametrize("failure", ["unconfigured", "wrong_event", "image", "redis_error"])
async def test_protection_failure_is_not_swallowed_or_logged_as_success(
    monkeypatch, caplog, failure
) -> None:
    store = ProtectedStore()
    client = SimpleNamespace(raw=store)
    monkeypatch.setattr(live_browse, "_redis", None if failure == "unconfigured" else client)
    event = protected_event()
    if failure == "wrong_event":
        event = event.model_copy(update={"kind": "browser_frame"})
    elif failure == "image":
        event = event.model_copy(update={"image": base64.b64encode(PASSWORD.encode()).decode()})
    elif failure == "redis_error":
        pipe = ProtectedPipe(store)
        pipe.execute = AsyncMock(side_effect=RedisError(PASSWORD))
        monkeypatch.setattr(store, "pipeline", lambda **kwargs: pipe)
    with pytest.raises((RuntimeError, RedisError)):
        await live_browse.protect_view("run", "call", event)
    assert PASSWORD not in caplog.text
    assert store.published == []


async def make_sink(monkeypatch, guard: BrowserOutputGuard):
    deps = SimpleNamespace(
        browser_events=AsyncMock(),
        run_id=uuid4(),
        organization_id=uuid4(),
        agent_id=uuid4(),
        user_id=str(uuid4()),
        audience=None,
    )
    monkeypatch.setattr(live_browse, "available", lambda: True)
    monkeypatch.setattr(live_browse, "open_view", AsyncMock())
    monkeypatch.setattr(live_browse, "has_viewers", AsyncMock(return_value=False))
    monkeypatch.setattr(live_browse, "publish", AsyncMock())
    monkeypatch.setattr(live_browse, "protect_view", AsyncMock())
    sink, _, _ = await _live(deps, "call", "Synthetic private task", lambda: guard)
    return sink, deps.browser_events


async def test_cached_last_picture_is_cleared_and_never_replayed_on_teardown(monkeypatch) -> None:
    guard = BrowserOutputGuard()
    sink, chat = await make_sink(monkeypatch, guard)
    frame = BrowserEvent(
        kind="browser_frame",
        call_id="call",
        step=0,
        image=base64.b64encode(PASSWORD.encode()).decode(),
        url=ORIGIN + "/" + PASSWORD,
        title=PASSWORD,
    )
    assert await sink(frame) is False
    live_browse.publish.assert_not_awaited()
    guard.protect(ORIGIN)
    await sink(protected_event())
    await sink(frame)
    await sink(BrowserEvent(kind="browser_finished", call_id="call", step=1, reason=PASSWORD))
    live_browse.protect_view.assert_awaited_once()
    for call in live_browse.publish.await_args_list + chat.await_args_list:
        event = call.args[-1]
        assert event.image is None
        assert PASSWORD not in event.model_dump_json()
        assert event.url == ORIGIN
    assert live_browse.publish.await_count == 2


@pytest.mark.parametrize("different_view", [False, True])
async def test_pending_publication_settles_before_clear_and_late_frames_remain_sanitized(
    monkeypatch,
    different_view,
) -> None:
    guard = BrowserOutputGuard()
    sink, _ = await make_sink(monkeypatch, guard)
    protected_sink = (await make_sink(monkeypatch, guard))[0] if different_view else sink
    started, release = asyncio.Event(), asyncio.Event()
    order = []

    async def publish(*args):
        order.append("earlier frame")
        started.set()
        await release.wait()

    async def protect(*args):
        order.append("clear cached output")

    live_browse.publish.side_effect = publish
    live_browse.protect_view.side_effect = protect
    live_browse.has_viewers.return_value = True
    old = asyncio.create_task(
        sink(BrowserEvent(kind="browser_frame", call_id="call", step=0, image="c3ludGhldGlj"))
    )
    await started.wait()
    guard.protect(ORIGIN)
    protected = asyncio.create_task(protected_sink(protected_event()))
    await asyncio.sleep(0)
    assert order == ["earlier frame"] and not protected.done()
    release.set()
    await old
    await protected
    assert order == ["earlier frame"] + ["clear cached output"] * (2 if different_view else 1)


@pytest.mark.parametrize("first_tool", ["browse_web", "browser_open"])
async def test_first_page_sinks_stay_protected_after_fill_tab_switch_and_close(
    monkeypatch, first_tool
) -> None:
    """Exercise first-open and credential-tool plumbing, with no native writes."""
    published, chat, protect_view = AsyncMock(), AsyncMock(return_value=True), AsyncMock()
    monkeypatch.setattr(live_browse, "available", lambda: True)
    monkeypatch.setattr(live_browse, "open_view", AsyncMock())
    monkeypatch.setattr(live_browse, "has_viewers", AsyncMock(return_value=False))
    monkeypatch.setattr(live_browse, "publish", published)
    monkeypatch.setattr(live_browse, "protect_view", protect_view)
    monkeypatch.setattr(live_browse, "credential_redis", lambda: object())
    sinks, pages = [], []

    async def capture_sink(*args, **kwargs):
        result = await _live(*args, **kwargs)
        assert result[0] is not None
        sinks.append(result[0])
        return result

    monkeypatch.setattr(toolset_module, "_live", capture_sink)

    @asynccontextmanager
    async def open_page(**kwargs):
        page = CdpPage(MagicMock(), str(uuid4()), PagePolicy(None, 60, 1024))
        page.snapshot = AsyncMock(return_value=_snapshot(text="Synthetic page"))
        page.location = AsyncMock(return_value=(ORIGIN, "Synthetic page"))
        pages.append(page)
        yield page

    raw_frame = BrowserEvent(
        kind="browser_frame",
        call_id="first",
        step=0,
        image=base64.b64encode(PASSWORD.encode()).decode(),
        url=ORIGIN + "/" + PASSWORD,
        title=PASSWORD,
    )

    async def browse(*, sink, session, **kwargs):
        session.last = await session.page.snapshot()
        # The earlier view must be registered for the later view's protection,
        # including its cached final image without an attached viewer.
        assert not await sink(raw_frame)
        return SimpleNamespace(
            outcome="done", steps=0, text="Synthetic result", page="Synthetic page"
        )

    monkeypatch.setattr(toolset_module, "run_browse", browse)
    controllers = []

    async def create_controller(**kwargs):
        async def request(*args):
            await kwargs["protect"](ORIGIN)
            return SimpleNamespace(id=uuid4())

        controller = SimpleNamespace(
            alive=True,
            ctx=None,
            redis=kwargs["redis"],
            identity=SimpleNamespace(
                run_id=uuid4(), call_id=kwargs["call_id"], tab_id=kwargs["tab_id"]
            ),
            request=AsyncMock(side_effect=request),
            wait=AsyncMock(return_value="Credential fill completed."),
            close=AsyncMock(),
        )
        controllers.append(controller)
        return controller

    monkeypatch.setattr(toolset_module.BrowserCredentialController, "create", create_controller)
    monkeypatch.setattr(
        toolset_module.BrowserCredentialPlanService, "eligible", AsyncMock(return_value=[])
    )

    @asynccontextmanager
    async def database():
        yield None

    monkeypatch.setattr(toolset_module, "get_db_context", database)
    ctx = RunContext(
        deps=AgentDeps(
            run_id=uuid4(), organization_id=uuid4(), agent_id=uuid4(), browser_events=chat
        ),
        model=_browsing_model(DONE_ARGS),
        usage=RunUsage(),
        tool_call_id="first",
    )
    toolset = toolset_module.build_toolset(
        cdp_url="http://browser:9222",
        page_policy=PagePolicy(None, 60, 1024),
        loop_policy=_policy(),
        page_factory=open_page,
        credential_ids=(uuid4(),),
    )

    async def invoke(name, args=None):
        tools = await toolset.get_tools(ctx)
        return await toolset.call_tool(name, args or {}, ctx, tools[name])

    async def late_events(original_sinks):
        published.reset_mock()
        chat.reset_mock()
        for sink in original_sinks:
            for event in (
                raw_frame,
                BrowserEvent(
                    kind="browser_control_error", call_id="first", step=1, detail=PASSWORD
                ),
                BrowserEvent(kind="browser_finished", call_id="first", step=1, reason=PASSWORD),
            ):
                await sink(event)
        assert published.await_count == len(original_sinks) * 3
        for call in published.await_args_list + chat.await_args_list:
            event = call.args[-1]
            assert event.image is None
            assert PASSWORD not in event.model_dump_json()
            assert event.url == ORIGIN

    async with toolset:
        args = (
            {"task": "Synthetic task", "start_url": ORIGIN}
            if first_tool == "browse_web"
            else {"url": ORIGIN}
        )
        await invoke(first_tool, args)
        assert await invoke("browser_credential_options") == "[]"
        first_view = toolset.view
        assert first_view is not None
        assert (
            await invoke(
                "browser_fill_credential",
                {
                    "secret_id": str(uuid4()),
                    "authorization_generation": str(uuid4()),
                    "selection": {"fields": [{"field": "password", "element_id": 0}]},
                },
            )
            == "Credential fill completed."
        )
        assert toolset.view is first_view
        assert pages[0].output_guard.active
        assert controllers[0].request.await_count == 1
        assert protect_view.await_count == (2 if first_tool == "browse_web" else 1)
        original_sinks = tuple(sinks)
        await late_events(original_sinks)
        await invoke("browser_new_tab", {"url": ORIGIN})
        assert len(pages) == 2 and not pages[1].output_guard.active
        await late_events(original_sinks)
    await late_events(original_sinks)


@pytest.mark.parametrize("missing", ["redis", "run", "organization"])
async def test_chat_fallback_filters_late_output_when_page_is_protected(monkeypatch, missing):
    guard = BrowserOutputGuard()
    chat = AsyncMock(return_value=True)
    monkeypatch.setattr(live_browse, "available", lambda: missing != "redis")
    deps = AgentDeps(
        run_id=None if missing == "run" else uuid4(),
        organization_id=None if missing == "organization" else uuid4(),
        browser_events=chat,
    )
    sink, control, run = await _live(deps, "first", "Synthetic task", lambda: guard)
    assert sink is not None and control is None and run is None
    guard.protect(ORIGIN)
    await sink(BrowserEvent(kind="browser_control_error", call_id="first", step=1, detail=PASSWORD))
    event = chat.await_args.args[0]
    assert PASSWORD not in event.model_dump_json()
    assert event.url == ORIGIN


def store_client(store):
    return SimpleNamespace(raw=store, get=store.get, list_range=store.list_range)


async def test_every_earlier_call_is_announced_and_purged_before_protection_returns(monkeypatch):
    store = ProtectedStore()
    monkeypatch.setattr(live_browse, "_redis", store_client(store))
    monkeypatch.setattr(live_browse, "has_viewers", AsyncMock(return_value=True))
    guard = BrowserOutputGuard()
    chat = AsyncMock(return_value=True)
    deps = AgentDeps(run_id=uuid4(), organization_id=uuid4(), browser_events=chat)
    old, _, run = await _live(deps, "old", "Synthetic task", lambda: guard)
    current, _, _ = await _live(deps, "current", "Synthetic task", lambda: guard)
    assert old is not None and current is not None and run is not None
    await old(
        BrowserEvent(
            kind="browser_frame",
            call_id="old",
            tab_id="main",
            step=0,
            image=PASSWORD,
            url=ORIGIN + "/" + PASSWORD,
            title=PASSWORD,
        )
    )
    guard.protect(ORIGIN)
    await current(protected_event().model_copy(update={"call_id": "current", "tab_id": "main"}))
    announced = [
        call.args[0] for call in chat.await_args_list if call.args[0].kind == "browser_protected"
    ]
    assert {event.call_id for event in announced} == {"old", "current"}
    for call_id in ("old", "current"):
        _, trace, frame = await live_browse._load(run, call_id)
        assert PASSWORD not in json.dumps(trace) + str(frame)
        assert all(BrowserEvent.model_validate_json(raw).output_protected for raw in trace)
        assert frame is not None
        observed = BrowserEvent.model_validate_json(frame)
        assert observed.output_protected and observed.image is None
    late, _, _ = await _live(deps, "late", "Synthetic task", lambda: guard)
    assert late is not None
    await late(BrowserEvent(kind="browser_finished", call_id="late", step=2, detail=PASSWORD))
    assert [
        call.args[0].call_id
        for call in chat.await_args_list
        if call.args[0].kind == "browser_protected"
    ] == ["old", "current", "late"]
    assert chat.await_args.args[0].output_protected


async def test_any_old_view_purge_failure_refuses_the_shared_protection_fence(monkeypatch, caplog):
    guard = BrowserOutputGuard()
    old, _ = await make_sink(monkeypatch, guard)
    current, _ = await make_sink(monkeypatch, guard)
    await old(BrowserEvent(kind="browser_step", call_id="call", step=0))
    live_browse.protect_view.side_effect = RedisError(PASSWORD)
    guard.protect(ORIGIN)
    with pytest.raises(RedisError):
        await current(protected_event())
    assert PASSWORD not in caplog.text
    live_browse.protect_view.side_effect = None
    live_browse.protect_view.reset_mock()
    await current(protected_event())
    assert live_browse.protect_view.await_count == 2


async def test_snapshot_racing_protection_never_joins_an_old_picture_or_trace(monkeypatch):
    store = ProtectedStore()
    client = store_client(store)
    monkeypatch.setattr(live_browse, "_redis", client)
    await live_browse.open_view(RUN, CALL, _meta())
    store.values[live_browse._key(RUN, CALL, "frame")] = BrowserEvent(
        kind="browser_frame", call_id=CALL, step=0, image=PASSWORD
    ).model_dump_json()
    store.lists[live_browse._key(RUN, CALL, "trace")] = [
        BrowserEvent(kind="browser_step", call_id=CALL, step=0, detail=PASSWORD).model_dump_json()
    ]

    async def racing_get(key):
        if key == live_browse._key(RUN, CALL, "location"):
            await live_browse.protect_view(
                RUN, CALL, protected_event().model_copy(update={"call_id": CALL})
            )
        return await store.get(key)

    client.get = racing_get
    _, trace, frame = await live_browse._load(RUN, CALL)
    assert PASSWORD not in json.dumps(trace) + str(frame)
    assert trace == [] and BrowserEvent.model_validate_json(frame).output_protected


async def test_reconnect_recovers_protection_in_snapshot_subscription_gap(monkeypatch):
    store = ProtectedStore()
    monkeypatch.setattr(live_browse, "_redis", store_client(store))
    monkeypatch.setattr(live_browse, "access_for", _access(control=False))
    await live_browse.open_view(RUN, CALL, _meta())
    await live_browse.publish(
        RUN, CALL, BrowserEvent(kind="browser_frame", call_id=CALL, step=0, image="earlier")
    )

    class RacingSocket(_Socket):
        async def send_text(self, raw):
            await super().send_text(raw)
            if len(self.sent) == 1:
                await live_browse.protect_view(
                    RUN, CALL, protected_event().model_copy(update={"call_id": CALL})
                )

    socket = RacingSocket()
    await live_browse.stream(socket, auth_token="synthetic", run_id=RUN, call_id=CALL)
    assert socket.sent[0]["frame"]["image"] == "earlier"
    assert socket.sent[1]["output_protected"] is True and socket.sent[1]["image"] is None
    assert store.pubsubs[0].closed


async def test_protection_drops_queued_and_late_pictures_but_preserves_protected_receipts():
    async def source():
        yield live_browse._PreviewPacket("old narration", False)
        yield live_browse._PreviewPacket("old picture", True)
        yield live_browse._PreviewPacket("protected", False, protected=True)
        yield live_browse._PreviewPacket("late picture", True)
        yield live_browse._PreviewPacket("needs-person", False, protected=True)
        yield live_browse._PreviewPacket("finished", False, terminal=True, protected=True)

    deliver = AsyncMock()
    assert await live_browse._deliver_preview(source(), deliver)
    assert [call.args[0] for call in deliver.await_args_list] == [
        "protected",
        "needs-person",
        "finished",
    ]
