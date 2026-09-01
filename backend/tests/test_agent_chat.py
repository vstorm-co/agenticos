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
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.messages import ModelMessage, ModelRequest, SystemPromptPart
from pydantic_ai.tools import DeferredToolRequests
from pydantic_ai.usage import RequestUsage

from app.agents.capabilities.budget import (
    BudgetExceeded,
    BudgetScope,
    SpendLedger,
    record_ambient_usage,
)
from app.agents.capabilities.compaction import ContextGauge
from app.agents.capabilities.guardrails import GuardrailBlocked
from app.agents.deps import AgentDeps
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import OrgRoleName
from app.db.models.agent_run import RunStatus, RunSurface
from app.services import agent_chat as agent_chat_service
from app.services.agent_chat import (
    ChatAgentRunner,
    display_output,
    requested_agent_id,
    requested_environment_id,
    requested_model_profile_id,
)
from app.services.agent_runner import AgentRunnerService, PreparedRun

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _no_shares(monkeypatch):
    """Every conversation in this module has one reader unless a test says so.

    `ChatAgentRunner` asks the share repository whether anybody else can read the
    conversation before it lets a binding speak as the runner's own account, and
    these tests hand it a `MagicMock` session - so the real call fails inside
    `db.execute`. Staged here rather than per test, and overridden where a test
    is about a shared conversation.
    """
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        agent_chat_service.conversation_share_repo,
        "get_shares_for_conversation",
        AsyncMock(return_value=[]),
    )


class TestWhatTheTurnCost:
    """Reported to the chat, and never at the cost of the answer.

    Built after `finish`, because that is what writes the tokens and the cost to
    the run row - reading it earlier would report every turn as free.
    """

    @pytest.mark.anyio
    async def test_a_failed_accounting_read_does_not_lose_the_answer(self):
        """The output has already been produced and committed. Losing it to a
        failed usage query would be the worst possible trade."""
        from unittest.mock import AsyncMock as _AsyncMock
        from unittest.mock import MagicMock as _MagicMock

        from app.services.agent_chat import ChatAgentRunner

        runner = ChatAgentRunner(_MagicMock())
        runner.usage = _MagicMock(for_run=_AsyncMock(side_effect=RuntimeError("no")))
        runner.runner = _MagicMock(monthly_spend=_AsyncMock(return_value=None))

        assert await runner._usage(_MagicMock(), _MagicMock()) is None

    @pytest.mark.anyio
    async def test_the_organizations_cap_is_what_the_share_is_measured_against(self):
        from decimal import Decimal as _Decimal
        from unittest.mock import AsyncMock as _AsyncMock
        from unittest.mock import MagicMock as _MagicMock

        from app.services.agent_chat import ChatAgentRunner

        organization = _MagicMock(monthly_budget_usd=_Decimal("100"))
        runner = ChatAgentRunner(_MagicMock(get=_AsyncMock(return_value=organization)))

        assert await runner._budget(_MagicMock()) == _Decimal("100")

    @pytest.mark.anyio
    async def test_an_organization_that_vanished_has_no_cap(self):
        from unittest.mock import AsyncMock as _AsyncMock
        from unittest.mock import MagicMock as _MagicMock

        from app.services.agent_chat import ChatAgentRunner

        runner = ChatAgentRunner(_MagicMock(get=_AsyncMock(return_value=None)))

        assert await runner._budget(_MagicMock()) is None

    @pytest.mark.anyio
    async def test_the_agents_own_spend_and_cap_reach_the_report(self):
        """The organization's cap is the one that stops every agent at once; the
        agent's own is the one whoever is looking at this agent can raise. A chat
        that reported only the first tells its reader nothing they can act on."""
        from decimal import Decimal as _Decimal
        from unittest.mock import AsyncMock as _AsyncMock
        from unittest.mock import MagicMock as _MagicMock

        from app.services.agent_chat import ChatAgentRunner

        runner = ChatAgentRunner(_MagicMock(get=_AsyncMock(return_value=None)))
        runner.usage = _MagicMock(for_run=_AsyncMock(return_value="the report"))
        runner.runner = _MagicMock(monthly_spend=_AsyncMock(return_value=_Decimal("6")))
        prepared = _MagicMock()
        prepared.spec.budget.monthly_usd = 20.0

        assert await runner._usage(_MagicMock(), prepared) == "the report"
        called = runner.usage.for_run.await_args.kwargs
        assert called["agent_spend_usd"] == _Decimal("6")
        assert called["agent_budget_usd"] == _Decimal("20.0")

    @pytest.mark.anyio
    async def test_an_agent_with_no_budget_block_reports_no_cap_of_its_own(self):
        from unittest.mock import AsyncMock as _AsyncMock
        from unittest.mock import MagicMock as _MagicMock

        from app.services.agent_chat import ChatAgentRunner

        runner = ChatAgentRunner(_MagicMock(get=_AsyncMock(return_value=None)))
        runner.usage = _MagicMock(for_run=_AsyncMock(return_value="the report"))
        runner.runner = _MagicMock(monthly_spend=_AsyncMock(return_value=None))
        prepared = _MagicMock()
        prepared.spec.budget = None

        await runner._usage(_MagicMock(), prepared)

        assert runner.usage.for_run.await_args.kwargs["agent_budget_usd"] is None

    @pytest.mark.anyio
    async def test_an_agent_whose_budget_block_names_no_amount_has_no_cap(self):
        from unittest.mock import AsyncMock as _AsyncMock
        from unittest.mock import MagicMock as _MagicMock

        from app.services.agent_chat import ChatAgentRunner

        runner = ChatAgentRunner(_MagicMock(get=_AsyncMock(return_value=None)))
        runner.usage = _MagicMock(for_run=_AsyncMock(return_value="the report"))
        runner.runner = _MagicMock(monthly_spend=_AsyncMock(return_value=None))
        prepared = _MagicMock()
        prepared.spec.budget.monthly_usd = None

        await runner._usage(_MagicMock(), prepared)

        assert runner.usage.for_run.await_args.kwargs["agent_budget_usd"] is None


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


