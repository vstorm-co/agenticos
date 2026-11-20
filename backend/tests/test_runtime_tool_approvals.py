"""A native action only runs after its live decision has been committed."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import anyio
import pytest

from app.agents.approval import ApprovalGranted, ApprovalRejected, ApprovalRequest
from app.agents.runtime_questions import (
    RuntimeAnswer,
    RuntimeQuestionRequest,
    RuntimeQuestionResponse,
)
from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext
from app.services import runtime_tool_approvals as approvals
from app.services.agent_runner import ApprovalChannel

pytestmark = [pytest.mark.anyio, pytest.mark.security]

type LiveFixture = tuple[ApprovalChannel, AsyncMock, AsyncMock, list[str]]


@pytest.fixture
def live(
    monkeypatch: pytest.MonkeyPatch,
) -> LiveFixture:
    channel = ApprovalChannel(organization_id=uuid4(), agent_id=uuid4(), run_id=uuid4())
    events: list[str] = []

    @asynccontextmanager
    async def sessions() -> AsyncIterator[MagicMock]:
        events.append("begin")
        yield MagicMock()
        events.append("commit")

    member = AsyncMock(
        return_value=AuthContext(
            user_id=uuid4(), organization_id=channel.organization_id, role="owner"
        )
    )
    service = AsyncMock()
    service.hidden_fields.return_value = frozenset()
    monkeypatch.setattr(approvals, "get_db_context", sessions)
    monkeypatch.setattr(approvals, "member_context", member)
    monkeypatch.setattr(approvals, "ApprovalService", MagicMock(return_value=service))
    return channel, member, service, events


def request(**changes: object) -> ApprovalRequest:
    return ApprovalRequest(
        capability_id="tables",
        tool_name="write_record",
        tool_call_id="native-one",
        tool_args={"record": "exact action"},
        **changes,
    )


@pytest.mark.parametrize("approved", [False, True])
async def test_live_decisions_preserve_the_full_action_and_commit_before_execution(
    live: LiveFixture, approved: bool
) -> None:
    channel, member, service, events = live

    async def ask(card: RuntimeQuestionRequest) -> RuntimeQuestionResponse:
        assert service.request.await_count == 1
        assert events[-1] == "commit"
        assert "exact action" in card.questions[0].question
        return RuntimeQuestionResponse(
            answers=[RuntimeAnswer(selected=["Yes" if approved else "No"])]
        )

    result = await channel.live(request(always_asks=True), user_id=uuid4(), questions=ask)
    assert isinstance(result, ApprovalGranted if approved else ApprovalRejected)
    assert not channel.parked and not channel.requested
    assert member.await_count == 3
    assert service.decide.call_args.kwargs == {"approved": approved}
    assert events[-1] == "commit"
    service.expire_now.assert_not_awaited()
    if isinstance(result, ApprovalGranted):
        assert result.tool_args == {"record": "exact action"}


@pytest.mark.parametrize(
    "response",
    [
        RuntimeQuestionResponse(cancelled=True),
        RuntimeQuestionResponse(),
        RuntimeQuestionResponse(answers=[RuntimeAnswer(skipped=True)]),
        RuntimeQuestionResponse(answers=[RuntimeAnswer(answer="probably")]),
    ],
)
async def test_abandoned_or_ambiguous_cards_expire_without_running(
    live: LiveFixture, response: RuntimeQuestionResponse
) -> None:
    channel, _member, service, _events = live
    result = await channel.live(
        request(), user_id=uuid4(), questions=AsyncMock(return_value=response)
    )
    assert isinstance(result, ApprovalRejected)
    service.decide.assert_not_awaited()
    service.expire_now.assert_awaited_once()
    assert not channel.parked and not channel.requested


async def test_revoked_membership_before_a_decision_never_authorizes_the_action(
    live: LiveFixture,
) -> None:
    channel, member, service, _events = live
    member.side_effect = [member.return_value, member.return_value, None]
    with pytest.raises(AuthorizationError):
        await channel.live(
            request(),
            user_id=uuid4(),
            questions=AsyncMock(
                return_value=RuntimeQuestionResponse(answers=[RuntimeAnswer(selected=["Yes"])])
            ),
        )
    service.decide.assert_not_awaited()
    service.expire_now.assert_awaited_once()


@pytest.mark.parametrize("ctx", [None, "viewer"])
async def test_members_without_decision_authority_cannot_even_open_an_approval(
    live: LiveFixture, ctx: str | None
) -> None:
    channel, member, service, _events = live
    member.return_value = (
        None
        if ctx is None
        else AuthContext(user_id=uuid4(), organization_id=channel.organization_id, role=ctx)
    )
    with pytest.raises(AuthorizationError):
        await channel.live(request(), user_id=uuid4(), questions=AsyncMock())
    service.request.assert_not_awaited()
    assert not channel.requested


async def test_standing_consent_keeps_the_existing_run_audit_path(live: LiveFixture) -> None:
    channel, _member, service, _events = live
    channel.standing_consent_by = uuid4()
    ask = AsyncMock()
    assert isinstance(
        await channel.live(request(), user_id=uuid4(), questions=ask), ApprovalGranted
    )
    ask.assert_not_awaited()
    service.request.assert_not_awaited()
    assert channel.requested[0].standing


async def test_an_action_too_large_to_review_in_full_is_expired_instead_of_truncated(
    live: LiveFixture,
) -> None:
    channel, _member, service, _events = live
    action = request()
    action.tool_args["record"] = "x" * 32000
    ask = AsyncMock()
    assert isinstance(await channel.live(action, user_id=uuid4(), questions=ask), ApprovalRejected)
    ask.assert_not_awaited()
    service.expire_now.assert_awaited_once()


async def test_process_cancellation_expires_the_committed_action(live: LiveFixture) -> None:
    channel, _member, service, _events = live
    entered = anyio.Event()

    async def ask(_card: RuntimeQuestionRequest) -> RuntimeQuestionResponse:
        entered.set()
        await anyio.sleep_forever()

    async with anyio.create_task_group() as group:

        async def run() -> None:
            await channel.live(request(), user_id=uuid4(), questions=ask)

        group.start_soon(run)
        await entered.wait()
        group.cancel_scope.cancel()
    service.expire_now.assert_awaited_once()
    service.decide.assert_not_awaited()


async def test_hidden_action_fields_are_never_put_into_a_native_review_card(
    live: LiveFixture,
) -> None:
    channel, _member, service, _events = live
    service.hidden_fields.return_value = frozenset({"record"})
    questions = AsyncMock()
    result = await channel.live(request(always_asks=True), user_id=uuid4(), questions=questions)
    assert isinstance(result, ApprovalRejected)
    questions.assert_not_awaited()
    service.decide.assert_not_awaited()
    service.expire_now.assert_awaited_once()


def test_the_live_approval_window_ends_before_desktops_bridge_gives_up() -> None:
    """A slow but valid answer must still leave the action time to run."""
    import re
    from pathlib import Path

    from app.services.runtime_tool_approvals import LIVE_APPROVAL_SECONDS

    bridge = (
        Path(__file__).resolve().parents[2] / "desktop" / "runtime" / "platform-bridge.mts"
    ).read_text()
    timer = re.search(r"_agenticos/cancel_request[\s\S]*?\}, (\d+)\);", bridge)
    assert timer is not None
    abandon_ms = int(timer.group(1))
    assert 60 <= LIVE_APPROVAL_SECONDS < abandon_ms / 1000
