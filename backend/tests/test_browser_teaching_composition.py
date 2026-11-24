"""Two capture kinds composed on one tab: a failure in either one never reaches the browser.

A capture that raises is switched off and ended, logged by exception type only. A
protected, closed or guarded page admits nothing to either capture.
"""

import logging
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.agents.capabilities.browser_use._teaching_capture import BrowserTeachingCapture

pytestmark = pytest.mark.anyio

METHODS = ("begin", "begin_task", "before_action", "after_action", "finish_task")
INPUTS = ("before_input", "after_input", "failed_input")


class _Side:
    """One capture kind. Every call is recorded; the methods named in `fail` raise."""

    def __init__(self, *fail: str) -> None:
        self.fail = set(fail)
        self.calls: list[str] = []

    async def _do(self, name: str, result: Any = None) -> Any:
        self.calls.append(name)
        if name in self.fail:
            raise RuntimeError("secret page detail")
        return result

    async def begin(self, *_args: Any, **_kwargs: Any) -> str:
        return await self._do("begin", "takeover")

    async def begin_task(self, *_args: Any) -> None:
        await self._do("begin_task")

    async def before_action(self, *_args: Any) -> str:
        return await self._do("before_action", "prepared-action")

    async def after_action(self, *_args: Any) -> None:
        await self._do("after_action")

    async def finish_task(self, **_kwargs: Any) -> None:
        await self._do("finish_task")

    async def before_input(self, *_args: Any) -> str:
        return await self._do("before_input", "prepared-input")

    async def after_input(self, *_args: Any) -> None:
        await self._do("after_input")

    async def failed_input(self) -> None:
        await self._do("failed_input")

    async def end(self) -> None:
        await self._do("end")

    async def protect(self) -> None:
        await self._do("protect")

    async def close(self) -> None:
        await self._do("close")

    def event(self, event: Any) -> Any:
        self.calls.append("event")
        if "event" in self.fail:
            raise RuntimeError("secret page detail")
        return event


class _Guard:
    def __init__(self) -> None:
        self.active = False

    def event(self, event: Any) -> Any:
        return SimpleNamespace(guarded=event)


def _compose(
    simple: _Side | None, procedure: _Side | None, guard: _Guard | None = None
) -> BrowserTeachingCapture:
    return BrowserTeachingCapture(
        cast(Any, simple), cast(Any, procedure), cast(Any, guard or _Guard())
    )


@pytest.mark.parametrize(
    ("call", "args"),
    [
        ("begin_task", ("call-1", None)),
        ("before_action", (None, None)),
        ("after_action", (None,)),
    ],
)
async def test_a_failing_procedure_capture_is_switched_off_and_never_called_again(
    call: str, args: tuple[Any, ...], caplog: pytest.LogCaptureFixture
) -> None:
    procedure = _Side(call)
    capture = _compose(None, procedure)
    with caplog.at_level(logging.WARNING):
        await getattr(capture, call)(*args)
        await getattr(capture, call)(*args)
    assert procedure.calls == [call, "end"]
    assert "capture failed (RuntimeError)" in caplog.text
    assert "secret page detail" not in caplog.text


async def test_a_failing_finish_switches_the_procedure_off(
    caplog: pytest.LogCaptureFixture,
) -> None:
    procedure = _Side("finish_task")
    capture = _compose(None, procedure)
    await capture.finish_task(completed=True)
    await capture.finish_task(completed=True)
    assert procedure.calls == ["finish_task", "end"]


async def test_a_working_procedure_capture_gets_every_action_hook() -> None:
    procedure = _Side()
    capture = _compose(None, procedure)
    await capture.begin_task("call-1", None)
    assert await capture.before_action(cast(Any, None), None) == "prepared-action"
    await capture.after_action(cast(Any, "prepared-action"))
    await capture.finish_task(completed=False)
    assert procedure.calls == ["begin_task", "before_action", "after_action", "finish_task"]


async def test_begin_starts_the_hold_and_only_a_live_socket_starts_the_takeover() -> None:
    simple, procedure = _Side(), _Side()
    capture = _compose(simple, procedure)
    assert await capture.begin("call-1", "person") is None
    assert simple.calls == ["begin"] and procedure.calls == []
    emit = cast(Any, lambda _event: None)
    assert await capture.begin("call-1", user_id="person", emit=emit) == "takeover"
    assert procedure.calls == ["begin"]


async def test_begin_survives_either_capture_failing() -> None:
    simple, procedure = _Side("begin"), _Side("begin")
    capture = _compose(simple, procedure)
    emit = cast(Any, lambda _event: None)
    assert await capture.begin("call-1", "person", emit=emit) is None
    assert simple.calls == ["begin", "end"]
    assert procedure.calls == ["begin", "end"]
    assert await capture.begin("call-1", "person", emit=emit) is None
    assert simple.calls == ["begin", "end"] and procedure.calls == ["begin", "end"]