def _agent_run(output: object, *, messages: list[ModelMessage] | None = None) -> MagicMock:
    agent_run = MagicMock()
    agent_run.result = MagicMock(output=output, all_messages=MagicMock(return_value=messages or []))
    return agent_run


def _prepared(output: object = "the refund window is 30 days") -> PreparedRun:
    """A run the runner has already opened, with its agent stubbed.

    A real `PreparedRun`, because `iterate` is what opens the spend meter -
    mocking the prepared run would mock that away and leave the accounting
    tests proving only that the chat called something.
    """
    built = MagicMock()
    built.model_label = "gpt-4.1"
    built.ledger = SpendLedger()
    built.context = ContextGauge()
    built.deps = AgentDeps()
    built.agent.iter = MagicMock(return_value=_Iteration(_agent_run(output)))
    return PreparedRun(
        run=MagicMock(id=uuid.uuid4()),
        agent=MagicMock(),
        spec=MagicMock(),
        built=built,
        approvals=MagicMock(parked={"approval-1": "call-1"}, requested=[]),
    )


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
    prompt_message_id: uuid.UUID | None = None,
    on_run_open: Any = None,
    ask_user: Any = None,
    stream: Any = _nothing,
    user_input: Any = "what is the refund window",
    attachments: Any = None,
    subagent_events: Any = None,
):
    return await ChatAgentRunner(db).run(
        user=user or _user(),
        organization_id=organization_id or uuid.uuid4(),
        agent_id=agent_id or uuid.uuid4(),
        user_input=user_input,
        message_history=[],
        conversation_id=conversation_id,
        prompt_message_id=prompt_message_id,
        on_run_open=on_run_open,
        attachments=attachments,
        ask_user=ask_user or AsyncMock(return_value=[]),
        stream=stream,
        subagent_events=subagent_events,
    )


