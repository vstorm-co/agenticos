"""The real browser socket and tool seams keep server identity and reviewed authority."""

import json
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import anyio
import anyio.lowlevel
import pytest

from app.agents.browser_events import BrowserCommand
from app.agents.capabilities.browser_use import _toolset
from app.agents.capabilities.browser_use._loop import BrowseSession
from app.agents.capabilities.browser_use._page import CdpPage
from app.agents.capabilities.browser_use._protected import BrowserOutputGuard
from app.agents.system_agents import JUDGE
from app.core.browser_teaching import CaptureObservation, TeachingReason, TeachingRefused
from app.core.config import settings
from app.services import live_browse
from app.services.browser_teaching import _discovery, _lease
from tests.test_browser_teaching_contracts import ORIGIN, SECRET
from tests.test_browser_teaching_native import Redis
from tests.test_browser_use import _direct
from tests.test_browser_use import _toolset as make_toolset
from tests.test_live_browse import CALL, RUN, _key, _meta, _Socket, _step
from tests.test_live_browse import store as store
from tests.test_system_agent_runner import Verdict, _ctx, _runner

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def admission(monkeypatch, meta):
    monkeypatch.setattr(settings, "BROWSER_TEACHING_ENABLED", True)
    monkeypatch.setattr(settings, "BROWSER_TEACHING_ORGANIZATION_IDS", [meta.organization_id])
    return live_browse._Access(
        control=True, own=True, name="Synthetic operator", user_id=meta.user_id
    )


@pytest.mark.parametrize("gate", ["viewer", "deployment", "organization", "redis"])
async def test_no_connection_lease_is_exposed_without_deployment_and_owner_admission(
    monkeypatch, gate
):
    meta, redis = _meta(), Redis()
    access = admission(monkeypatch, meta)
    if gate == "viewer":
        access = live_browse._Access(
            control=True, own=False, name=access.name, user_id=access.user_id
        )
    elif gate == "deployment":
        monkeypatch.setattr(settings, "BROWSER_TEACHING_ENABLED", False)
    elif gate == "organization":
        monkeypatch.setattr(settings, "BROWSER_TEACHING_ORGANIZATION_IDS", [])
    else:
        monkeypatch.setattr(redis, "set", AsyncMock(side_effect=OSError(SECRET)))
    send = AsyncMock()
    monkeypatch.setattr(live_browse, "send", send)
    async with live_browse._teaching_connection(redis, meta, access, RUN, CALL) as connection:
        assert connection is None
    send.assert_not_awaited()


async def test_cancellation_releases_the_exact_connection_and_notifies_the_owning_controller(
    monkeypatch,
):
    meta, redis = _meta(), Redis()
    access = admission(monkeypatch, meta)
    send = AsyncMock()
    monkeypatch.setattr(live_browse, "send", send)
    connection = None
    with anyio.CancelScope() as cancelled:
        async with live_browse._teaching_connection(redis, meta, access, RUN, CALL) as connection:
            assert connection is not None
            assert await redis.get(_lease.connection_key(RUN, CALL, connection)) == access.user_id
            cancelled.cancel()
            await anyio.lowlevel.checkpoint()
    assert connection is not None
    assert await redis.get(_lease.connection_key(RUN, CALL, connection)) is None
    sent_run, sent_call, lost = send.await_args.args
    assert (sent_run, sent_call) == (RUN, CALL)
    assert lost.type == "control_lost" and lost.control_connection_id == connection
    assert lost.by_user_id == access.user_id and lost.control_sequence is None


@pytest.fixture
def owned_socket(store, monkeypatch):
    meta = _meta()
    access = admission(monkeypatch, meta)
    current = AsyncMock(return_value=access)
    monkeypatch.setattr(live_browse, "access_for", current)
    opened, renewed, closed = (
        AsyncMock(return_value=True),
        AsyncMock(return_value=True),
        AsyncMock(),
    )
    monkeypatch.setattr(_lease, "open_connection", opened)
    monkeypatch.setattr(_lease, "renew_connection", renewed)
    monkeypatch.setattr(_lease, "close_connection", closed)
    store.queued_messages = [_step(1).model_dump_json()]
    return SimpleNamespace(
        meta=meta,
        access=access,
        current=current,
        opened=opened,
        renewed=renewed,
        closed=closed,
        store=store,
    )


