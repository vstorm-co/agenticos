"""Shared desktops refuse overlapping runs and stop after losing ownership."""

import asyncio
import io
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import anyio
import pytest
from PIL import Image
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from pydantic_ai.workspaces import (
    CommandResult,
    SupportsCommands,
    Workspace,
    WorkspaceError,
    WorkspaceRef,
)
from redis.exceptions import ConnectionError as RedisConnectionError

from app.agents.browser_events import BrowserCommand, BrowserEvent
from app.agents.capabilities.computer_use import ComputerUse, _lease, _toolset
from app.agents.capabilities.computer_use._actions import Click, Screen
from app.agents.capabilities.computer_use._backends import (
    Capture,
    ComputerError,
    NativeAction,
    open_sandbox_desktop,
)
from app.agents.capabilities.computer_use._desktop_apps import App
from app.agents.capabilities.computer_use._lease import DesktopLeaseLost, LeasedComputer
from app.agents.capabilities.computer_use._live import held
from app.agents.deps import AgentDeps
from app.clients.redis import RedisClient

pytestmark = pytest.mark.anyio

REF = WorkspaceRef(provider="sandboxd:connection-one", id="user-desktop")


class _Desktop:
    label = "Linux"

    def __init__(self) -> None:
        self.actions: list[NativeAction] = []
        self.captures = 0
        self.listed = 0
        self.closed = 0

    async def capture(self) -> Capture:
        self.captures += 1
        return Capture(image=b"screen", width=100, height=80)

    async def perform(self, action: NativeAction) -> None:
        self.actions.append(action)

    async def apps(self) -> list[App]:
        self.listed += 1
        return []

    async def close(self) -> None:
        self.closed += 1


class _Redis:
    """The Redis boundary shared by distinct clients, with an advanceable clock."""

    def __init__(self) -> None:
        self.values: dict[str, tuple[str, float]] = {}
        self.now = 0.0
        self.clients: list[MagicMock] = []
        self.error: Exception | None = None
        self.renewed = asyncio.Event()

    def current(self, key: str) -> str | None:
        value = self.values.get(key)
        if value is None:
            return None
        if value[1] <= self.now:
            del self.values[key]
            return None
        return value[0]

    async def claim(self, key: str, holder: str, *, ttl: int, nx: bool) -> bool:
        if self.error is not None:
            raise self.error
        assert nx
        if self.current(key) is not None:
            return False
        self.values[key] = holder, self.now + ttl
        return True

    async def renew(self, script: str, keys: int, key: str, holder: str, ttl: int) -> int:
        self.renewed.set()
        if self.error is not None:
            raise self.error
        assert keys == 1 and script == _lease._RENEW
        if self.current(key) != holder:
            return 0
        self.values[key] = holder, self.now + ttl
        return 1

    async def release(self, key: str, holder: str) -> bool:
        if self.error is not None:
            raise self.error
        if self.current(key) != holder:
            return False
        del self.values[key]
        return True

    def client(self) -> MagicMock:
        client = MagicMock(spec=RedisClient)
        client.connect = AsyncMock()
        client.set = AsyncMock(side_effect=self.claim)
        client.raw.eval = AsyncMock(side_effect=self.renew)
        client.delete_if_equal = AsyncMock(side_effect=self.release)
        client.close = AsyncMock()
        self.clients.append(client)
        return client


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> _Redis:
    state = _Redis()
    monkeypatch.setattr(_lease, "RedisClient", state.client)
    monkeypatch.setattr(_toolset.live_browse, "available", lambda: False)
    return state


@pytest.mark.parametrize("same_run", [False, True])
async def test_only_one_concurrent_claim_can_observe_or_act(redis: _Redis, same_run: bool) -> None:
    first, second = _Desktop(), _Desktop()
    run = str(uuid4())
    results = await asyncio.gather(
        LeasedComputer.acquire(first, REF, run),
        LeasedComputer.acquire(second, REF, run if same_run else str(uuid4())),
        return_exceptions=True,
    )
    winners = [result for result in results if isinstance(result, LeasedComputer)]
    refusals = [result for result in results if isinstance(result, ComputerError)]
    assert len(winners) == len(refusals) == 1
    assert "another run" in str(refusals[0])
    [winner] = winners
    assert winner.label == "Linux"
    assert (await winner.capture()).image == b"screen"
    assert await winner.apps() == []
    await winner.perform(Click(x=4, y=5))
    assert first.captures + second.captures == 1
    assert first.listed + second.listed == 1
    assert len(first.actions) + len(second.actions) == 1
    await winner.close()
    await winner.close()
    assert redis.values == {}
    assert first.closed == second.closed == 1
    next_run = await LeasedComputer.acquire(_Desktop(), REF, str(uuid4()))
    await next_run.close()


