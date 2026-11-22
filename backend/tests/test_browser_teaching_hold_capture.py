"""The simple-teaching capture on one held tab: lease, renewal, what each input becomes, and failure.

Capture never reaches the browse loop with an error. A lost lease, an unreadable
page or a failed write pauses the recording and is logged by exception type only.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.agents.browser_events import BrowserCommand
from app.core.browser_teaching import TeachingReason
from app.core.config import settings
from app.services.browser_teaching import _capture, _hold
from app.services.browser_teaching._capture import HoldCapture
from tests.test_browser_teaching_services import _Script

pytestmark = pytest.mark.anyio

ORG, USER, RUN, AGENT = (uuid.uuid4() for _ in range(4))
ORIGIN = "https://portal.example.com"


def _page(role: str | None, *, auth: bool = False) -> dict[str, Any]:
    return {
        "origin": ORIGIN,
        "role": role,
        "path": [[role or "div", 0]] if role else None,
        "auth": auth,
    }


class _Observer:
    """A page that answers per mode; an `Exception` value is raised the way a dead page would."""

    def __init__(self, **answers: Any) -> None:
        self.answers = answers

    async def __call__(self, _script: str, mode: str, _x: float, _y: float) -> Any:
        answer = self.answers[mode]
        if isinstance(answer, Exception):
            raise answer
        return answer


class _Service:
    """The write side: remembers what capture asked it to store or pause, and can be made to fail."""

    calls: list[tuple[str, Any]] = []
    fail: Exception | None = None

    def __init__(self, db: object, redis: object) -> None:
        self.db = db

    async def record(self, hold: _hold.Hold, **step: Any) -> None:
        if _Service.fail:
            raise _Service.fail
        _Service.calls.append(("record", step))

    async def release(self, hold: _hold.Hold, reason: TeachingReason) -> None:
        if _Service.fail:
            raise _Service.fail
        _Service.calls.append(("release", reason))


@pytest.fixture
def writes(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    _Service.calls, _Service.fail = [], None

    @asynccontextmanager
    async def context() -> AsyncIterator[str]:
        yield "db"

    monkeypatch.setattr(_capture, "get_db_context", context)
    monkeypatch.setattr(_capture, "BrowserTeachingService", _Service)
    monkeypatch.setattr(settings, "BROWSER_TEACHING_ENABLED", True)
    monkeypatch.setattr(settings, "BROWSER_TEACHING_ORGANIZATION_IDS", [ORG])
    return _Service.calls


def _capture_for(redis: _Script, observer: _Observer | None = None) -> HoldCapture:
    return HoldCapture(
        organization_id=ORG,
        run_id=RUN,
        agent_id=AGENT,
        user_id=USER,
        tab_id="main",
        redis=cast(Any, redis),
        run_observer=cast(Any, observer or _Observer()),
    )


def _command(kind: str, **fields: Any) -> BrowserCommand:
    return BrowserCommand(type=cast(Any, kind), by_user_id=str(USER), **fields)


async def _held(redis: _Script, observer: _Observer | None = None) -> HoldCapture:
    capture = _capture_for(redis, observer)
    await capture.begin("call-1", str(USER))
    assert capture.hold is not None
    return capture


async def test_a_take_over_by_the_runs_person_claims_the_lease_and_hand_back_releases_it(
    writes: list[tuple[str, Any]],
) -> None:
    redis = _Script()
    capture = await _held(redis)
    assert await _hold.current(cast(Any, redis), RUN, "call-1") == capture.hold
    await capture.end()
    assert capture.hold is None
    assert await _hold.current(cast(Any, redis), RUN, "call-1") is None
    assert writes == [("release", TeachingReason.OWNERSHIP_LOST)]


async def test_another_person_or_a_disabled_deployment_or_a_taken_view_starts_no_capture(
    writes: list[tuple[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    redis = _Script()
    other = _capture_for(redis)
    await other.begin("call-1", str(uuid.uuid4()))
    assert other.hold is None
    taken = _capture_for(redis)
    await _hold.claim(
        cast(Any, redis),
        _hold.Hold(
            organization_id=ORG,
            run_id=RUN,
            agent_id=AGENT,
            user_id=USER,
            call_id="call-1",
            tab_id="main",
            hold_id=uuid.uuid4(),
        ),
    )
    await taken.begin("call-1", str(USER))
    assert taken.hold is None
    monkeypatch.setattr(settings, "BROWSER_TEACHING_ENABLED", False)
    off = _capture_for(_Script())
    await off.begin("call-1", str(USER))
    assert off.hold is None


async def test_a_lease_that_cannot_be_renewed_pauses_the_recording(
    writes: list[tuple[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_capture, "RENEW_SECONDS", 0)
    redis = _Script()
    capture = await _held(redis)
    redis.values.clear()
    for _ in range(100):
        if capture.hold is None:
            break
        await asyncio.sleep(0.01)
    assert capture.hold is None
    assert ("release", TeachingReason.OWNERSHIP_LOST) in writes


async def test_a_lease_that_keeps_renewing_stays_recording(
    writes: list[tuple[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_capture, "RENEW_SECONDS", 0.001)
    capture = await _held(_Script())
    hold = capture.hold
    await asyncio.sleep(0.05)
    assert capture.hold == hold
    assert writes == []
    await capture.end()


async def test_a_renewer_stops_when_its_hold_was_replaced(
    writes: list[tuple[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_capture, "RENEW_SECONDS", 0)
    capture = await _held(_Script())
    renewer = capture._renewer
    assert renewer is not None
    capture.hold = None
    await asyncio.wait_for(renewer, 2)
    assert writes == []


@pytest.mark.parametrize(
    ("command", "answers", "expected"),
    [
        (_command("reload"), {}, "navigate"),
        (_command("scroll", dy=40), {"origin": _page(None)}, "scroll"),
        (_command("scroll", dy=0), {}, None),
        (_command("click", x=3, y=4), {"point": _page("button")}, "click"),
        (_command("click", x=3, y=4), {"point": _page("combobox")}, "select"),
        (_command("click", x=3, y=4), {"point": _page(None)}, None),
        (_command("click", x=3, y=4), {"point": _page(None, auth=True)}, "click"),
        (_command("type", text="a"), {"focus": _page("textbox")}, "input_parameter"),
        (_command("type", text="a"), {"focus": _page("combobox")}, "select"),
        (_command("type", text="a"), {"focus": _page(None)}, None),
        (_command("key", key="Enter"), {"focus": _page("link")}, "click"),
        (_command("key", key="Enter"), {"focus": _page("textbox")}, "checkpoint"),
        (_command("key", key="Tab"), {}, None),
        (_command("resize", width=800, height=600), {}, None),
    ],
)
async def test_each_input_becomes_one_structural_action_or_nothing(
    writes: list[tuple[str, Any]],
    command: BrowserCommand,
    answers: dict[str, Any],
    expected: str | None,
) -> None:
    capture = await _held(_Script(), _Observer(**answers))
    prepared = await capture.before_input(command)
    assert (None if prepared is None else prepared.action) == expected


async def test_a_scroll_records_its_direction_and_an_unobservable_page_fails_the_input(
    writes: list[tuple[str, Any]],
) -> None:
    down = await _held(_Script(), _Observer(origin=_page(None)))
    up_command = _command("scroll", dy=-5)
    prepared = await down.before_input(up_command)
    assert prepared is not None and prepared.direction == "up"
    blind = await _held(_Script(), _Observer(point=RuntimeError("page closed")))
    failed = await blind.before_input(_command("click", x=1, y=1))
    assert failed is not None and failed.failed


async def test_input_from_nobody_holding_or_from_someone_else_is_not_prepared(
    writes: list[tuple[str, Any]],
) -> None:
    idle = _capture_for(_Script())
    assert await idle.before_input(_command("reload")) is None
    held = await _held(_Script())
    stranger = BrowserCommand(type="reload", by_user_id=str(uuid.uuid4()))
    assert await held.before_input(stranger) is None


async def test_a_carried_out_input_is_stored_with_the_observation_it_was_prepared_with(
    writes: list[tuple[str, Any]],
) -> None:
    capture = await _held(_Script(), _Observer(origin=_page(None)))
    await capture.after_input(await capture.before_input(_command("reload")))
    assert [name for name, _ in writes] == ["record"]
    assert writes[0][1]["action"] == "navigate"
    assert writes[0][1]["observation"].origin == ORIGIN
    await capture.after_input(None)
    await capture.after_input("not prepared")
    assert len(writes) == 1


async def test_an_unobservable_input_or_a_failed_write_pauses_the_recording(
    writes: list[tuple[str, Any]],
) -> None:
    blind = await _held(_Script(), _Observer(focus=RuntimeError("closed")))
    await blind.after_input(await blind.before_input(_command("type", text="x")))
    assert writes == [("release", TeachingReason.CAPTURE_FAILED)]
    writes.clear()
    capture = await _held(_Script(), _Observer(origin=_page(None)))
    prepared = await capture.before_input(_command("reload"))
    _Service.fail = RuntimeError("database down")
    await capture.after_input(prepared)
    assert writes == []
    _Service.fail = None


async def test_a_command_that_never_reached_the_page_pauses_and_ends_the_capture(
    writes: list[tuple[str, Any]],
) -> None:
    await _capture_for(_Script()).failed_input()
    assert writes == []
    redis = _Script()
    capture = await _held(redis)
    await capture.failed_input()
    assert capture.hold is None
    assert writes[0] == ("release", TeachingReason.CAPTURE_FAILED)
    assert await _hold.current(cast(Any, redis), RUN, "call-1") is None


async def test_a_pause_that_cannot_be_written_is_left_to_the_sweep(
    writes: list[tuple[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    capture = await _held(_Script())
    hold = capture.hold
    assert hold is not None
    _Service.fail = RuntimeError("secret detail that must not be logged")
    with caplog.at_level("WARNING"):
        await capture._release(hold, TeachingReason.CAPTURE_FAILED)
    assert "pause deferred (RuntimeError)" in caplog.text
    assert "secret detail" not in caplog.text
    _Service.fail = None


def test_capture_is_attached_only_for_the_runs_own_person_on_a_provisioned_cdp_tab(
    monkeypatch: pytest.MonkeyPatch, writes: list[tuple[str, Any]]
) -> None:
    redis = _Script()
    monkeypatch.setattr(_capture.live_browse, "client", lambda: redis)
    audience = SimpleNamespace(user_id=USER, browses_signed_in=True, shared_transcript=False)
    deps = SimpleNamespace(
        audience=audience,
        organization_id=ORG,
        run_id=RUN,
        agent_id=AGENT,
        impersonated=False,
        delegated=False,
        run_person=USER,
        user_id=str(USER),
    )
    page = SimpleNamespace(observe_structure=_Observer(), native_id=None)

    def attach(**changes: Any) -> HoldCapture | None:
        merged = SimpleNamespace(**{**vars(deps), **changes})
        return _capture.attach(cast(Any, merged), page, provisioned=True, tab_id=None)

    assert attach() is not None
    assert attach(delegated=True) is None
    assert (
        attach(
            audience=SimpleNamespace(user_id=USER, browses_signed_in=False, shared_transcript=False)
        )
        is None
    )
    assert attach(run_person=uuid.uuid4()) is None
    assert _capture.attach(cast(Any, deps), page, provisioned=False, tab_id="t") is None
    native = SimpleNamespace(observe_structure=_Observer(), native_id="n")
    assert _capture.attach(cast(Any, deps), native, provisioned=True, tab_id="t") is None
    monkeypatch.setattr(_capture.live_browse, "client", lambda: None)
    assert attach() is None


_unused: Callable[..., Any] | None = None
