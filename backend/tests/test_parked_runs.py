"""A decision, a resume or an answer on a parked run, as the routes make it (#2656).

What has to hold: a chat run is taken before its approval, on every decision a key's
included; a person's decision on the last pending call queues one continuation as
them after commit, and a key's continues nothing; the browser's own resume and
answer still run inline but post to the chat; and a run that is not a chat's is
exactly what it was.
"""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities.channel_tools._directory import ChannelDestination
from app.core.exceptions import BadRequestError, NotFoundError, RunExecutionError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_run import ApprovalStatus, RunSurface
from app.services.approvals import ApprovalService
from app.services.parked_runs import Continued, DecidedApproval, ParkedRunService

pytestmark = pytest.mark.anyio

_MODULE = "app.services.parked_runs"
ORG = uuid.uuid4()
USER = uuid.uuid4()
RUN = uuid.uuid4()
APPROVAL = uuid.uuid4()
BOT = uuid.uuid4()
DESTINATION = ChannelDestination(bot_id=BOT, platform_chat_id="C1:1.0", private_chat=False)


def _run(surface: str = "slack", *, destination: ChannelDestination | None = DESTINATION) -> Any:
    return MagicMock(
        id=RUN,
        organization_id=ORG,
        surface=surface,
        conversation_id=uuid.uuid4(),
        paused_state={
            "messages": [],
            "tool_call_ids": {},
            "channel_destination": None
            if destination is None
            else destination.model_dump(mode="json"),
        },
    )


def _person() -> AuthContext:
    return AuthContext(user_id=USER, organization_id=ORG, role=OrgRoleName.OWNER)


def _key() -> AuthContext:
    return AuthContext(
        user_id=None, organization_id=ORG, role=OrgRoleName.OWNER, api_key_id=uuid.uuid4()
    )


def _close(coro: Any) -> None:
    coro.close()


class _Patched:
    """The repositories and the spawns, patched, with the order of the locks recorded."""

    def __init__(self, run: Any | None = None) -> None:
        self.events: list[str] = []
        self.run = run if run is not None else _run()
        self.pending: list[Any] = []
        self.spawned: list[tuple[str, Any]] = []
        self.db = MagicMock()
        self.runner = MagicMock()
        self.runner.get_run = AsyncMock(return_value=self.run)
        self.runner.resume = AsyncMock(return_value=MagicMock(name="segment", settled={}))
        self.runner.answer = AsyncMock(return_value=MagicMock(name="segment", settled={}))
        self.approvals = MagicMock()
        self.decided = MagicMock(name="decided")

        async def decide(*args: Any, **kwargs: Any) -> Any:
            self.events.append("decide")
            return self.decided

        self.approvals.decide = AsyncMock(side_effect=decide)

        async def claim(*args: Any, **kwargs: Any) -> Any:
            self.events.append("claim run")
            return self.run

        async def settle(*args: Any, **kwargs: Any) -> int:
            self.events.append("settle")
            return 1

        self.settle_open = AsyncMock(side_effect=settle)
        self.get_approval = AsyncMock(return_value=MagicMock(run_id=RUN))
        self.get_run = AsyncMock(return_value=self.run)
        self.claim = AsyncMock(side_effect=claim)

        def spawn_after_commit(db: Any, coro: Any, *, name: str) -> None:
            self.spawned.append((name, coro))
            _close(coro)

        self.patches = [
            patch(f"{_MODULE}.agent_run_repo.get_approval", new=self.get_approval),
            patch(f"{_MODULE}.agent_run_repo.get_run", new=self.get_run),
            patch(f"{_MODULE}.agent_run_repo.claim_parked_run", new=self.claim),
            patch(
                f"{_MODULE}.agent_run_repo.list_approvals_for_run",
                new=AsyncMock(side_effect=lambda *a, **k: self.pending),
            ),
            patch(f"{_MODULE}.channel_prompt_repo.settle_open", new=self.settle_open),
            patch(f"{_MODULE}.spawn_after_commit", new=spawn_after_commit),
        ]
        self.service = ParkedRunService(self.db, runner=self.runner, approvals=self.approvals)

    def __enter__(self) -> _Patched:
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc: object) -> None:
        for p in reversed(self.patches):
            p.stop()

    def names(self) -> list[str]:
        return [name for name, _ in self.spawned]