class TestKeepingASummary:
    """A summary is a model request over a history that is by definition long.
    Bought once, it has to leave the run it was bought in, or the next turn buys
    another over a history one turn longer (#49).
    """

    async def test_a_turn_that_summarised_carries_the_history_it_came_to(self):
        prepared = _prepared()
        prepared.built.context.summarized = True
        prepared.built.agent.iter = MagicMock(
            return_value=_Iteration(
                _agent_run(
                    "the refund window is 30 days",
                    messages=[ModelRequest(parts=[SystemPromptPart(content="Summary: …")])],
                )
            )
        )

        with _runner(prepared):
            turn = await _run(_db())

        assert turn.summarized_history is not None
        assert turn.summarized_history[0]["parts"][0]["content"] == "Summary: …"

    async def test_the_overhead_the_turn_measured_leaves_with_it(self):
        """A one-request turn never measures one of its own before it decides, so
        this turn's reading is what the next turn starts from (#49)."""
        prepared = _prepared()
        prepared.built.context.overhead = 3_865

        with _runner(prepared):
            turn = await _run(_db())

        assert turn.overhead_tokens == 3_865

    async def test_a_turn_that_measured_nothing_carries_nothing(self):
        """A run that reached no model. A zero would read as an agent with no
        instructions and no tools, which is a window with room for anything."""
        prepared = _prepared()

        with _runner(prepared):
            turn = await _run(_db())

        assert turn.overhead_tokens is None

    async def test_a_turn_that_did_not_carries_nothing(self):
        """Most turns. Writing one per turn would pin the thread to whatever the
        last request happened to hold."""
        prepared = _prepared()

        with _runner(prepared):
            turn = await _run(_db())

        assert turn.summarized_history is None


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

    def test_a_parked_run_produces_no_text_of_its_own(self):
        """This value is stored as the assistant message's `content`, so a notice
        about the queue put here is stored as the agent's words - and stays there,
        false, once somebody approves and the run goes on (#509). Parked is state:
        the step it stopped on and the approval panel carry it, and stop carrying
        it when the decision is made."""
        assert display_output(DeferredToolRequests()) == ""


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

    async def test_a_conversation_nobody_else_can_read_is_private(self):
        """The condition a personal MCP substitution waits for."""
        with _runner(_prepared()) as runner:
            await _run(_db(), conversation_id=uuid.uuid4())

        assert runner.prepare.call_args.kwargs["private_to_user"] is True

    async def test_a_shared_conversation_is_not_private(self, monkeypatch):
        """A dashboard conversation can be shared with a member or through a
        public link, and both leave a second reader in the room. Marking the
        whole web surface private let a binding query the runner's own
        third-party account and persist the answer where other people read it."""
        monkeypatch.setattr(
            agent_chat_service.conversation_share_repo,
            "get_shares_for_conversation",
            AsyncMock(return_value=[MagicMock()]),
        )

        with _runner(_prepared()) as runner:
            await _run(_db(), conversation_id=uuid.uuid4())

        assert runner.prepare.call_args.kwargs["private_to_user"] is False

    async def test_a_conversation_that_does_not_exist_yet_is_private(self):
        """Nothing has been shared with anybody, so there is nobody else in it."""
        with _runner(_prepared()) as runner:
            await _run(_db(), conversation_id=None)

        assert runner.prepare.call_args.kwargs["private_to_user"] is True


