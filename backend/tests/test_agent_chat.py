"""Tests for chatting with a published agent over the WebSocket.

The chat is the one surface that does not simply await an answer: it iterates
the run, forwards events, and can be stopped halfway by a person closing a tab.
That is what makes the accounting worth proving here rather than trusting the
runner to have covered it - every way a chat turn can end has to reach run
history, including the ways that are not an answer.

The other half is who the run belongs to. A socket is long-lived; a membership
is not. A run must carry the person's own role at the moment they typed, never
the organization's and never none at all.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.tools import DeferredToolRequests

from app.agents.capabilities.budget import BudgetExceeded, BudgetScope
from app.agents.deps import AgentDeps
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import OrgRoleName
from app.db.models.agent_run import RunStatus, RunSurface
from app.services.agent_chat import (
    ChatAgentRunner,
    display_output,
    requested_agent_id,
    requested_environment_id,
    requested_model_profile_id,
)

pytestmark = pytest.mark.anyio


class _Iteration:
    """Stands in for `agent.iter` - an async context manager over one run."""

    def __init__(self, agent_run: MagicMock) -> None:
        self.agent_run = agent_run

    async def __aenter__(self) -> MagicMock:
        return self.agent_run

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


def _user() -> MagicMock:
    return MagicMock(id=uuid.uuid4(), full_name="Ada Lovelace")


def _db() -> MagicMock:
    db = MagicMock()
    db.commit = AsyncMock()
    return db


def _agent_run(output: object) -> MagicMock:
    agent_run = MagicMock()
    agent_run.result = MagicMock(output=output, all_messages=MagicMock(return_value=[]))
    return agent_run


def _prepared(output: object = "the refund window is 30 days") -> MagicMock:
    """A run the runner has already opened, with its agent stubbed."""
    prepared = MagicMock()
    prepared.run = MagicMock(id=uuid.uuid4())
    prepared.deps = AgentDeps()
    prepared.built.model_label = "gpt-4.1"
    prepared.built.agent.iter = MagicMock(return_value=_Iteration(_agent_run(output)))
    prepared.approvals.parked = {"approval-1": "call-1"}
    return prepared


def _membership(role: OrgRoleName = OrgRoleName.MEMBER) -> MagicMock:
    return MagicMock(role=role)


@contextmanager
def _runner(
    prepared: MagicMock, *, membership: MagicMock | None = _membership()
) -> Iterator[MagicMock]:
    """Patch out the row lookups and the runner, keeping this module's logic real.

    `membership=None` is someone with no standing in the organization.
    """
    with (
        patch("app.services.agent_chat.member_repo") as members,
        patch("app.services.agent_chat.AgentRunnerService") as runner_cls,
    ):
        members.get = AsyncMock(return_value=membership)
        runner_cls.return_value.prepare = AsyncMock(return_value=prepared)
        runner_cls.return_value.finish = AsyncMock()
        yield runner_cls.return_value


async def _nothing(agent_run: Any) -> None:
    """A surface that consumes the run without forwarding anything."""


async def _run(
    db: MagicMock,
    *,
    user: MagicMock | None = None,
    organization_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    ask_user: Any = None,
    stream: Any = _nothing,
    user_input: Any = "what is the refund window",
    attachments: Any = None,
):
    return await ChatAgentRunner(db).run(
        user=user or _user(),
        organization_id=organization_id or uuid.uuid4(),
        agent_id=agent_id or uuid.uuid4(),
        user_input=user_input,
        message_history=[],
        conversation_id=conversation_id,
        attachments=attachments,
        ask_user=ask_user or AsyncMock(return_value=[]),
        stream=stream,
    )


class TestAddressingAnAgent:
    """Which agent a frame names - and what happens when it names nothing."""

    @pytest.mark.parametrize("frame", [{}, {"agent_id": None}, {"agent_id": ""}])
    def test_a_frame_that_names_no_agent_keeps_the_general_assistant(self, frame):
        """No implicit default: an unnamed agent means the assistant, not a guess."""
        assert requested_agent_id(frame) is None

    def test_a_named_agent_is_read_back_as_its_id(self):
        agent_id = uuid.uuid4()

        assert requested_agent_id({"agent_id": str(agent_id)}) == agent_id


class TestAddressingAnEnvironment:
    """Which named environment a frame asks for, if any."""

    @pytest.mark.parametrize("frame", [{}, {"environment_id": None}, {"environment_id": ""}])
    def test_a_frame_that_names_no_environment_gets_the_default(self, frame):
        assert requested_environment_id(frame) is None

    def test_a_named_environment_is_read_back_as_its_id(self):
        environment_id = uuid.uuid4()

        assert requested_environment_id({"environment_id": str(environment_id)}) == environment_id

    def test_something_that_is_not_an_id_is_refused_rather_than_ignored(self):
        """Falling back to the default would run a version the person did not
        pick and say nothing about it."""
        with pytest.raises(BadRequestError) as refused:
            requested_environment_id({"environment_id": "not-a-uuid"})

        assert refused.value.details == {"environment_id": "not-a-uuid"}


class TestAddressingAModel:
    """Which model a frame asks for, on top of whatever the agent declares."""

    @pytest.mark.parametrize("frame", [{}, {"model_profile_id": None}, {"model_profile_id": ""}])
    def test_a_frame_that_names_no_model_defers_to_the_agent(self, frame):
        assert requested_model_profile_id(frame) is None

    def test_a_named_model_is_read_back_as_its_id(self):
        profile_id = uuid.uuid4()

        assert requested_model_profile_id({"model_profile_id": str(profile_id)}) == profile_id

    def test_something_that_is_not_an_id_is_refused_rather_than_ignored(self):
        """Ignoring it would answer on a model the person did not choose.

        The failure has to be loud here: falling back to the agent's own model
        looks like success, costs money, and says nothing about having
        substituted one model for another.
        """
        with pytest.raises(BadRequestError) as refused:
            requested_model_profile_id({"model_profile_id": "not-a-uuid"})

        assert refused.value.details == {"model_profile_id": "not-a-uuid"}

    def test_a_malformed_agent_id_is_refused_rather_than_ignored(self):
        """Ignoring it would answer as the assistant while the user picked an agent."""
        with pytest.raises(BadRequestError) as refused:
            requested_agent_id({"agent_id": "not-an-agent"})

        assert refused.value.details == {"agent_id": "not-an-agent"}


class TestWhatTheClientIsShown:
    def test_an_answer_is_shown_as_the_model_wrote_it(self):
        assert display_output("42 days") == "42 days"

    def test_a_parked_run_says_so_instead_of_showing_nothing(self):
        """A blank turn reads as the agent ignoring you; it is waiting on a person."""
        shown = display_output(DeferredToolRequests())

        assert "approval" in shown.lower()


class TestWhoTheRunBelongsTo:
    async def test_the_run_carries_the_chatters_own_role_in_this_organization(self):
        """Not the organization's, and not the agent owner's: the person typing."""
        user = _user()
        organization_id = uuid.uuid4()

        with _runner(_prepared(), membership=_membership(OrgRoleName.VIEWER)) as runner:
            await _run(_db(), user=user, organization_id=organization_id)

        ctx = runner.prepare.call_args.args[0]
        assert (ctx.user_id, ctx.organization_id, ctx.role) == (
            user.id,
            organization_id,
            OrgRoleName.VIEWER,
        )
        assert ctx.is_app_admin is False

    async def test_a_chatter_who_is_no_longer_a_member_never_opens_a_run(self):
        """A socket outlives a membership; the run must not outlive it too."""
        with _runner(_prepared(), membership=None) as runner:
            with pytest.raises(AuthorizationError):
                await _run(_db())

            runner.prepare.assert_not_called()


class TestRecordingTheRun:
    """Every way a chat turn ends has to reach run history."""

    async def test_a_chat_run_is_stamped_as_a_web_run_on_its_conversation(self):
        """Filed the same way a Playground or API run is, so `/runs` is complete."""
        conversation_id = uuid.uuid4()
        agent_id = uuid.uuid4()
        user = _user()

        with _runner(_prepared()) as runner:
            await _run(_db(), user=user, agent_id=agent_id, conversation_id=conversation_id)

        opened = runner.prepare.call_args
        assert opened.args[1] == agent_id
        assert opened.kwargs["surface"] is RunSurface.WEB
        assert opened.kwargs["conversation_id"] == conversation_id
        assert opened.kwargs["user_name"] == user.full_name

    async def test_an_answer_comes_back_with_the_model_that_produced_it(self):
        with _runner(_prepared("42 days")) as runner:
            turn = await _run(_db())

        assert (turn.output, turn.model_label) == ("42 days", "gpt-4.1")
        assert runner.finish.call_args.kwargs["status"] is RunStatus.COMPLETED

    async def test_a_failed_run_still_records_what_it_spent(self):
        """The tokens were spent before it broke; a budget that ignores that is not one."""
        db = _db()

        with _runner(_prepared()) as runner, pytest.raises(RuntimeError, match="went away"):
            await _run(db, stream=AsyncMock(side_effect=RuntimeError("the model went away")))

        finished = runner.finish.call_args.kwargs
        assert finished["status"] is RunStatus.FAILED
        assert finished["error"] == "the model went away"
        db.commit.assert_awaited_once()

    async def test_a_stopped_turn_is_recorded_as_cancelled_and_committed(self):
        """Cancellation never reaches the session's rollback-on-error, so the row
        would vanish with the turn unless this path commits it itself."""
        db = _db()

        with _runner(_prepared()) as runner, pytest.raises(asyncio.CancelledError):
            await _run(db, stream=AsyncMock(side_effect=asyncio.CancelledError))

        finished = runner.finish.call_args.kwargs
        assert finished["status"] is RunStatus.CANCELLED
        assert finished["error"] is None
        db.commit.assert_awaited_once()

    async def test_a_budget_stop_is_recorded_as_a_budget_stop_not_a_failure(self):
        """An operator filtering run history for problems should not wade through it."""
        stopped = BudgetExceeded(limit_usd=1, spent_usd=2, scope=BudgetScope.AGENT)

        with _runner(_prepared()) as runner, pytest.raises(BudgetExceeded):
            await _run(_db(), stream=AsyncMock(side_effect=stopped))

        finished = runner.finish.call_args.kwargs
        assert finished["status"] is RunStatus.BUDGET_EXCEEDED
        assert "budget exhausted" in finished["error"]

    async def test_a_run_that_ends_with_nothing_at_all_fails_loudly(self):
        """An empty answer persisted as the agent's reply would be a lie about it."""
        prepared = _prepared()
        prepared.built.agent.iter = MagicMock(return_value=_Iteration(MagicMock(result=None)))

        with _runner(prepared) as runner, pytest.raises(RuntimeError, match="without a result"):
            await _run(_db())

        assert runner.finish.call_args.kwargs["status"] is RunStatus.FAILED


