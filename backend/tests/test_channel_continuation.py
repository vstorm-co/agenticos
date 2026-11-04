"""A decision made outside a chat continues its run there (#2656).

What has to hold: a person's decision continues the parked run as them, once, and
posts the answer to the chat the run was asked in; only a *definite* refusal stops
it, and says so once; a run somebody else already continued is left in silence;
and nothing the background task meets is ever raised.
"""

import dataclasses
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities.channel_tools._directory import ChannelDestination
from app.core.audit import current_impersonator, set_impersonator
from app.core.exceptions import BadRequestError, RunExecutionError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_run import RunStatus
from app.services.agent_runner import RunSegment
from app.services.channels.continuation import (
    ChatDelivery,
    continue_in_chat,
    deliver_in_chat,
)
from app.services.channels.handback import REFUSED_NOTICE
from app.services.channels.router import Admission
from app.services.transcript import RecordedToolCall

pytestmark = pytest.mark.anyio

_MODULE = "app.services.channels.continuation"
ORG = uuid.uuid4()
RUN = uuid.uuid4()
BOT = uuid.uuid4()
DECIDER = uuid.uuid4()
APPROVAL = uuid.uuid4()
DESTINATION = ChannelDestination(bot_id=BOT, platform_chat_id="C1:1.0", private_chat=False)


def _run(
    *,
    status: str = RunStatus.AWAITING_APPROVAL.value,
    destination: Any = DESTINATION,
    parked_on: tuple[uuid.UUID, ...] = (APPROVAL,),
) -> Any:
    return MagicMock(
        id=RUN,
        organization_id=ORG,
        surface="slack",
        status=status,
        chat_notice_sent_at=None,
        paused_state={
            "tool_call_ids": {str(approval): f"call-{approval}" for approval in parked_on},
            "channel_destination": None
            if destination is None
            else destination.model_dump(mode="json"),
        },
    )


def _decider(role: str = OrgRoleName.OWNER) -> AuthContext:
    return AuthContext(user_id=DECIDER, organization_id=ORG, role=role)


def _segment() -> Any:
    return MagicMock(output="Done.", tool_calls=[], settled={}, generated_files=frozenset())


class _Patched:
    """Everything the continuation reaches for, patched; what happened recorded."""

    def __init__(self, *, run: Any | None = None, claimed: Any | None = None) -> None:
        self.events: list[str] = []
        self.run = run if run is not None else _run()
        self.claimed = claimed if claimed is not None else self.run
        self.bot = MagicMock(id=BOT, is_active=True, organization_id=ORG)
        self.db = MagicMock()
        self.savepoint = MagicMock(is_active=True)
        self.savepoint.rollback = AsyncMock()
        self.savepoint.commit = AsyncMock()
        self.db.begin_nested = AsyncMock(return_value=self.savepoint)
        self.pending: list[Any] = []
        self.resume = AsyncMock(return_value=_segment())
        self.deliver = AsyncMock()
        self.post_notice = AsyncMock()
        self.settle_open = AsyncMock()
        self.record_chat_notice = AsyncMock()
        self.admission = AsyncMock(return_value=Admission("admitted", "member"))
        self.incoming_for_run = AsyncMock(return_value=MagicMock(name="incoming"))
        self.decider_context = AsyncMock(return_value=_decider())
        self.get_bot = AsyncMock(return_value=self.bot)
        self.get_run = AsyncMock(return_value=self.run)

        async def claim(*args: Any, **kwargs: Any) -> Any:
            self.events.append("claim")
            return self.claimed

        @asynccontextmanager
        async def lock(bot_id: str, chat_id: str) -> AsyncIterator[None]:
            self.events.append("lock")
            self.lock_key = (bot_id, chat_id)
            yield

        @asynccontextmanager
        async def context() -> AsyncIterator[Any]:
            yield self.db

        runner = MagicMock()
        runner.resume = self.resume
        router = MagicMock()
        router.admission = self.admission
        prompts = MagicMock()
        prompts.deliver = self.deliver
        prompts_class = MagicMock(return_value=prompts)
        prompts_class.inherited_calls = MagicMock(return_value=[])
        prompts_class.with_inherited = MagicMock(side_effect=lambda segment, inherited: segment)
        self.prompts_class = prompts_class
        self.patches = [
            patch(f"{_MODULE}.chat_lock", new=lock),
            patch(f"{_MODULE}.get_db_context", new=context),
            patch(f"{_MODULE}.channel_bot_repo.get_for_org", new=self.get_bot),
            patch(f"{_MODULE}.agent_run_repo.get_run", new=self.get_run),
            patch(f"{_MODULE}.agent_run_repo.claim_parked_run", new=claim),
            patch(
                f"{_MODULE}.agent_run_repo.list_approvals_for_run",
                new=AsyncMock(side_effect=lambda *a, **k: self.pending),
            ),
            patch(f"{_MODULE}.agent_run_repo.record_chat_notice", new=self.record_chat_notice),
            patch(f"{_MODULE}.channel_prompt_repo.settle_open", new=self.settle_open),
            patch(f"{_MODULE}.decider_context", new=self.decider_context),
            patch(f"{_MODULE}.incoming_for_run", new=self.incoming_for_run),
            patch(f"{_MODULE}.ChannelMessageRouter", return_value=router),
            patch(f"{_MODULE}.AgentRunnerService", return_value=runner),
            patch(f"{_MODULE}.ChannelPrompts", new=prompts_class),
            patch(f"{_MODULE}.queue_notices", new=self.post_notice),
            patch(f"{_MODULE}.queue_segment", return_value=AsyncMock()),
        ]
        self.original_claim = claim

    def __enter__(self) -> _Patched:
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc: object) -> None:
        for p in reversed(self.patches):
            p.stop()