class TestMeteringWhatTheTurnEmbedded:
    """A knowledge search embeds the question, and somebody has to pay for it.

    The embedding service is process-global - it serves every run and every
    ingestion job at once - so it books through a context variable rather than
    an argument, and a surface that opens no meter drops the cost on the floor.
    Silently: no exception, no warning, a run that reports less than it spent
    and an organization's month that never sees it. The chat did exactly that
    for its whole life (agenticos#16), which is why the meter now belongs to the
    prepared run rather than to whoever remembered to open it.
    """

    @staticmethod
    @contextmanager
    def _billed(*prepared: PreparedRun) -> Iterator[AsyncMock]:
        """Run turns against a real `finish`, and hand back the rows it wrote.

        `finish` bills from the ledger, so a test asserting on the ledger would
        be asserting on the object it is trying to prove reaches the row. This
        reads the row.
        """
        with (
            patch("app.services.agent_chat.member_repo") as members,
            patch.object(AgentRunnerService, "prepare", AsyncMock(side_effect=prepared)),
            patch(
                "app.services.agent_runner.agent_run_repo.finish_run", new=AsyncMock()
            ) as finish_run,
        ):
            members.get = AsyncMock(return_value=_membership())
            yield finish_run

    @staticmethod
    def _searches(tokens: int = 1000, provider: str | None = "openai"):
        """A turn whose tool embeds something while the agent is working."""

        async def stream(agent_run: Any) -> None:
            record_ambient_usage(
                "text-embedding-3-small", RequestUsage(input_tokens=tokens), provider
            )

        return stream

    async def test_an_embedding_made_during_the_turn_reaches_the_runs_cost(self):
        with self._billed(_prepared()) as finish_run:
            await _run(_db(), stream=self._searches())

        billed = finish_run.await_args.kwargs
        assert billed["cost_usd"] == Decimal("0.00002")
        assert billed["input_tokens"] == 1000

    async def test_an_unpriced_embedding_makes_the_turns_cost_a_floor(self):
        """`cost_is_partial` is what the chat draws its `+` from. An embedding
        model nobody prices costs something, and reporting the run's total as
        exact would say the opposite of what is known."""
        with self._billed(_prepared()) as finish_run:
            await _run(_db(), stream=self._searches(provider=None))

        billed = finish_run.await_args.kwargs
        assert (billed["cost_usd"], billed["cost_is_partial"]) == (Decimal(0), True)

    async def test_two_chats_in_one_process_do_not_bill_each_other(self):
        """Every socket in a deployment is served by one process, so the meter is
        a context variable rather than a field - and the reason to prove it is
        that the failure would be a person paying for a stranger's search.

        The barrier makes the overlap real: neither turn embeds until both are
        inside their own metered block, and neither leaves until both have.
        """
        first, second = _prepared(), _prepared()
        overlapping = asyncio.Barrier(2)

        def embeds(tokens: int):
            async def stream(agent_run: Any) -> None:
                await overlapping.wait()
                record_ambient_usage(
                    "text-embedding-3-small", RequestUsage(input_tokens=tokens), "openai"
                )
                await overlapping.wait()

            return stream

        with self._billed(first, second):
            await asyncio.gather(
                _run(_db(), stream=embeds(1000)),
                _run(_db(), stream=embeds(2000)),
            )

        ledgers = [first.built.ledger, second.built.ledger]
        assert [len(ledger.entries) for ledger in ledgers] == [1, 1]
        assert sorted(ledger.input_tokens for ledger in ledgers) == [1000, 2000]


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

    async def test_the_run_row_is_committed_before_the_stream_starts(self):
        """The transaction ends before the model is asked anything (#12).

        The row is then visible from another session for the life of the run,
        and the pooled connection is returned instead of being held `idle in
        transaction` for however long somebody watches the answer arrive.
        """
        db = _db()
        order: list[str] = []

        async def note_commit() -> None:
            order.append("commit")

        async def note_stream(_agent_run: MagicMock) -> None:
            order.append("stream")

        db.commit = AsyncMock(side_effect=note_commit)

        with _runner(_prepared()):
            await _run(db, stream=AsyncMock(side_effect=note_stream))

        assert order[:2] == ["commit", "stream"]

    async def test_a_failed_run_still_records_what_it_spent(self):
        """The tokens were spent before it broke; a budget that ignores that is not one."""
        db = _db()

        with _runner(_prepared()) as runner, pytest.raises(RuntimeError, match="went away"):
            await _run(db, stream=AsyncMock(side_effect=RuntimeError("the model went away")))

        finished = runner.finish.call_args.kwargs
        assert finished["status"] is RunStatus.FAILED
        # Two commits: the one that opened the run row to other sessions before
        # the stream started, and the one that lands the terminal write.
        assert db.commit.await_count == 2

    async def test_a_failed_chat_run_records_the_refusal_and_not_the_provider(self, caplog):
        """The same rule the chat frame took in #659, on the row rather than the
        socket: `agent_runs.error` is rendered in run history to every member who
        can read it, and a model client puts the failing request in its message -
        a tenant's own endpoint with the key still in its query string (#676).

        The log keeps the endpoint and status an operator debugs with, and the key
        in the query string is redacted there by the PII filter when it is
        installed (#440, covered in `test_logging`). This asserts the detail that
        is present either way, not the filter's own behaviour."""
        db = _db()
        vendor_text = "401 from https://llm.acme.internal/v1/chat?api_key=sk-live-9f2c"

        with (
            _runner(_prepared()) as runner,
            caplog.at_level(logging.ERROR, logger="app.services.agent_chat"),
            pytest.raises(RuntimeError),
        ):
            await _run(db, stream=AsyncMock(side_effect=RuntimeError(vendor_text)))

        assert runner.finish.call_args.kwargs["error"] == (
            "The run did not finish (RuntimeError) - retry it, and check the agent's "
            "model profile if it keeps failing. The server log has the full error."
        )
        assert "401 from https://llm.acme.internal/v1/chat" in caplog.text

    async def test_a_stopped_turn_is_recorded_as_cancelled_and_committed(self):
        """Cancellation never reaches the session's rollback-on-error, so the row
        would vanish with the turn unless this path commits it itself."""
        db = _db()

        with _runner(_prepared()) as runner, pytest.raises(asyncio.CancelledError):
            await _run(db, stream=AsyncMock(side_effect=asyncio.CancelledError))

        finished = runner.finish.call_args.kwargs
        assert finished["status"] is RunStatus.CANCELLED
        assert finished["error"] is None
        assert db.commit.await_count == 2

    async def test_a_budget_stop_is_recorded_as_a_budget_stop_not_a_failure(self):
        """An operator filtering run history for problems should not wade through it."""
        stopped = BudgetExceeded(limit_usd=1, spent_usd=2, scope=BudgetScope.AGENT)

        with _runner(_prepared()) as runner, pytest.raises(BudgetExceeded):
            await _run(_db(), stream=AsyncMock(side_effect=stopped))

        finished = runner.finish.call_args.kwargs
        assert finished["status"] is RunStatus.BUDGET_EXCEEDED
        assert "budget exhausted" in finished["error"]

    async def test_a_guardrail_block_is_recorded_as_blocked_not_a_failure(self):
        """The streaming surface does not go through the runner's `_run`, so a
        block here would have been logged like a crash and recorded as FAILED
        without its own clause - the visitor owed the guard's safe refusal."""
        blocked = GuardrailBlocked(edge="input", message="This request was blocked.")

        with _runner(_prepared()) as runner, pytest.raises(GuardrailBlocked):
            await _run(_db(), stream=AsyncMock(side_effect=blocked))

        finished = runner.finish.call_args.kwargs
        assert finished["status"] is RunStatus.GUARDRAIL_BLOCKED
        assert finished["error"] == "This request was blocked."

    async def test_a_run_that_ends_with_nothing_at_all_fails_loudly(self):
        """An empty answer persisted as the agent's reply would be a lie about it."""
        prepared = _prepared()
        prepared.built.agent.iter = MagicMock(return_value=_Iteration(MagicMock(result=None)))

        with _runner(prepared) as runner, pytest.raises(RuntimeError, match="without a result"):
            await _run(_db())

        assert runner.finish.call_args.kwargs["status"] is RunStatus.FAILED


