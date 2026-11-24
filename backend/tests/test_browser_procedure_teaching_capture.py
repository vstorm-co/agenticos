"""Only accepted input provenance reaches the value-free recorder; failures stay fixed."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4, uuid5

import pytest

from app.agents.audience import RunAudience
from app.agents.browser_events import BrowserCommand, BrowserEvent
from app.agents.capabilities.browser_use._protected import BrowserOutputGuard
from app.agents.deps import AgentDeps
from app.core.browser_procedure_teaching import (
    BrowserProcedureTeachingObservation,
    BrowserProcedureTeachingReason,
    BrowserProcedureTeachingRefused,
    BrowserProcedureTeachingState,
)
from app.core.permissions import AuthContext
from app.schemas.browser_procedure_teaching import BrowserProcedureTeachingRead
from app.services.browser_procedure_teaching import _capture
from app.services.browser_procedure_teaching._lease import BrowserProcedureTeachingIdentity
from tests.test_browser_procedure_teaching_contracts import ORIGIN, SECRET, TARGET
from tests.test_browser_procedure_teaching_native import Redis, connect, identity

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def receipt(held, **changes):
    now = datetime.now(UTC)
    return BrowserProcedureTeachingRead(
        id=uuid4(),
        agent_id=held.agent_id,
        run_id=held.run_id,
        call_id=held.call_id,
        tab_id=held.tab_id,
        target_skill_id=None,
        title="Synthetic recording",
        allowed_origins=(ORIGIN,),
        source="manual",
        status="recording",
        revision=1,
        reason_code=None,
        events=(),
        review=None,
        procedure=None,
        generation_state="none",
        generation_mode=None,
        max_cost_usd=None,
        proposal_id=None,
        created_at=now,
        expires_at=now + timedelta(hours=24),
        capture_ends_at=now + timedelta(minutes=30),
    ).model_copy(update=changes)


@pytest.fixture
async def recorder(monkeypatch):
    held, redis, guard = identity(), Redis(), BrowserOutputGuard()
    ctx = AuthContext(user_id=held.user_id, organization_id=held.organization_id, role="member")
    page = SimpleNamespace(
        observe=AsyncMock(
            return_value=BrowserProcedureTeachingObservation(origin=ORIGIN, target=TARGET)
        )
    )
    emit = AsyncMock(return_value=True)
    row = SimpleNamespace(
        id=uuid4(),
        organization_id=held.organization_id,
        owner_user_id=held.user_id,
        agent_id=held.agent_id,
        run_id=held.run_id,
        controller_id=held.controller_id,
        call_id=held.call_id,
        tab_id=held.tab_id,
        takeover_id=held.takeover_id,
        connection_id=held.connection_id,
        status=BrowserProcedureTeachingState.RECORDING,
        capture_ends_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    append = AsyncMock(return_value=receipt(held))
    pause = AsyncMock(return_value=receipt(held, status=BrowserProcedureTeachingState.PAUSED))
    db = AsyncMock()

    @asynccontextmanager
    async def transaction():
        yield db

    monkeypatch.setattr(_capture, "get_db_context", transaction)
    monkeypatch.setattr(_capture._access, "deployment_enabled", lambda _: True)
    monkeypatch.setattr(
        _capture._access, "admit", AsyncMock(return_value=SimpleNamespace(context=ctx))
    )
    monkeypatch.setattr(_capture._access, "authorize", AsyncMock())
    monkeypatch.setattr(_capture.repo, "active", AsyncMock(return_value=row))
    monkeypatch.setattr(
        _capture,
        "BrowserProcedureTeachingService",
        lambda *_: SimpleNamespace(append=append, pause_live=pause),
    )
    monkeypatch.setattr(_capture, "RENEW_SECONDS", 3600)
    capture = _capture.BrowserProcedureTeachingCapture(
        context=ctx,
        identity=BrowserProcedureTeachingIdentity.model_validate(
            held.model_dump(exclude={"connection_id", "takeover_id"})
        ),
        redis=redis,
        page=page,
        guard=guard,
        step=lambda: 7,
    )
    assert await connect(redis, held)
    takeover = await capture.begin(
        call_id=held.call_id,
        connection_id=held.connection_id,
        user_id=str(held.user_id),
        emit=emit,
    )
    assert takeover is not None
    row.takeover_id = takeover
    held = held.model_copy(update={"takeover_id": takeover})
    try:
        yield SimpleNamespace(
            capture=capture,
            held=held,
            redis=redis,
            guard=guard,
            row=row,
            page=page,
            emit=emit,
            append=append,
            pause=pause,
            context=ctx,
            db=db,
        )
    finally:
        await capture.close()


def command(r, kind, **values):
    return BrowserCommand(
        type=kind,
        by_user_id=str(r.held.user_id),
        control_connection_id=r.held.connection_id,
        control_sequence=9,
        **values,
    )


@pytest.mark.parametrize(
    ("kind", "values", "action", "mode"),
    [
        ("click", {"x": 40, "y": 25}, "click", "point"),
        ("type", {"text": SECRET}, "input_parameter", "focus"),
        ("scroll", {"dy": 100}, "scroll", "origin"),
        ("scroll", {"dy": -100}, "scroll", "origin"),
        ("navigate", {"url": ORIGIN + "?token=" + SECRET}, "navigate", None),
        ("back", {}, "navigate", None),
        ("forward", {}, "navigate", None),
        ("reload", {}, "navigate", None),
        ("key", {"key": "ArrowDown"}, "checkpoint", "focus"),
    ],
)
async def test_capture_records_only_role_origin_and_server_sequence(
    recorder, kind, values, action, mode
):
    r = recorder
    prepared = await r.capture.before_input(command(r, kind, **values))
    assert prepared.action == action
    assert prepared.input_id == uuid5(r.held.connection_id, "9")
    assert SECRET not in repr(prepared)
    if mode is not None:
        assert r.page.observe.call_args.args[0] == mode
    await r.capture.after_input(prepared)
    args = r.append.call_args
    assert args.kwargs["action"] == action
    assert SECRET not in repr(args)
    assert "text" not in args.kwargs and "url" not in args.kwargs
    assert r.emit.call_args.args[0].kind == "browser_procedure_teaching"
    assert SECRET not in r.emit.call_args.args[0].model_dump_json()


async def test_native_combobox_and_enter_use_closed_roles(recorder):
    r = recorder
    r.page.observe.return_value = BrowserProcedureTeachingObservation(
        origin=ORIGIN, target=TARGET.model_copy(update={"role": "combobox"})
    )
    assert (await r.capture.before_input(command(r, "type", text=SECRET))).action == "select"
    r.page.observe.return_value = BrowserProcedureTeachingObservation(
        origin=ORIGIN, target=TARGET.model_copy(update={"role": "button"})
    )
    assert (await r.capture.before_input(command(r, "key", key="Enter"))).action == "click"
    r.page.observe.return_value = BrowserProcedureTeachingObservation(
        origin=ORIGIN, human_required=True
    )
    prepared = await r.capture.before_input(command(r, "type", text=SECRET))
    assert prepared.observation.human_required and prepared.observation.target is None


@pytest.mark.parametrize("key", ["ArrowDown", "ArrowUp", "Home", "End", "Enter"])
async def test_native_combobox_keys_record_only_a_select_parameter(recorder, key):
    r = recorder
    r.page.observe.return_value = BrowserProcedureTeachingObservation(
        origin=ORIGIN, target=TARGET.model_copy(update={"role": "combobox"})
    )
    prepared = await r.capture.before_input(command(r, "key", key=key))
    assert prepared.action == "select" and key not in repr(prepared)
    await r.capture.after_input(prepared)
    assert r.append.call_args.kwargs["action"] == "select"
    assert "key" not in r.append.call_args.kwargs


@pytest.mark.parametrize(
    "change", ["connection", "person", "sequence", "paused", "missing", "different", "protected"]
)
async def test_wrong_live_authority_or_protected_page_never_prepares_capture(
    recorder, monkeypatch, change
):
    r = recorder
    data = command(r, "type", text=SECRET)
    if change == "connection":
        data = data.model_copy(update={"control_connection_id": uuid4()})
    elif change == "person":
        data = data.model_copy(update={"by_user_id": str(uuid4())})
    elif change == "sequence":
        data = data.model_copy(update={"control_sequence": None})
    elif change == "paused":
        r.row.status = BrowserProcedureTeachingState.PAUSED
    elif change == "missing":
        _capture.repo.active.return_value = None
    elif change == "different":
        r.row.takeover_id = uuid4()
    else:
        r.guard.protect(ORIGIN)
    assert await r.capture.before_input(data) is None
    await r.capture.after_input(None)
    r.append.assert_not_awaited()


@pytest.mark.parametrize(
    ("kind", "values"),
    [
        ("take_over", {}),
        ("give_back", {}),
        ("control_lost", {}),
        ("resize", {}),
        ("navigate", {}),
        ("scroll", {}),
        ("scroll", {"dy": 0}),
        ("click", {"x": 1}),
        ("click", {"y": 1}),
        ("type", {}),
        ("key", {}),
        ("key", {"key": "Tab"}),
        ("key", {"key": "Escape"}),
    ],
)
async def test_non_recordable_commands_store_no_keystrokes_or_invented_actions(
    recorder, kind, values
):
    assert await recorder.capture.before_input(command(recorder, kind, **values)) is None
    recorder.append.assert_not_awaited()


@pytest.mark.parametrize(
    "stage", ["before_refused", "before_error", "after_refused", "after_error", "input_error"]
)
async def test_errors_are_fixed_and_unknown_native_failure_ends_the_lease(recorder, stage, caplog):
    r = recorder
    if stage.startswith("before"):
        r.page.observe.side_effect = (
            BrowserProcedureTeachingRefused(BrowserProcedureTeachingReason.NATIVE_UNAVAILABLE)
            if stage.endswith("refused")
            else RuntimeError(SECRET)
        )
        assert await r.capture.before_input(command(r, "type", text=SECRET)) is None
    elif stage.startswith("after"):
        prepared = await r.capture.before_input(command(r, "type", text=SECRET))
        r.append.side_effect = (
            BrowserProcedureTeachingRefused(BrowserProcedureTeachingReason.AUTHORITY_CHANGED)
            if stage.endswith("refused")
            else RuntimeError(SECRET)
        )
        await r.capture.after_input(prepared)
    else:
        await r.capture.failed_input()
    r.pause.assert_awaited()
    assert SECRET not in caplog.text
    assert all(SECRET not in call.args[0].model_dump_json() for call in r.emit.call_args_list)
    if stage.endswith("error") and stage != "input_error":
        assert r.capture._lease is None


async def test_protection_and_close_are_sticky_and_remove_live_ownership(recorder):
    r = recorder
    before = r.capture._lease
    await r.capture.protect()
    assert r.capture._lease is None and r.capture._heartbeat is None
    assert r.pause.call_args.args[-1] == BrowserProcedureTeachingReason.PROTECTED
    assert (
        await r.capture.begin(
            call_id=r.held.call_id,
            connection_id=r.held.connection_id,
            user_id=str(r.held.user_id),
            emit=r.emit,
        )
        is None
    )
    await r.capture.after_input(None)
    await r.capture.close()
    assert before is not None


async def test_teaching_events_keep_ephemeral_preview_but_drop_every_opaque_text(recorder):
    r = recorder
    raw = BrowserEvent(
        kind="browser_step",
        call_id=r.held.call_id,
        step=1,
        run_id=str(r.held.run_id),
        tab_id=r.held.tab_id,
        url=ORIGIN + "?token=" + SECRET,
        title=SECRET,
        target=SECRET,
        reason=SECRET,
        detail=SECRET,
        goal=SECRET,
        image="ephemeral-preview",
    )
    event = r.capture.event(raw)
    assert SECRET not in event.model_dump_json() and event.url == ORIGIN
    assert event.image == "ephemeral-preview"
    r.guard.protect(ORIGIN)
    protected = r.guard.event(event)
    assert protected.image is None and protected.output_protected
    error = r.capture.event(
        BrowserEvent(kind="browser_control_error", call_id="call", step=1, detail=SECRET)
    )
    assert error.detail == "Browser input unavailable" and SECRET not in error.model_dump_json()


async def test_cancelled_input_observation_does_not_store_an_event(recorder):
    recorder.page.observe.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await recorder.capture.before_input(command(recorder, "type", text=SECRET))
    recorder.append.assert_not_awaited()


@pytest.mark.parametrize(
    "change",
    [
        "organization",
        "run",
        "agent",
        "impersonated",
        "delegated",
        "anonymous",
        "unsigned",
        "shared",
        "person",
        "user",
        "disabled",
        "guard",
        "admission",
    ],
)
async def test_recorder_creation_refuses_every_unsupported_audience(recorder, monkeypatch, change):
    r = recorder
    deps = AgentDeps(
        organization_id=r.held.organization_id,
        run_id=r.held.run_id,
        agent_id=r.held.agent_id,
        run_person=r.held.user_id,
        user_id=str(r.held.user_id),
        audience=RunAudience(user_id=r.held.user_id, browses_signed_in=True),
    )
    if change in {"organization", "run", "agent"}:
        setattr(deps, change + "_id", None)
    elif change in {"impersonated", "delegated"}:
        setattr(deps, change, True)
    elif change == "anonymous":
        deps.audience = None
    elif change == "unsigned":
        deps.audience = RunAudience(user_id=r.held.user_id)
    elif change == "shared":
        deps.audience = RunAudience(
            user_id=r.held.user_id, browses_signed_in=True, shared_transcript=True
        )
    elif change == "person":
        deps.run_person = uuid4()
    elif change == "user":
        deps.user_id = str(uuid4())
    elif change == "disabled":
        monkeypatch.setattr(_capture._access, "deployment_enabled", lambda _: False)
    elif change == "guard":
        r.guard.protect(ORIGIN)
    else:
        _capture._access.admit.side_effect = BrowserProcedureTeachingRefused(
            BrowserProcedureTeachingReason.AUTHORITY_CHANGED
        )
    assert (
        await _capture.BrowserProcedureTeachingCapture.create(
            deps=deps,
            tab_id=r.held.tab_id,
            redis=r.redis,
            page=r.page,
            guard=r.guard,
            step=lambda: 1,
        )
        is None
    )