async def _continue(impersonator_id: uuid.UUID | None = None) -> None:
    await continue_in_chat(
        organization_id=ORG,
        run_id=RUN,
        decider_user_id=DECIDER,
        impersonator_id=impersonator_id,
        destination=DESTINATION,
        approval_id=APPROVAL,
    )


class TestContinuing:
    async def test_a_decided_run_continues_as_the_decider_and_posts_once(self) -> None:
        with _Patched() as p:
            order: list[str] = []
            p.settle_open.side_effect = lambda *a, **k: order.append("settle")
            real_resume = p.resume

            async def resume(ctx: AuthContext, run_id: uuid.UUID, **kwargs: Any) -> Any:
                order.append("resume")
                return await real_resume(ctx, run_id, **kwargs)

            with patch(f"{_MODULE}.AgentRunnerService") as runner_class:
                runner_class.return_value.resume = resume
                await _continue()

        real_resume.assert_awaited_once()
        assert real_resume.await_args.args[0].user_id == DECIDER
        p.deliver.assert_not_awaited()
        assert callable(p.resume.await_args.kwargs["on_segment"])
        assert p.settle_open.await_args.kwargs["by"] == "continued"
        assert order == ["settle", "resume"]
        p.db.begin_nested.assert_awaited_once()
        p.savepoint.commit.assert_awaited_once()
        p.post_notice.assert_not_awaited()

    async def test_a_decision_by_an_app_admin_outside_the_organization_continues_as_them(
        self,
    ) -> None:
        admin = AuthContext(user_id=DECIDER, organization_id=ORG, role="", is_app_admin=True)
        with _Patched() as p:
            p.decider_context.return_value = admin
            await _continue()
        assert p.resume.await_args.args[0] is admin
        p.deliver.assert_not_awaited()
        assert callable(p.resume.await_args.kwargs["on_segment"])

    async def test_a_membership_check_the_platform_cannot_answer_lets_the_continuation_proceed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with _Patched() as p, caplog.at_level(logging.INFO):
            p.admission.return_value = Admission("unconfirmed", "membership_unconfirmed")
            await _continue()
        p.resume.assert_awaited_once()
        p.deliver.assert_not_awaited()
        assert callable(p.resume.await_args.kwargs["on_segment"])
        assert any(
            "membership_unconfirmed" in r.getMessage() and str(RUN) in r.getMessage()
            for r in caplog.records
        )

    async def test_it_takes_the_chat_lock_before_it_claims_the_run(self) -> None:
        with _Patched() as p:
            await _continue()
        assert p.events == ["lock", "claim"]
        assert p.lock_key == (str(BOT), DESTINATION.platform_chat_id)

    async def test_the_impersonating_admin_is_named_during_the_continuation(self) -> None:
        admin_id = uuid.uuid4()
        seen: list[uuid.UUID | None] = []
        with _Patched() as p:

            async def resume(*a: Any, **k: Any) -> Any:
                seen.append(current_impersonator())
                return _segment()

            p.resume.side_effect = resume
            try:
                await _continue(impersonator_id=admin_id)
            finally:
                set_impersonator(None)
        assert seen == [admin_id]

    @pytest.mark.parametrize(
        "status",
        [RunStatus.RUNNING.value, RunStatus.COMPLETED.value, RunStatus.CANCELLED.value],
    )
    async def test_a_run_already_continued_or_ended_is_left_in_silence(self, status: str) -> None:
        with _Patched(claimed=_run(status=status)) as p:
            await _continue()
        p.resume.assert_not_awaited()
        p.deliver.assert_not_awaited()
        p.post_notice.assert_not_awaited()

    async def test_a_run_that_parked_on_a_question_meanwhile_is_left_alone_and_unstamped(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A manual Resume that re-parked the run on a question is not this decision's run."""
        parked = _run(status=RunStatus.AWAITING_ANSWER.value, parked_on=())
        with _Patched(run=parked) as p, caplog.at_level(logging.INFO):
            await _continue()
        p.resume.assert_not_awaited()
        p.post_notice.assert_not_awaited()
        p.record_chat_notice.assert_not_awaited()
        assert any(str(RUN) in r.getMessage() for r in caplog.records)

    async def test_a_run_that_moved_to_the_question_before_the_claim_is_left_alone(self) -> None:
        with _Patched(claimed=_run(status=RunStatus.AWAITING_ANSWER.value, parked_on=())) as p:
            await _continue()
        p.resume.assert_not_awaited()
        p.post_notice.assert_not_awaited()
        p.record_chat_notice.assert_not_awaited()

    @pytest.mark.security
    async def test_a_run_that_parked_on_another_approval_meanwhile_is_left_alone(self) -> None:
        elsewhere = _run(parked_on=(uuid.uuid4(),))
        with _Patched(run=elsewhere) as p:
            p.admission.return_value = Admission("refused", "access_policy")
            await _continue()
        p.resume.assert_not_awaited()
        p.post_notice.assert_not_awaited()
        p.record_chat_notice.assert_not_awaited()

    async def test_a_run_that_is_not_parked_when_first_read_is_left_in_silence(self) -> None:
        with _Patched(run=_run(status=RunStatus.COMPLETED.value)) as p:
            await _continue()
        assert "claim" not in p.events
        p.resume.assert_not_awaited()
        p.post_notice.assert_not_awaited()

    async def test_a_run_that_vanished_is_left_in_silence(self) -> None:
        with _Patched() as p:
            p.get_run.return_value = None
            await _continue()
        p.resume.assert_not_awaited()
        p.post_notice.assert_not_awaited()

    async def test_a_run_that_vanished_before_the_claim_is_left_in_silence(self) -> None:
        with _Patched() as p:
            p.claimed = None
            await _continue()
        p.resume.assert_not_awaited()
        p.post_notice.assert_not_awaited()

    async def test_a_run_with_a_decision_still_pending_is_left_in_silence(self) -> None:
        with _Patched() as p:
            p.pending = [MagicMock(status="pending")]
            await _continue()
        p.resume.assert_not_awaited()
        p.post_notice.assert_not_awaited()

    async def test_a_destination_that_no_longer_matches_the_run_is_left_in_silence(self) -> None:
        other = ChannelDestination(bot_id=BOT, platform_chat_id="C2", private_chat=False)
        with _Patched(run=_run(destination=other)) as p:
            await _continue()
        p.resume.assert_not_awaited()
        p.post_notice.assert_not_awaited()

    async def test_a_destination_that_changed_before_the_claim_is_left_in_silence(self) -> None:
        other = ChannelDestination(bot_id=BOT, platform_chat_id="C2", private_chat=False)
        with _Patched(claimed=_run(destination=other)) as p:
            await _continue()
        p.resume.assert_not_awaited()
        p.post_notice.assert_not_awaited()

    async def test_a_switched_off_bot_posts_nothing(self) -> None:
        with _Patched() as p:
            p.bot.is_active = False
            await _continue()
        p.resume.assert_not_awaited()
        p.post_notice.assert_not_awaited()

    async def test_a_missing_bot_posts_nothing(self) -> None:
        with _Patched() as p:
            p.get_bot.return_value = None
            await _continue()
        p.resume.assert_not_awaited()
        p.post_notice.assert_not_awaited()


class TestRefusing:
    @pytest.mark.parametrize(
        "decider", [None, _decider(OrgRoleName.MEMBER)], ids=["gone", "member"]
    )
    async def test_a_decider_no_longer_admitted_or_no_longer_deciding_is_refused(
        self, decider: AuthContext | None
    ) -> None:
        with _Patched() as p:
            p.decider_context.return_value = decider
            await _continue()
        p.post_notice.assert_awaited_once()
        assert p.post_notice.await_args.args[1][0].text == REFUSED_NOTICE
        p.record_chat_notice.assert_awaited_once()
        p.resume.assert_not_awaited()

    async def test_a_room_that_definitely_refuses_the_asker_runs_nothing_and_is_refused(
        self,
    ) -> None:
        with _Patched() as p:
            p.admission.return_value = Admission("refused", "access_policy")
            await _continue()
        p.resume.assert_not_awaited()
        p.deliver.assert_not_awaited()
        assert p.post_notice.await_args.args[1][0].text == REFUSED_NOTICE
        p.record_chat_notice.assert_awaited_once()

    async def test_a_chat_that_started_over_is_told_the_run_could_not_continue(self) -> None:
        with _Patched() as p:
            p.incoming_for_run.return_value = None
            await _continue()
        p.admission.assert_not_awaited()
        p.resume.assert_not_awaited()
        assert p.post_notice.await_args.args[1][0].text == REFUSED_NOTICE

    async def test_a_refusal_already_told_is_not_told_again(self) -> None:
        run = _run()
        run.chat_notice_sent_at = "earlier"
        with _Patched(run=run) as p:
            p.admission.return_value = Admission("refused", "access_policy")
            await _continue()
        p.post_notice.assert_not_awaited()
        p.record_chat_notice.assert_not_awaited()

    async def test_a_refusal_after_the_run_moved_on_is_silent(self) -> None:
        with _Patched(claimed=_run(status=RunStatus.RUNNING.value)) as p:
            p.admission.return_value = Admission("refused", "access_policy")
            await _continue()
        p.post_notice.assert_not_awaited()
        p.record_chat_notice.assert_not_awaited()

    async def test_a_continuation_that_cannot_be_built_says_so_once_and_leaves_the_run_parked(
        self,
    ) -> None:
        with _Patched() as p:
            p.resume.side_effect = BadRequestError(message="The agent version is gone")
            await _continue()
        p.savepoint.rollback.assert_awaited_once()
        p.post_notice.assert_awaited_once()
        assert p.post_notice.await_args.args[1][0].text == REFUSED_NOTICE
        p.record_chat_notice.assert_awaited_once()
        p.deliver.assert_not_awaited()

    async def test_a_savepoint_the_resume_already_closed_is_not_rolled_back_again(self) -> None:
        with _Patched() as p:
            p.savepoint.is_active = False
            p.resume.side_effect = BadRequestError(message="gone")
            await _continue()
        p.savepoint.rollback.assert_not_awaited()
        assert p.post_notice.await_args.args[1][0].text == REFUSED_NOTICE

    async def test_a_savepoint_the_resume_already_closed_is_not_committed_again(self) -> None:
        with _Patched() as p:
            p.savepoint.is_active = False
            await _continue()
        p.savepoint.commit.assert_not_awaited()
        p.deliver.assert_not_awaited()
        assert callable(p.resume.await_args.kwargs["on_segment"])

    async def test_a_continuation_that_failed_while_running_says_why_as_a_press_would(
        self,
    ) -> None:
        with _Patched() as p:
            p.resume.side_effect = RunExecutionError(message="The run failed: x")
            await _continue()
        p.post_notice.assert_not_awaited()
        assert callable(p.resume.await_args.kwargs["on_segment"])
        p.record_chat_notice.assert_not_awaited()
        p.savepoint.rollback.assert_not_awaited()
        p.deliver.assert_not_awaited()


class TestNeverRaising:
    async def test_nothing_it_meets_is_raised(self, caplog: pytest.LogCaptureFixture) -> None:
        with _Patched() as p, caplog.at_level(logging.ERROR):
            p.resume.side_effect = RuntimeError("boom")
            await _continue()
        assert any(str(RUN) in r.getMessage() for r in caplog.records)


class TestDeliveringAManualContinuation:
    @staticmethod
    def _said() -> ChatDelivery:
        call = RecordedToolCall(tool_call_id="t1", tool_name="send_email", args={}, result="ok")
        return ChatDelivery(
            output="Sent.", tool_calls=(call,), generated_files=frozenset({"a.png"})
        )

    async def _deliver(self) -> None:
        await deliver_in_chat(
            organization_id=ORG, run_id=RUN, destination=DESTINATION, said=self._said()
        )

    async def test_a_manual_continuation_is_posted_to_its_chat(self) -> None:
        with _Patched() as p:
            await self._deliver()
        assert p.events == ["lock"]
        p.deliver.assert_awaited_once()
        kwargs = p.deliver.await_args.kwargs
        assert kwargs["platform_chat_id"] == DESTINATION.platform_chat_id
        segment = kwargs["segment"]
        assert isinstance(segment, RunSegment)
        assert segment.output == "Sent."
        assert [c.tool_call_id for c in segment.tool_calls] == ["t1"]
        assert segment.generated_files == frozenset({"a.png"})

    async def test_a_manual_continuation_is_not_posted_into_a_room_that_refuses_the_asker(
        self,
    ) -> None:
        with _Patched() as p:
            p.admission.return_value = Admission("refused", "left_channel")
            await self._deliver()
        p.deliver.assert_not_awaited()

    async def test_a_manual_continuation_for_a_chat_that_started_over_posts_nothing(self) -> None:
        with _Patched() as p:
            p.incoming_for_run.return_value = None
            await self._deliver()
        p.deliver.assert_not_awaited()

    async def test_a_manual_continuation_is_posted_when_membership_cannot_be_confirmed(
        self,
    ) -> None:
        with _Patched() as p:
            p.admission.return_value = Admission("unconfirmed", "membership_unconfirmed")
            await self._deliver()
        p.deliver.assert_awaited_once()

    async def test_a_manual_continuation_for_a_switched_off_bot_posts_nothing(self) -> None:
        with _Patched() as p:
            p.bot.is_active = False
            await self._deliver()
        p.deliver.assert_not_awaited()

    async def test_a_manual_continuation_for_a_missing_bot_or_run_posts_nothing(self) -> None:
        with _Patched() as p:
            p.get_bot.return_value = None
            await self._deliver()
        p.deliver.assert_not_awaited()
        with _Patched() as p:
            p.get_run.return_value = None
            await self._deliver()
        p.deliver.assert_not_awaited()

    async def test_a_manual_delivery_raises_for_durable_retry(self) -> None:
        with _Patched() as p:
            p.deliver.side_effect = RuntimeError("boom")
            with pytest.raises(RuntimeError, match="boom"):
                await self._deliver()


class TestWhatIsHandedOver:
    def test_what_is_handed_over_holds_no_row(self) -> None:
        call = RecordedToolCall(tool_call_id="t1", tool_name="x", args={}, result=None)
        segment = RunSegment(
            output="Hi",
            run=MagicMock(),
            tool_calls=[call],
            settled={},
            generated_files=frozenset({"f"}),
        )
        said = ChatDelivery.of(segment)
        assert said.output == "Hi"
        assert said.tool_calls == (call,)
        assert said.generated_files == frozenset({"f"})
        assert "run" not in {f.name for f in dataclasses.fields(ChatDelivery)}