class TestPausingMidRun:
    async def test_the_agent_can_put_a_question_to_the_person_who_is_chatting(self):
        """Only a live surface can answer one; without this wiring the tool is dead."""
        prepared = _prepared()
        ask_user = AsyncMock(return_value=[])

        with _runner(prepared):
            await _run(_db(), ask_user=ask_user)

        assert prepared.deps.ask_user is ask_user

    async def test_a_parked_tool_call_leaves_the_run_resumable(self):
        """The decision arrives later, from the queue - possibly tomorrow, in
        another process - so everything needed to continue goes on the row."""
        prepared = _prepared(DeferredToolRequests())

        with _runner(prepared) as runner:
            turn = await _run(_db())

        finished = runner.finish.call_args.kwargs
        assert finished["status"] is RunStatus.AWAITING_APPROVAL
        assert finished["paused_state"].tool_call_ids == {"approval-1": "call-1"}
        assert "approval" in turn.output.lower()


class TestAttachmentsAreRoutedHereAndNotBySurfaces:
    """Where a file goes depends on whether the agent has a workspace, and only
    `prepare` knows that - so a surface cannot have assembled the prompt yet.

    The WebSocket used to do this inline and no other surface did it at all,
    which made an attachment mean something different depending on where the
    person was sitting. Once a workspace is involved that would have been three
    different behaviours.
    """

    async def test_a_file_reaches_the_prompt_the_agent_is_run_with(self):
        attachment = SimpleNamespace(
            id=uuid.uuid4(),
            filename="raport.csv",
            mime_type="text/csv",
            size=512,
            storage_path="u/1/raport.csv",
            file_type="text",
            parsed_content="month,total\njan,10",
        )
        prepared = _prepared()
        prepared.workspace = None

        with _runner(prepared):
            await _run(_db(), attachments=[attachment])

        prompt = prepared.built.agent.iter.call_args.args[0]
        assert "month,total" in prompt

    async def test_the_workspace_the_run_opened_is_the_one_the_file_lands_in(self):
        """Not a fresh one, and not none - the file has to be where the agent
        will look for it."""
        from pydantic_ai_backends import StateBackend

        attachment = SimpleNamespace(
            id=uuid.uuid4(),
            filename="raport.csv",
            mime_type="text/csv",
            size=512,
            storage_path="u/1/raport.csv",
            file_type="text",
            parsed_content="month,total",
        )
        backend = StateBackend()
        prepared = _prepared()
        prepared.workspace = SimpleNamespace(backend=backend)

        with (
            _runner(prepared),
            patch(
                "app.services.attachments.get_file_storage",
                lambda: SimpleNamespace(load=AsyncMock(return_value=b"month,total")),
            ),
        ):
            await _run(_db(), attachments=[attachment])

        assert any(path.startswith("/uploads/") for path in backend.files)

    async def test_a_prompt_already_assembled_as_parts_keeps_its_text(self):
        """A caller passing the richer shape would otherwise have its
        attachments appended to a `repr`."""
        attachment = SimpleNamespace(
            id=uuid.uuid4(),
            filename="notes.txt",
            mime_type="text/plain",
            size=10,
            storage_path="u/1/notes.txt",
            file_type="text",
            parsed_content="hello",
        )
        prepared = _prepared()
        prepared.workspace = None

        with _runner(prepared):
            await _run(_db(), user_input=["what is this", "and this"], attachments=[attachment])

        prompt = prepared.built.agent.iter.call_args.args[0]
        assert prompt.startswith("what is thisand this")