@pytest.mark.parametrize(
    "ref",
    [
        WorkspaceRef(provider="sandboxd:connection-two", id=REF.id),
        WorkspaceRef(provider=REF.provider, id="another-user-desktop"),
    ],
)
async def test_distinct_workspaces_do_not_block_each_other(
    redis: _Redis, ref: WorkspaceRef
) -> None:
    first = await LeasedComputer.acquire(_Desktop(), REF, str(uuid4()))
    second = await LeasedComputer.acquire(_Desktop(), ref, str(uuid4()))
    assert len(redis.values) == 2
    await first.close()
    await second.close()


@pytest.mark.parametrize(("ref", "run"), [(None, "run"), (REF, None)])
async def test_missing_server_identity_never_uses_the_screen(
    redis: _Redis, ref: WorkspaceRef | None, run: str | None
) -> None:
    desktop = _Desktop()
    with pytest.raises(ComputerError, match="identity to lock"):
        await LeasedComputer.acquire(desktop, ref, run)
    assert redis.clients == []
    assert desktop.closed == 1 and desktop.captures == 0 and desktop.actions == []


async def test_redis_failure_is_closed_and_its_connection_details_are_not_shown(
    redis: _Redis,
) -> None:
    redis.error = RedisConnectionError("redis://secret@example/private")
    desktop = _Desktop()
    with pytest.raises(ComputerError, match="exclusive access could not be verified") as refused:
        await LeasedComputer.acquire(desktop, REF, str(uuid4()))
    assert "secret" not in str(refused.value)
    assert desktop.captures == 0 and desktop.actions == [] and desktop.closed == 1
    redis.clients[0].close.assert_awaited_once()


async def test_expiry_never_lets_an_old_owner_act_or_delete_a_successors_claim(
    redis: _Redis,
) -> None:
    old_desktop, new_desktop = _Desktop(), _Desktop()
    old = await LeasedComputer.acquire(old_desktop, REF, "old-run")
    redis.now = _lease.LEASE_SECONDS + 1
    new = await LeasedComputer.acquire(new_desktop, REF, "new-run")
    with pytest.raises(DesktopLeaseLost):
        await old.perform(Click(x=1, y=1))
    await old.close()
    assert len(redis.values) == 1
    await new.perform(Click(x=2, y=2))
    assert old_desktop.actions == [] and len(new_desktop.actions) == 1
    await new.close()


async def test_a_failed_ownership_check_is_terminal_even_when_redis_recovers(redis: _Redis) -> None:
    desktop = _Desktop()
    owner = await LeasedComputer.acquire(desktop, REF, "run")
    redis.error = RedisConnectionError("unreachable")
    with pytest.raises(DesktopLeaseLost):
        await owner.capture()
    redis.error = None
    with pytest.raises(DesktopLeaseLost):
        await owner.perform(Click(x=1, y=1))
    with pytest.raises(DesktopLeaseLost):
        await owner.apps()
    assert desktop.captures == desktop.listed == 0 and desktop.actions == []
    await owner.close()
    with pytest.raises(DesktopLeaseLost):
        await owner.capture()


async def test_heartbeat_keeps_an_idle_model_or_human_session_exclusive(
    redis: _Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_lease, "RENEW_EVERY", 0)
    owner = await LeasedComputer.acquire(_Desktop(), REF, "run")
    redis.now = _lease.LEASE_SECONDS - 1
    with anyio.fail_after(1):
        await redis.renewed.wait()
    redis.now = _lease.LEASE_SECONDS + 1
    with pytest.raises(ComputerError, match="another run"):
        await LeasedComputer.acquire(_Desktop(), REF, "other-run")
    await owner.close()