class TestLinkingThePromptToTheRun:
    """`messages.run_id` on the question, not only on the answer.

    The surface writes the prompt before this method is called, because a build
    that refuses - a deleted secret, a model profile removed in a deploy - must
    not lose what somebody typed. There is no run row to name at that moment, so
    the link is made here, as soon as `prepare` has opened one.
    """

    async def test_the_prompt_is_stamped_with_the_run_that_answers_it(self):
        prepared = _prepared()
        conversation_id = uuid.uuid4()
        message_id = uuid.uuid4()

        with (
            _runner(prepared),
            patch("app.services.agent_chat.conversation_repo") as conversations,
        ):
            conversations.link_message_to_run = AsyncMock()
            await _run(_db(), conversation_id=conversation_id, prompt_message_id=message_id)

        assert conversations.link_message_to_run.await_args.kwargs == {
            "message_id": message_id,
            "run_id": prepared.run.id,
            # Off the run rather than taken on trust, so a message id from
            # another thread cannot be pulled into this run's transcript.
            "conversation_id": conversation_id,
        }

    async def test_a_run_that_failed_still_has_the_question_that_started_it(self):
        """Linked before the run rather than after it. A transcript holding the
        answer but not the question can still be read; one holding neither cannot,
        and a failed run is exactly the one somebody opens."""
        prepared = _prepared()
        message_id = uuid.uuid4()

        with (
            _runner(prepared),
            patch("app.services.agent_chat.conversation_repo") as conversations,
            pytest.raises(RuntimeError, match="went away"),
        ):
            conversations.link_message_to_run = AsyncMock()
            await _run(
                _db(),
                conversation_id=uuid.uuid4(),
                prompt_message_id=message_id,
                stream=AsyncMock(side_effect=RuntimeError("the model went away")),
            )

        assert conversations.link_message_to_run.await_args.kwargs["message_id"] == message_id

    @pytest.mark.parametrize(
        ("conversation_id", "message_id"),
        [
            (None, uuid.uuid4()),
            (uuid.uuid4(), None),
            (None, None),
        ],
        ids=["no conversation", "prompt not persisted", "neither"],
    )
    async def test_nothing_is_linked_when_there_is_no_row_to_link(
        self, conversation_id, message_id
    ):
        """`persist_user_turn` logs and swallows a write failure, so a turn can
        reach here with no prompt row at all. Writing `run_id` against `None`
        would raise inside a run that is otherwise fine."""
        with (
            _runner(_prepared()),
            patch("app.services.agent_chat.conversation_repo") as conversations,
        ):
            conversations.link_message_to_run = AsyncMock()
            await _run(_db(), conversation_id=conversation_id, prompt_message_id=message_id)

        conversations.link_message_to_run.assert_not_awaited()