class TestDeciding:
    @pytest.mark.security
    async def test_a_persons_decision_on_a_chat_run_takes_the_run_before_the_approval(self) -> None:
        with _Patched() as p:
            await p.service.decide(_person(), APPROVAL, approved=True, note=None)
        assert p.events == ["claim run", "settle", "decide"]
        assert p.settle_open.await_args.kwargs == {
            "run_id": RUN,
            "approval_id": APPROVAL,
            "by": "decided",
        }

    async def test_the_last_decision_spawns_one_continuation_as_the_decider_after_commit(
        self,
    ) -> None:
        with _Patched() as p, patch(f"{_MODULE}.continue_in_chat") as continuation:
            continuation.side_effect = lambda **kw: AsyncMock()()
            decided = await p.service.decide(_person(), APPROVAL, approved=True, note="ok")
        assert p.names() == [f"channel-continuation:{RUN}"]
        continuation.assert_called_once()
        assert isinstance(decided, DecidedApproval)
        assert decided.continues_in_chat is True
        assert decided.approval is p.decided

    async def test_the_continuation_is_built_for_the_decider_the_run_and_its_chat(self) -> None:
        with _Patched() as p, patch(f"{_MODULE}.continue_in_chat") as continuation:
            continuation.side_effect = lambda **kw: AsyncMock()()
            await p.service.decide(_person(), APPROVAL, approved=True, note=None)
        kwargs = continuation.call_args.kwargs
        assert kwargs["decider_user_id"] == USER
        assert kwargs["run_id"] == RUN
        assert kwargs["organization_id"] == ORG
        assert kwargs["destination"] == DESTINATION
        assert kwargs["approval_id"] == APPROVAL
        assert kwargs["impersonator_id"] is None

    async def test_a_decision_with_another_call_still_pending_spawns_nothing_but_says_it_continues_in_chat(
        self,
    ) -> None:
        with _Patched() as p:
            p.pending = [MagicMock(status=ApprovalStatus.PENDING.value)]
            decided = await p.service.decide(_person(), APPROVAL, approved=True, note=None)
        assert p.spawned == []
        assert decided.continues_in_chat is True

    async def test_a_key_decision_on_a_chat_run_is_recorded_and_continues_nothing(self) -> None:
        with _Patched() as p:
            decided = await p.service.decide(_key(), APPROVAL, approved=True, note=None)
        assert p.events == ["claim run", "settle", "decide"]
        assert p.settle_open.await_args.kwargs["approval_id"] == APPROVAL
        p.approvals.decide.assert_awaited_once()
        assert p.spawned == []
        assert decided.continues_in_chat is False

    @pytest.mark.parametrize("surface", ["web", "api"])
    async def test_a_decision_on_a_web_or_api_run_is_exactly_todays(self, surface: str) -> None:
        with _Patched(_run(surface)) as p:
            decided = await p.service.decide(_person(), APPROVAL, approved=True, note="n")
        assert p.events == ["decide"]
        p.settle_open.assert_not_awaited()
        assert p.spawned == []
        assert decided.approval is p.decided
        assert decided.continues_in_chat is False
        assert p.approvals.decide.await_args.args == (_person(), APPROVAL)
        assert p.approvals.decide.await_args.kwargs == {
            "approved": True,
            "note": "n",
            "remember_scope": None,
        }

    async def test_a_decision_on_a_chat_run_parked_before_its_chat_was_recorded_leaves_resuming_to_the_browser(
        self,
    ) -> None:
        with _Patched(_run(destination=None)) as p:
            decided = await p.service.decide(_person(), APPROVAL, approved=True, note=None)
        assert p.events == ["claim run", "settle", "decide"]
        assert p.spawned == []
        assert decided.continues_in_chat is False

    @pytest.mark.security
    async def test_an_unknown_approval_is_the_same_404(self) -> None:
        with _Patched() as p:
            p.get_approval.return_value = None
            p.approvals.decide.side_effect = NotFoundError(message="Approval not found")
            with pytest.raises(NotFoundError, match="Approval not found"):
                await p.service.decide(_person(), APPROVAL, approved=True, note=None)
        p.claim.assert_not_awaited()

    @pytest.mark.security
    async def test_an_approval_whose_run_vanished_is_left_to_the_approval_service(self) -> None:
        with _Patched() as p:
            p.get_run.return_value = None
            decided = await p.service.decide(_person(), APPROVAL, approved=True, note=None)
        p.claim.assert_not_awaited()
        assert decided.continues_in_chat is False

    @pytest.mark.security
    async def test_a_run_that_vanished_at_the_claim_is_left_to_the_approval_service(self) -> None:
        with _Patched() as p:
            p.claim.side_effect = None
            p.claim.return_value = None
            decided = await p.service.decide(_person(), APPROVAL, approved=True, note=None)
        p.settle_open.assert_not_awaited()
        assert decided.continues_in_chat is False

    async def test_a_refused_decision_raises_as_before_and_spawns_nothing(self) -> None:
        with _Patched() as p:
            p.approvals.decide.side_effect = BadRequestError(
                message="This request was already approved"
            )
            with pytest.raises(BadRequestError):
                await p.service.decide(_person(), APPROVAL, approved=True, note=None)
        assert p.spawned == []

    async def test_a_console_decision_still_wakes_a_workflow_waiting_on_its_run(self) -> None:
        pending = MagicMock(
            status=ApprovalStatus.PENDING.value, organization_id=ORG, run_id=RUN, tool_args={}
        )
        decided = MagicMock(run_id=RUN, organization_id=ORG)
        woken: list[str] = []

        def wake(coro: Any, *, name: str) -> None:
            woken.append(name)
            coro.close()

        db = MagicMock()
        with (
            patch(
                "app.services.approvals.agent_run_repo.get_approval",
                AsyncMock(return_value=pending),
            ),
            patch(
                "app.services.approvals.agent_run_repo.decide_approval",
                AsyncMock(return_value=decided),
            ),
            patch(
                "app.services.approvals.voice_call_repo.is_live_run", AsyncMock(return_value=False)
            ),
            patch("app.services.approvals.record_audit", AsyncMock()),
            patch(
                "app.services.approvals.agent_run_repo.list_approvals_for_run",
                AsyncMock(return_value=[pending]),
            ),
            patch(
                "app.services.approvals.spawn_after_commit",
                side_effect=lambda d, c, name: wake(c, name=name),
            ),
            patch(f"{_MODULE}.agent_run_repo.get_approval", AsyncMock(return_value=pending)),
            patch(f"{_MODULE}.agent_run_repo.get_run", AsyncMock(return_value=_run("web"))),
        ):
            service = ParkedRunService(db, runner=MagicMock(), approvals=ApprovalService(db))
            await service.decide(_person(), APPROVAL, approved=True, note=None)
        assert woken == ["workflow-approval-wake"]