async def test_a_screen_captured_during_ownership_loss_is_not_returned(
    redis: _Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    desktop = _Desktop()
    owner = await LeasedComputer.acquire(desktop, REF, "run")

    async def capture() -> Capture:
        redis.values.clear()
        return Capture(image=b"another run's screen", width=100, height=80)

    monkeypatch.setattr(desktop, "capture", capture)
    with pytest.raises(DesktopLeaseLost):
        await owner.capture()
    await owner.close()


async def test_heartbeat_loss_stops_future_input(
    redis: _Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_lease, "RENEW_EVERY", 0)
    desktop = _Desktop()
    owner = await LeasedComputer.acquire(desktop, REF, "run")
    redis.error = RedisConnectionError("offline")
    with anyio.fail_after(1):
        await redis.renewed.wait()
    redis.error = None
    with pytest.raises(DesktopLeaseLost):
        await owner.perform(Click(x=1, y=1))
    assert desktop.actions == []
    await owner.close()


async def test_cancellation_after_redis_accepts_a_claim_releases_it(
    redis: _Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    accepted = asyncio.Event()
    never = asyncio.Event()
    client = redis.client()

    async def slow_claim(key: str, holder: str, *, ttl: int, nx: bool) -> bool:
        await redis.claim(key, holder, ttl=ttl, nx=nx)
        accepted.set()
        await never.wait()
        return True

    client.set = AsyncMock(side_effect=slow_claim)
    monkeypatch.setattr(_lease, "RedisClient", lambda: client)
    desktop = _Desktop()
    task = asyncio.create_task(LeasedComputer.acquire(desktop, REF, "run"))
    await accepted.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert redis.values == {} and desktop.closed == 1
    client.close.assert_awaited_once()


def _workspace(redis: _Redis) -> MagicMock:
    workspace = MagicMock(spec=Workspace)
    workspace.attached = True
    workspace.backend = MagicMock(spec=SupportsCommands)
    workspace.ref = REF

    async def run(*args: object, **kwargs: object) -> CommandResult:
        assert redis.values, "Even desktop bootstrap must hold the lease"
        return CommandResult(exit_code=0, stdout="", stderr="")

    workspace.run = AsyncMock(side_effect=run)
    output = io.BytesIO()
    Image.new("RGB", (100, 80)).save(output, format="PNG")
    workspace.read_bytes = AsyncMock(return_value=output.getvalue())
    workspace.remove = AsyncMock()
    return workspace


def _ctx(workspace: Workspace) -> RunContext[AgentDeps]:
    return RunContext(
        deps=AgentDeps(run_id=uuid4()),
        model=TestModel(),
        usage=RunUsage(),
        workspace=workspace,
        tool_call_id="screenshot",
    )


async def test_toolsets_lock_before_bootstrap_and_a_busy_run_cannot_see_the_desktop(
    redis: _Redis,
) -> None:
    workspace = _workspace(redis)
    first, second = (
        ComputerUse(backend="sandbox").get_toolset(),
        ComputerUse(backend="sandbox").get_toolset(),
    )
    assert isinstance(first, _toolset.ComputerToolset) and isinstance(
        second, _toolset.ComputerToolset
    )
    async with first, second:
        await first.tools["computer_screenshot"].function(_ctx(workspace))
        calls = workspace.run.await_count
        refused = await second.tools["computer_screenshot"].function(_ctx(workspace))
        assert "another run" in refused
        assert workspace.run.await_count == calls
    assert redis.values == {}


async def test_lazy_workspace_materializes_without_touching_the_display(redis: _Redis) -> None:
    workspace = _workspace(redis)
    workspace.ref = None

    async def stat(path: str) -> None:
        assert path == "/" and redis.values == {}
        workspace.ref = REF

    workspace.stat = AsyncMock(side_effect=stat)
    desktop = await open_sandbox_desktop(workspace, width=100, height=80, defer_start=True)
    workspace.run.assert_not_awaited()
    owner = await LeasedComputer.acquire(desktop, workspace.ref, "run")
    await desktop.start()
    workspace.run.assert_awaited_once()
    await owner.close()


async def test_unreachable_lazy_workspace_refuses_before_a_claim(redis: _Redis) -> None:
    workspace = _workspace(redis)
    workspace.ref = None
    workspace.stat = AsyncMock(side_effect=WorkspaceError("gone"))
    with pytest.raises(ComputerError, match="could not be reached"):
        await open_sandbox_desktop(workspace, width=100, height=80, defer_start=True)
    workspace.run.assert_not_awaited()
    assert redis.values == {}


async def test_failed_bootstrap_releases_the_claim(redis: _Redis) -> None:
    workspace = _workspace(redis)
    workspace.run = AsyncMock(return_value=CommandResult(exit_code=3, stdout="", stderr=""))
    toolset = ComputerUse(backend="sandbox").get_toolset()
    assert isinstance(toolset, _toolset.ComputerToolset)
    async with toolset:
        refused = await toolset.tools["computer_screenshot"].function(_ctx(workspace))
        assert "no desktop installed" in refused
    assert redis.values == {}


async def test_teardown_releases_ownership_even_if_the_live_view_cannot_finish(
    redis: _Redis,
) -> None:
    toolset = _toolset.build_toolset(AsyncMock(), _toolset.ToolPolicy())
    owner = await LeasedComputer.acquire(_Desktop(), REF, "run")
    with pytest.raises(RuntimeError, match="view disconnected"):
        async with toolset:
            toolset.session.computer = owner
            toolset.session.call_id = "window"
            toolset.session.sink = AsyncMock(side_effect=RuntimeError("view disconnected"))
    assert redis.values == {}


async def test_human_takeover_uses_the_same_lease_until_give_back(redis: _Redis) -> None:
    desktop = _Desktop()
    owner = await LeasedComputer.acquire(desktop, REF, "run")
    events: list[BrowserEvent] = []
    screen = Screen(width=100, height=80, native_width=100, native_height=80)

    async def look() -> tuple[bytes, Screen]:
        return (await owner.capture()).image, screen

    async def emit(event: BrowserEvent) -> None:
        events.append(event)

    control = MagicMock(
        wait=AsyncMock(
            side_effect=[
                BrowserCommand(type="click", x=5, y=6, by_user_id="person"),
                BrowserCommand(type="give_back", by_user_id="person"),
            ]
        )
    )
    await held(
        owner,
        control,
        BrowserCommand(type="take_over", by_user_id="person"),
        look=look,
        emit=emit,
        call_id="window",
        step=0,
    )
    assert len(desktop.actions) == 1
    assert [event.kind for event in events] == ["browser_held", "browser_frame", "browser_released"]
    with pytest.raises(ComputerError, match="another run"):
        await LeasedComputer.acquire(_Desktop(), REF, "other-run")
    await owner.close()


async def test_canceling_a_run_releases_its_desktop_claim(redis: _Redis) -> None:
    toolset = _toolset.build_toolset(AsyncMock(), _toolset.ToolPolicy())
    owner = await LeasedComputer.acquire(_Desktop(), REF, "run")
    with anyio.CancelScope() as cancel:
        async with toolset:
            toolset.session.computer = owner
            cancel.cancel()
            await anyio.lowlevel.checkpoint()
    assert redis.values == {}


async def test_a_broken_redis_close_does_not_leave_a_claim_held(redis: _Redis) -> None:
    owner = await LeasedComputer.acquire(_Desktop(), REF, "run")
    redis.clients[0].close.side_effect = RedisConnectionError("gone")
    await owner.close()
    assert redis.values == {}


@pytest.mark.parametrize("input_arrives", [False, True])
async def test_takeover_ends_promptly_when_ownership_is_lost(
    redis: _Redis, input_arrives: bool
) -> None:
    desktop = _Desktop()
    owner = await LeasedComputer.acquire(desktop, REF, "run")
    screen = Screen(width=100, height=80, native_width=100, native_height=80)

    async def look() -> tuple[bytes, Screen]:
        return (await owner.capture()).image, screen

    async def wait(_timeout: float) -> BrowserCommand | None:
        redis.values.clear()
        return (
            BrowserCommand(type="click", x=5, y=6, by_user_id="person") if input_arrives else None
        )

    with pytest.raises(DesktopLeaseLost):
        await held(
            owner,
            MagicMock(wait=AsyncMock(side_effect=wait)),
            BrowserCommand(type="take_over", by_user_id="person"),
            look=look,
            emit=AsyncMock(),
            call_id="window",
            step=0,
        )
    assert desktop.actions == []
    await owner.close()