class TestTellingTheSurfaceItsRunIsOpen:
    """`on_run_open`, for the surface that has to persist what it streamed.

    Everything a streaming surface needs to attribute an answer arrives on
    `ChatTurn` - and a run that failed, hit its budget or was cancelled returns
    none, because this method raises instead. So the row is handed over the
    moment `prepare` opens it, before anything can go wrong.
    """

    async def test_the_row_is_handed_over_before_the_run_executes(self):
        prepared = _prepared()
        prepared.run.agent_version_id = uuid.uuid4()
        seen: list[Any] = []

        with _runner(prepared):
            await _run(
                _db(),
                on_run_open=seen.append,
                stream=AsyncMock(side_effect=lambda _run: seen.append("streamed")),
            )

        # Order is the point: handed over first, so a failure in the stream still
        # leaves the surface able to file what it had.
        assert [type(item).__name__ for item in seen] == ["OpenedRun", "str"]
        assert seen[0].run_id == prepared.run.id
        assert seen[0].model_label == "gpt-4.1"
        assert seen[0].agent_version_id == prepared.run.agent_version_id

    async def test_a_surface_that_does_not_persist_is_told_nothing(self):
        """The Playground and the API do not write transcripts of their own."""
        with _runner(_prepared()):
            turn = await _run(_db())

        assert turn.output == "the refund window is 30 days"


class TestMeteringWhatTheRequestWrapperCannotSee:
    """A knowledge search's embedding cost, on the product's primary surface.

    `record_ambient_usage` books onto whichever ledger is active, and having none
    is deliberately a no-op - an embedding provider should not refuse to embed
    because nobody is counting. That makes forgetting the meter silent: this path
    had no `metered_by` at all, so every knowledge search in web chat was free.
    The run under-reported its `cost_usd`, `cost_is_partial` stayed unset so
    nothing on screen hinted at it, and the organization's monthly total never saw
    it (#16).
    """

    async def test_an_embedding_during_the_stream_lands_on_the_run(self):
        prepared = _prepared()
        prepared.built.ledger = SpendLedger()

        async def searches(_agent_run: Any) -> None:
            """A tool call that embeds, as a knowledge search does."""
            record_ambient_usage(
                "text-embedding-3-small", RequestUsage(input_tokens=1_000_000), "openai"
            )

        with _runner(prepared) as runner:
            await _run(_db(), stream=searches)

        # Through `finish`, because that is what writes the ledger to the row -
        # asserting on the ledger alone would pass with the meter still missing.
        assert runner.finish.await_args.args[0].built.ledger.total_usd > 0

    async def test_the_meter_is_closed_once_the_turn_is_over(self):
        """A ledger left active would bill the next thing that embeds - an
        ingestion job, a warmup - to a run that has already been paid for."""
        with _runner(_prepared()):
            await _run(_db())

        ledger = SpendLedger()
        record_ambient_usage("text-embedding-3-small", RequestUsage(input_tokens=1000), "openai")

        assert ledger.total_usd == Decimal(0)