class TestResuming:
    async def test_a_manual_resume_queues_handback_in_the_segment_transaction(self) -> None:
        callback = AsyncMock()
        with _Patched() as p, patch(f"{_MODULE}.queue_segment", return_value=callback) as queue:
            result = await p.service.resume(_person(), RUN)
        assert result.continues_in_chat is True
        assert result.segment is p.runner.resume.return_value
        p.runner.resume.assert_awaited_once_with(_person(), RUN, on_segment=callback)
        queue.assert_called_once()
        assert queue.call_args.args[:2] == (p.db, DESTINATION)
        assert p.spawned == []
        assert p.settle_open.await_args.kwargs["by"] == "continued"

    @pytest.mark.parametrize("surface", ["web", "api"])
    async def test_a_manual_resume_of_any_other_run_is_todays(self, surface: str) -> None:
        with _Patched(_run(surface)) as p:
            result = await p.service.resume(_person(), RUN)
        assert p.spawned == []
        p.settle_open.assert_not_awaited()
        assert result.continues_in_chat is False
        p.runner.resume.assert_awaited_once_with(_person(), RUN, on_segment=None)

    async def test_a_key_resumes_a_run_a_key_started_as_before(self) -> None:
        key = _key()
        with _Patched() as p:
            result = await p.service.resume(key, RUN)
        assert p.spawned == []
        p.settle_open.assert_not_awaited()
        assert result.continues_in_chat is False
        p.runner.resume.assert_awaited_once_with(key, RUN, on_segment=None)

    async def test_a_refused_resume_raises_as_before_and_posts_nothing(self) -> None:
        with _Patched() as p:
            p.runner.resume.side_effect = BadRequestError(
                message="This run is not waiting for approval"
            )
            with pytest.raises(BadRequestError):
                await p.service.resume(_person(), RUN)
        assert p.spawned == []

    async def test_a_resume_failure_keeps_the_transactional_handback_callback(self) -> None:
        callback = AsyncMock()
        with _Patched() as p, patch(f"{_MODULE}.queue_segment", return_value=callback):
            p.runner.resume.side_effect = RunExecutionError(message="The run failed: x")
            with pytest.raises(RunExecutionError):
                await p.service.resume(_person(), RUN)
        assert p.runner.resume.await_args.kwargs["on_segment"] is callback
        assert p.spawned == []