async def test_a_prepared_input_is_handed_back_to_the_capture_that_made_it() -> None:
    simple, procedure = _Side(), _Side()
    capture = _compose(simple, procedure)
    prepared = await capture.before_input(cast(Any, None))
    await capture.after_input(prepared)
    await capture.after_input(None)
    await capture.after_input("not prepared")
    await capture.failed_input()
    assert simple.calls == ["before_input", "after_input", "failed_input"]
    assert procedure.calls == simple.calls


async def test_input_with_nothing_to_record_is_not_prepared() -> None:
    assert await _compose(None, None).before_input(cast(Any, None)) is None


@pytest.mark.parametrize("call", INPUTS)
@pytest.mark.parametrize("failing", ["simple", "procedure"])
async def test_an_input_failure_in_one_capture_leaves_the_other_running(
    call: str, failing: str
) -> None:
    sides = {"simple": _Side(), "procedure": _Side()}
    sides[failing].fail.add(call)
    capture = _compose(sides["simple"], sides["procedure"])
    prepared = await capture.before_input(cast(Any, None))
    if call == "before_input":
        assert prepared is not None
    elif call == "after_input":
        await capture.after_input(prepared)
    else:
        await capture.failed_input()
    other = sides["procedure" if failing == "simple" else "simple"]
    assert call in other.calls
    assert sides[failing].calls[-1] == "end"


async def test_a_protected_page_admits_nothing_and_ends_both_captures() -> None:
    simple, procedure = _Side(), _Side()
    capture = _compose(simple, procedure)
    await capture.protect()
    assert simple.calls == ["end"] and procedure.calls == ["protect"]
    await capture.begin_task("call-1", None)
    assert await capture.begin("call-1", "person") is None
    assert await capture.before_action(cast(Any, None), None) is None
    assert await capture.before_input(cast(Any, None)) is None
    await capture.after_action(None)
    await capture.finish_task(completed=True)
    await capture.failed_input()
    assert simple.calls == ["end"] and procedure.calls == ["protect"]


async def test_a_guarded_page_blocks_capture_until_the_guard_lifts() -> None:
    guard = _Guard()
    procedure = _Side()
    capture = _compose(None, procedure, guard)
    guard.active = True
    event = cast(Any, "event")
    assert capture.guard.event(event).guarded == "event"
    assert (await capture.event(event)).guarded == "event"
    await capture.begin_task("call-1", None)
    assert procedure.calls == []
    guard.active = False
    await capture.begin_task("call-1", None)
    assert procedure.calls == ["begin_task"]


async def test_closing_ends_each_capture_once_and_a_failing_cleanup_is_logged_not_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    simple, procedure = _Side("end"), _Side("close")
    capture = _compose(simple, procedure)
    with caplog.at_level(logging.WARNING):
        await capture.close()
        await capture.end()
    assert simple.calls == ["end"] and procedure.calls == ["close"]
    assert "cleanup failed (RuntimeError)" in caplog.text
    assert "secret page detail" not in caplog.text


async def test_end_ends_both_captures_unless_the_tab_is_closed() -> None:
    simple, procedure = _Side(), _Side()
    capture = _compose(simple, procedure)
    await capture.end()
    assert simple.calls == ["end"] and procedure.calls == ["end"]
    await _compose(None, None).end()


async def test_an_event_passes_through_unless_the_procedure_capture_fails_on_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    event = cast(Any, "event")
    assert await _compose(None, None).event(event) == "event"
    simple, procedure = _Side(), _Side("event")
    capture = _compose(simple, procedure)
    with caplog.at_level(logging.WARNING):
        guarded = await capture.event(event)
    assert guarded.guarded == "event"
    assert simple.calls == ["end"] and procedure.calls == ["event", "end"]
    assert "event failed (RuntimeError)" in caplog.text
    assert await capture.before_input(cast(Any, None)) is None
    assert (await capture.event(event)).guarded == "event"


@pytest.mark.parametrize("only", ["simple", "procedure"])
async def test_a_tab_with_one_capture_kind_runs_the_whole_lifecycle(only: str) -> None:
    side = _Side()
    capture = _compose(side if only == "simple" else None, side if only == "procedure" else None)
    prepared = await capture.before_input(cast(Any, None))
    await capture.after_input(prepared)
    await capture.failed_input()
    await capture.end()
    await capture.protect()
    await capture.close()
    assert side.calls[:3] == ["before_input", "after_input", "failed_input"]
    assert await _compose(None, side if only == "procedure" else None).event(cast(Any, "e")) == "e"
    failing = _Side("event")
    broken = _compose(None, failing)
    assert (await broken.event(cast(Any, "e"))).guarded == "e"
    assert failing.calls == ["event", "end"]