class TestPausingMidRun:
    async def test_the_agent_can_put_a_question_to_the_person_who_is_chatting(self):
        """Only a live surface can answer one; without this wiring the tool is dead."""
        prepared = _prepared()
        ask_user = AsyncMock(return_value=[])

        with _runner(prepared):
            await _run(_db(), ask_user=ask_user)

        assert prepared.deps.ask_user is ask_user

    async def test_the_surface_that_can_draw_a_delegation_is_the_one_that_hears_it(self):
        """Wired here rather than by `prepare`, for the same reason `ask_user` is:
        only a live surface has anywhere to put the frames."""
        prepared = _prepared()

        async def sink(event: Any) -> None:
            """Stands in for the WebSocket."""

        with _runner(prepared):
            await _run(_db(), subagent_events=sink)

        assert prepared.deps.subagent_events is sink

    async def test_a_surface_that_cannot_show_a_delegation_is_given_no_sink(self):
        """The default is load-bearing, not convenient. Attaching a handler makes
        the library open a streamed request for every child, so a delegate whose
        provider cannot stream would work from the API and break in chat -
        `tests/test_subagents_library_contract.py` pins that. Leaving the sink
        `None` off-chat is what keeps it contained."""
        prepared = _prepared()

        with _runner(prepared):
            await _run(_db())

        assert prepared.deps.subagent_events is None

    async def test_a_parked_tool_call_leaves_the_run_resumable(self):
        """The decision arrives later, from the queue - possibly tomorrow, in
        another process - so everything needed to continue goes on the row."""
        prepared = _prepared(DeferredToolRequests())

        with _runner(prepared) as runner:
            turn = await _run(_db())

        finished = runner.finish.call_args.kwargs
        assert finished["status"] is RunStatus.AWAITING_APPROVAL
        assert finished["paused_state"].tool_call_ids == {"approval-1": "call-1"}
        # And no answer, because it produced none. What it is waiting on is on the
        # row and in `parked`, not in a sentence stored as the agent's words.
        assert turn.output == ""


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
        # `parses_documents` is what says the runtime can read a PDF itself; a
        # stored workspace cannot, and so keeps the extracted text beside the file.
        prepared.workspace = SimpleNamespace(backend=backend, briefing=None, parses_documents=False)

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


class TestACommitThatCannotLand:
    """The terminal commit must not replace the exception that ended the run (#235)."""

    @pytest.mark.anyio
    async def test_a_failing_commit_does_not_mask_the_cancellation(self):
        """A stop cancels the turn; a commit that then cannot land - a
        serialization failure, a dropped connection - must not turn that into a
        failed turn by replacing the `CancelledError`."""

        async def _cancelled(agent_run: Any) -> None:
            raise asyncio.CancelledError

        db = _db()
        # Two commits reach the session now: the opening one before the model
        # call (#12) and the terminal one. Only the terminal write is under
        # test, so the first is allowed to land.
        db.commit = AsyncMock(side_effect=[None, RuntimeError("could not serialize access")])
        with _runner(_prepared()), pytest.raises(asyncio.CancelledError):
            await _run(db, stream=_cancelled)
        assert db.commit.await_count == 2

    @pytest.mark.anyio
    async def test_a_failing_commit_on_a_clean_run_still_surfaces(self):
        """When nothing else ended the run, a commit that cannot land is the one
        thing wrong and does surface."""
        db = _db()
        # Two commits reach the session now: the opening one before the model
        # call (#12) and the terminal one. Only the terminal write is under
        # test, so the first is allowed to land.
        db.commit = AsyncMock(side_effect=[None, RuntimeError("could not commit")])
        with _runner(_prepared()), pytest.raises(RuntimeError, match="could not commit"):
            await _run(db)

    @pytest.mark.anyio
    async def test_a_failing_finish_does_not_mask_the_cancellation(self):
        """The masking window is the whole terminal write, not only the commit:
        `finish` hits the same connection first and must not replace the
        `CancelledError` either (#235)."""

        async def _cancelled(agent_run: Any) -> None:
            raise asyncio.CancelledError

        db = _db()
        with _runner(_prepared()) as runner:
            runner.finish = AsyncMock(side_effect=RuntimeError("connection dropped"))
            with pytest.raises(asyncio.CancelledError):
                await _run(db, stream=_cancelled)
        # Only the opening commit; the terminal one is never reached.
        db.commit.assert_awaited_once()

    @pytest.mark.anyio
    async def test_a_commit_failure_surfaces_even_inside_a_callers_except(self):
        """#235 review: a caller's handled exception must not make this run's own
        commit failure look like the thing being unwound and get swallowed."""
        db = _db()
        # Two commits reach the session now: the opening one before the model
        # call (#12) and the terminal one. Only the terminal write is under
        # test, so the first is allowed to land.
        db.commit = AsyncMock(side_effect=[None, RuntimeError("could not commit")])
        with _runner(_prepared()):
            try:
                raise ValueError("boom")  # noqa: TRY301 - a caller already mid-except
            except ValueError:
                with pytest.raises(RuntimeError, match="could not commit"):
                    await _run(db)
