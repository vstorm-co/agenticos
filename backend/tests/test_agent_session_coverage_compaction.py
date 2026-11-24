"""Manual maintenance frames must terminate safely without admitting a chat turn."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import (
    AlreadyExistsError,
    AppException,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.services.agent_session import _CompactNowRequest
from tests.test_manual_conversation_compaction import (
    AGENT,
    CONVERSATION,
    PERSON,
    _events,
    _install_session_dependencies,
    _session,
)

pytestmark = pytest.mark.anyio


def _frame(**updates: object) -> dict[str, object]:
    return {
        "type": "compact_now",
        "request_id": "maintenance",
        "conversation_id": str(CONVERSATION),
        "agent_id": str(AGENT),
        **updates,
    }


@pytest.mark.parametrize("request_id", [None, 4, "", "x" * 129])
async def test_invalid_correlation_ids_do_not_query_credentials(
    monkeypatch: pytest.MonkeyPatch, request_id: object
) -> None:
    session = _session()
    authorize = AsyncMock()
    monkeypatch.setattr(session, "_reauthorize", authorize)
    await session.handle_frame(_frame(request_id=request_id))
    authorize.assert_not_awaited()
    assert _events(session) == []
    assert session._compaction_task is None


@pytest.mark.security
async def test_revoked_credentials_never_schedule_maintenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session()
    monkeypatch.setattr(session, "_reauthorize", AsyncMock(return_value=False))
    await session.handle_frame(_frame())
    assert session._compaction_task is None
    assert _events(session) == []


@pytest.mark.parametrize("invalid", [True, False])
@pytest.mark.parametrize("active", ["none", "turn", "compaction", "finished"])
async def test_unavailable_frames_do_not_mark_an_active_session_ready(
    monkeypatch: pytest.MonkeyPatch, invalid: bool, active: str
) -> None:
    session = _session()
    monkeypatch.setattr(session, "_reauthorize", AsyncMock(return_value=True))
    task = None
    if active != "none":
        task = asyncio.create_task(asyncio.Event().wait())
        if active == "finished":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            session._turn_task = task
            session._compaction_task = task
        else:
            setattr(session, "_turn_task" if active == "turn" else "_compaction_task", task)
    try:
        requested_id = "invalid" if invalid else str(uuid4())
        await session.handle_frame(_frame(conversation_id=requested_id))
        events = _events(session)
        assert events[0][0] == "compact_now_result"
        assert events[0][1]["status"] == "unavailable"
        assert events[0][1]["conversation_id"] == (None if invalid else requested_id)
        assert [kind for kind, _ in events].count("session_ready") == (
            active in {"none", "finished"}
        )
    finally:
        if task is not None and not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


@pytest.mark.parametrize("slot", ["_turn_task", "_compaction_task"])
async def test_an_active_session_reports_busy_without_starting_another_task(
    monkeypatch: pytest.MonkeyPatch, slot: str
) -> None:
    session = _session()
    monkeypatch.setattr(session, "_reauthorize", AsyncMock(return_value=True))
    task = asyncio.create_task(asyncio.Event().wait())
    setattr(session, slot, task)
    try:
        await session.handle_frame(_frame())
        assert _events(session) == [
            (
                "compact_now_result",
                {
                    "request_id": "maintenance",
                    "conversation_id": str(CONVERSATION),
                    "status": "busy",
                },
            )
        ]
        assert getattr(session, slot) is task
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_a_valid_frame_runs_maintenance_and_frees_its_task_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session()
    _install_session_dependencies(monkeypatch, session)
    monkeypatch.setattr(session, "_reauthorize", AsyncMock(return_value=True))
    await session.handle_frame(_frame())
    task = session._compaction_task
    assert task is not None
    await task
    assert session._compaction_task is None
    assert _events(session)[-2][1]["status"] == "compacted"
    session._compaction_task = task
    session._on_turn_done(task)
    assert session._compaction_task is None


@pytest.mark.parametrize(
    "error,status",
    [
        pytest.param(AuthorizationError(), "unavailable", marks=pytest.mark.security),
        (NotFoundError(), "unavailable"),
        (AlreadyExistsError(), "busy"),
        (BadRequestError(), "unavailable"),
        (AppException(), "failed"),
        (RuntimeError("provider broke"), "failed"),
    ],
)
async def test_maintenance_failures_release_admission_and_report_the_terminal_status(
    monkeypatch: pytest.MonkeyPatch, error: Exception, status: str
) -> None:
    session = _session()
    dependencies = _install_session_dependencies(monkeypatch, session)
    dependencies["runner"].compact_conversation.side_effect = error
    await session._run_compaction(_CompactNowRequest(**_frame()))
    assert dependencies["claim_state"] == {"held": False, "released": True}
    assert _events(session)[-2][1]["status"] == status
    assert _events(session)[-1][0] == "session_ready"
    assert session._admission_stack is None


async def test_a_chat_archived_after_admission_does_not_reach_the_summarizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session()
    dependencies = _install_session_dependencies(monkeypatch, session)
    eligible = SimpleNamespace(
        user_id=PERSON, project_id=None, workflow_id=None, origin=None, is_archived=False
    )
    archived = SimpleNamespace(**{**vars(eligible), "is_archived": True})
    dependencies["conversation_service"].get_conversation.side_effect = [eligible, archived]
    await session._run_compaction(_CompactNowRequest(**_frame()))
    dependencies["runner"].compact_conversation.assert_not_awaited()
    assert dependencies["claim_state"] == {"held": False, "released": True}
    assert _events(session)[-2][1]["status"] == "unavailable"


@pytest.mark.parametrize("finished", [False, True])
async def test_shutdown_cancels_only_active_maintenance_without_turn_grace(
    monkeypatch: pytest.MonkeyPatch, finished: bool
) -> None:
    session = _session()
    monkeypatch.setattr(session, "_stop_following", AsyncMock())
    monkeypatch.setattr(session, "_leave_room", AsyncMock())
    task = asyncio.create_task(asyncio.sleep(0) if finished else asyncio.Event().wait())
    if finished:
        await task
    session._compaction_task = task
    await session.shutdown()
    assert task.done()
    assert task.cancelled() is (not finished)
    assert session._closed is True