async def test_socket_overwrites_client_identity_and_sequence_and_rejects_forged_disconnects(
    owned_socket,
):
    s = owned_socket
    await live_browse.open_view(RUN, CALL, s.meta)
    forged = uuid4()
    socket = _Socket(
        "x" * 32_769,
        "invalid json",
        json.dumps({"type": "control_lost"}),
        json.dumps(
            {
                "type": "take_over",
                "by": SECRET,
                "by_user_id": SECRET,
                "control_connection_id": str(forged),
                "control_sequence": 999,
            }
        ),
        json.dumps(
            {
                "type": "type",
                "text": "synthetic parameter",
                "control_connection_id": str(forged),
                "control_sequence": 998,
            }
        ),
    )
    await live_browse.stream(socket, auth_token="synthetic", run_id=RUN, call_id=CALL)
    queued = [BrowserCommand.model_validate_json(raw) for raw in s.store.lists[_key("control")]]
    assert [command.type for command in queued] == ["take_over", "type", "control_lost"]
    first, second, lost = queued
    assert [first.control_sequence, second.control_sequence] == [1, 2]
    assert first.control_connection_id != forged
    assert second.control_connection_id == lost.control_connection_id == first.control_connection_id
    assert all(command.by_user_id == s.access.user_id for command in queued)
    assert first.by == second.by == s.access.name
    s.opened.assert_awaited_once()
    s.closed.assert_awaited_once()
    assert s.closed.await_args.args[3] == first.control_connection_id


@pytest.mark.parametrize("change", ["owner", "user", "lease"])
async def test_socket_revocation_prevents_a_command_and_still_releases_the_connection(
    owned_socket, change
):
    s = owned_socket
    await live_browse.open_view(RUN, CALL, s.meta)
    if change == "lease":
        s.renewed.return_value = False
    else:
        fresh = live_browse._Access(
            control=True,
            own=change != "owner",
            name=s.access.name,
            user_id=str(uuid4()) if change == "user" else s.access.user_id,
        )
        s.current.side_effect = [s.access, fresh]
    socket = _Socket(json.dumps({"type": "take_over"}))
    await live_browse.stream(socket, auth_token="synthetic", run_id=RUN, call_id=CALL)
    queued = [BrowserCommand.model_validate_json(raw) for raw in s.store.lists[_key("control")]]
    assert [command.type for command in queued] == ["control_lost"]
    assert socket.closed == (4403, "Not allowed to watch")
    s.closed.assert_awaited_once()


async def test_the_server_closes_at_its_sequence_bound_without_accepting_another_input(
    owned_socket, monkeypatch
):
    s = owned_socket
    monkeypatch.setattr(live_browse, "CONTROL_SEQUENCE_LIMIT", 2)
    await live_browse.open_view(RUN, CALL, s.meta)
    socket = _Socket(*(json.dumps({"type": "take_over"}) for _ in range(3)))
    await live_browse.stream(socket, auth_token="synthetic", run_id=RUN, call_id=CALL)
    queued = [BrowserCommand.model_validate_json(raw) for raw in s.store.lists[_key("control")]]
    assert [command.control_sequence for command in queued] == [1, 2, None]
    assert queued[-1].type == "control_lost"
    assert socket.closed == (4403, "Not allowed to watch")


@pytest.mark.parametrize("bounded", [False, True])
async def test_system_drafting_preserves_the_exact_budget_and_per_request_authority_callback(
    monkeypatch, bounded
):
    runner, execute = _runner(monkeypatch)
    check = AsyncMock()
    options = {"run_limit_usd": Decimal("0.05"), "check_model_request": check} if bounded else {}
    result = await runner.run(
        _ctx(), key=JUDGE.key, prompt="Reviewed procedure", output_type=Verdict, **options
    )
    assert result.output.passed
    supplied = execute.await_args.kwargs
    if bounded:
        assert supplied["run_limit_usd"] == Decimal("0.05")
        assert supplied["check_model_request"] is check
    else:
        assert "run_limit_usd" not in supplied and "check_model_request" not in supplied


@pytest.mark.parametrize(
    "case", ["missing", "ordinary", "protected", "refused", "unavailable", "allowed"]
)
async def test_procedure_tool_reads_only_the_live_unprotected_origin_and_never_replays(
    monkeypatch, case
):
    toolset = make_toolset(None)
    observed = AsyncMock(return_value=CaptureObservation(origin=ORIGIN))
    discover = AsyncMock(return_value=())
    monkeypatch.setattr(_toolset.TeachingPage, "observe", observed)
    monkeypatch.setattr(_discovery, "discover", discover)

    @asynccontextmanager
    async def database():
        yield AsyncMock()

    monkeypatch.setattr(_toolset, "get_db_context", database)
    if case != "missing":
        page = MagicMock(spec=CdpPage) if case != "ordinary" else MagicMock()
        page.output_guard = BrowserOutputGuard()
        toolset.session = BrowseSession(page=page)
        if case == "protected":
            page.output_guard.protect(ORIGIN)
    if case == "refused":
        discover.side_effect = TeachingRefused(TeachingReason.AUTHORITY_CHANGED)
    elif case == "unavailable":
        observed.side_effect = RuntimeError(SECRET)
    result = await _direct(toolset, "browser_procedures")
    assert SECRET not in result
    if case == "allowed":
        assert json.loads(result) == []
        assert discover.await_args.args[3] == ORIGIN
    else:
        assert "unavailable" in result.lower() or result == _toolset.NO_TAB
    if case in {"missing", "ordinary", "protected"}:
        observed.assert_not_awaited()
        discover.assert_not_awaited()
