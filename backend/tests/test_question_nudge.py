"""Tests for reminding a chat once about an unanswered question.

A question parks its run for a day, and a person who missed the card has no
reason to look again until the run is already ended. The hourly sweep
reminds the chat once, halfway through the window, and the stamp is what
stops the next sweep sending it again. What these tests are about is that
"once": a run reminded, answered, continued, or outside a chat is left
alone, and the reminder carries the hours left rather than the question
itself - the card in the conversation already holds that.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.db.models.agent_run import RunStatus
from app.services.approvals import ApprovalService
from app.services.channels.handback import question_nudge_notice
from app.worker.tasks.approval_tasks import expire_approvals

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def _db() -> MagicMock:
    return MagicMock(flush=AsyncMock(), refresh=AsyncMock(), add=MagicMock())


def _chat_run(**overrides: object) -> MagicMock:
    """A run parked on a question in a Slack channel, never reminded."""
    state = {
        "messages": [],
        "tool_call_ids": {str(uuid.uuid4()): "call-1"},
        "questions": ["ask-1"],
        "channel_destination": {
            "bot_id": str(uuid.uuid4()),
            "platform_chat_id": "C1",
            "private_chat": False,
        },
    }
    run = MagicMock(
        id=uuid.uuid4(),
        status=RunStatus.AWAITING_ANSWER.value,
        paused_state=state,
        input_tokens=1200,
        output_tokens=340,
        cost_usd=Decimal("0.0210"),
        cost_is_partial=False,
        question_nudged_at=None,
    )
    run.surface = "slack"
    run.chat_notice_sent_at = None
    for name, value in overrides.items():
        setattr(run, name, value)
    return run


class TestNudgeUnanswered:
    """The reminder itself: one notice, once, to a chat that can hear it."""

    @staticmethod
    def _patches(runs: list[MagicMock]) -> dict[str, MagicMock]:
        by_id = {run.id: run for run in runs}

        async def claim(_db, run_id, **_kwargs):
            return by_id[run_id]

        async def stamp(_db, *, run, at, **_kwargs):
            run.question_nudged_at = at

        return {
            "list": patch(
                "app.services.approvals.agent_run_repo.list_unnudged_runs",
                new=AsyncMock(return_value=runs),
            ),
            "claim": patch(
                "app.services.approvals.agent_run_repo.claim_parked_run", side_effect=claim
            ),
            "stamp": patch(
                "app.services.approvals.agent_run_repo.record_question_nudge",
                side_effect=stamp,
            ),
            "post": patch(
                "app.services.approvals.queue_notices",
                new=AsyncMock(),
            ),
        }

    async def _sweep(self, runs: list[MagicMock]) -> tuple[int, dict[str, MagicMock]]:
        patches = self._patches(runs)
        started = {name: p.start() for name, p in patches.items()}
        try:
            return await ApprovalService(_db()).nudge_unanswered(), started
        finally:
            for p in patches.values():
                p.stop()

    async def test_a_run_halfway_to_expiry_gets_one_reminder(self):
        run = _chat_run()
        nudged, started = await self._sweep([run])

        assert nudged == 1
        started["stamp"].assert_awaited_once()
        (notice,) = started["post"].call_args.args[1]
        remaining = settings.QUESTION_EXPIRY_HOURS - settings.QUESTION_NUDGE_HOURS
        assert notice.text == question_nudge_notice(remaining)
        assert f"{remaining}h" in notice.text
        started["post"].assert_awaited_once()

    async def test_a_run_already_reminded_is_not_reminded_again(self):
        run = _chat_run(question_nudged_at=datetime.now(UTC) - timedelta(hours=1))
        nudged, started = await self._sweep([run])

        assert nudged == 0
        started["stamp"].assert_not_called()
        started["post"].assert_not_awaited()

    async def test_a_run_a_press_continued_meanwhile_is_left_alone(self):
        run = _chat_run()

        async def claim(_db, run_id, **_kwargs):
            run.status = RunStatus.RUNNING.value
            return run

        patches = self._patches([run])
        started = {name: p.start() for name, p in patches.items()}
        started["claim"].side_effect = claim
        try:
            nudged = await ApprovalService(_db()).nudge_unanswered()
        finally:
            for p in patches.values():
                p.stop()

        assert nudged == 0
        started["stamp"].assert_not_called()
        started["post"].assert_not_awaited()

    async def test_a_run_answered_since_listing_is_left_alone(self):
        state = dict(_chat_run().paused_state)
        state["question_results"] = {"ask-1": ["yes"]}
        run = _chat_run(paused_state=state)
        nudged, started = await self._sweep([run])

        assert nudged == 0
        started["stamp"].assert_not_called()
        started["post"].assert_not_awaited()

    async def test_a_run_outside_a_chat_posts_nothing_and_is_not_stamped(self):
        run = _chat_run()
        run.surface = "web"
        run.paused_state = {"messages": [], "questions": ["ask-1"]}
        nudged, started = await self._sweep([run])

        assert nudged == 0
        started["stamp"].assert_not_called()
        started["post"].assert_not_awaited()

    async def test_a_run_waiting_only_for_a_secret_gets_no_question_reminder(self) -> None:
        run = _chat_run()
        run.paused_state["questions"] = []
        run.paused_state["secret_requests"] = ["secret-1"]
        nudged, started = await self._sweep([run])
        assert nudged == 0
        assert run.question_nudged_at is None
        started["stamp"].assert_not_called()
        started["post"].assert_not_awaited()

    async def test_two_runs_are_each_reminded_once(self):
        runs = sorted((_chat_run() for _ in range(2)), key=lambda run: run.id)
        nudged, started = await self._sweep(list(reversed(runs)))

        assert nudged == 2
        assert started["stamp"].await_count == 2
        assert started["post"].await_count == 1
        assert len(started["post"].call_args.args[1]) == 2


class TestNudgeInTheSweep:
    """The hourly sweep reminds before it expires, in its own transaction."""

    async def test_the_sweep_calls_the_nudge_once(self):
        service = MagicMock(
            expire_stale=AsyncMock(return_value=0),
            nudge_unanswered=AsyncMock(return_value=1),
            expire_unanswered=AsyncMock(return_value=0),
            end_stranded=AsyncMock(return_value=0),
        )
        db_context = MagicMock()
        db_context.return_value.__aenter__ = AsyncMock(return_value=_db())
        db_context.return_value.__aexit__ = AsyncMock(return_value=False)
        with (
            patch("app.worker.tasks.approval_tasks.get_db_context", new=db_context),
            patch("app.worker.tasks.approval_tasks.ApprovalService", return_value=service),
            patch("app.worker.tasks.approval_tasks.ensure_channel_adapters"),
        ):
            await expire_approvals()

        service.nudge_unanswered.assert_awaited_once()
        service.expire_unanswered.assert_awaited_once()
        assert db_context.call_count == 4