class TestAnswering:
    async def test_a_workflow_answer_queues_its_owner_instead_of_executing_inline(self) -> None:
        with (
            _Patched(_run(RunSurface.WORKFLOW.value)) as p,
            patch("app.services.workflow_execution.WorkflowExecutionService") as workflows,
        ):
            workflows.return_value.answer_agent_questions = AsyncMock(return_value=MagicMock())
            result = await p.service.answer(_person(), RUN, {"q": [{"answer": "yes"}]})

        workflows.return_value.answer_agent_questions.assert_awaited_once_with(
            _person(), RUN, {"q": [{"answer": "yes"}]}
        )
        p.runner.answer.assert_not_awaited()
        p.runner.resume.assert_not_awaited()
        assert result.segment.run.id == RUN
        assert result.segment.output == ""
        assert result.continues_in_chat is False

    async def test_a_workflow_run_without_an_owner_is_not_resumed_inline(self) -> None:
        with (
            _Patched(_run(RunSurface.WORKFLOW.value)) as p,
            patch("app.services.workflow_execution.WorkflowExecutionService") as workflows,
        ):
            workflows.return_value.answer_agent_questions = AsyncMock(return_value=None)
            with pytest.raises(BadRequestError, match="no longer waiting"):
                await p.service.answer(_person(), RUN, {})

        p.runner.answer.assert_not_awaited()

    async def test_the_generic_resume_route_cannot_bypass_a_workflow(self) -> None:
        with (
            _Patched(_run(RunSurface.WORKFLOW.value)) as p,
            pytest.raises(BadRequestError, match="continued by its workflow"),
        ):
            await p.service.resume(_person(), RUN)

        p.runner.resume.assert_not_awaited()

    async def test_an_answer_settles_buttons_and_installs_transactional_handback(self) -> None:
        callback = AsyncMock()
        with _Patched() as p, patch(f"{_MODULE}.queue_segment", return_value=callback):
            result = await p.service.answer(_person(), RUN, {"q": [{"value": "a"}]})
        assert p.settle_open.await_args.kwargs["by"] == "answered"
        assert result.continues_in_chat is True
        p.runner.answer.assert_awaited_once_with(
            _person(), RUN, {"q": [{"value": "a"}]}, on_segment=callback
        )
        assert p.spawned == []

    async def test_an_answer_on_a_web_run_is_todays(self) -> None:
        with _Patched(_run("web")) as p:
            result = await p.service.answer(_person(), RUN, {})
        assert p.spawned == []
        p.settle_open.assert_not_awaited()
        assert result.continues_in_chat is False
        assert isinstance(result, Continued)

    async def test_an_answer_failure_keeps_the_transactional_handback_callback(self) -> None:
        callback = AsyncMock()
        with _Patched() as p, patch(f"{_MODULE}.queue_segment", return_value=callback):
            p.runner.answer.side_effect = RunExecutionError(message="The run failed: y")
            with pytest.raises(RunExecutionError):
                await p.service.answer(_person(), RUN, {})
        assert p.runner.answer.await_args.kwargs["on_segment"] is callback
        assert p.spawned == []
