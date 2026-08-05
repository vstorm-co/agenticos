"""A specialist a model invents at run time, and what has to be true of one.

One property is the reason this exists, and it is worth stating before anything
else: **a dynamic specialist's model request is metered.** The delegation library
will happily build one itself, from `SubAgentCapability.default_model` - an agent
on a provider the organization may hold no key for, priced by nothing and checked
against no budget. That is an unmetered model request, which is the thing this
platform exists to refuse, and it is why `create_agent` and `delegate` sat
declared and not offered until now.

Everything else follows from routing the build through
`app.agents.factory.build_agent` with the run's `shared_budget`, and from the
model choosing its specialist's model out of the organization's own profiles
rather than naming one in free text:

* the spend lands on the run's shared ledger, and the parent's cap sees it before
  the parent's own next request;
* a model this organization does not hold is refused, by name, before anything is
  built, and so is naming no model at all;
* a specialist is instructions and a model and nothing else - no capabilities, no
  knowledge, and so no delegating further;
* more than `MAX_DYNAMIC_SPECIALISTS` *kept* is refused, and so is one that would
  answer to a published delegate's handle.

Every model is a `FunctionModel`. Both of them report their *usage* rather than
letting the library estimate it, because what is under test is a real
`BudgetGuard` pricing real requests through `genai-prices` - and the two token
counts are two orders of magnitude apart on purpose, so a ledger entry says which
agent spent it and a moved price snapshot cannot flip an assertion.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import anyio
import pytest
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai._run_context import RunContext
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RequestUsage, RunUsage

from app.agents.capabilities import CapabilityBinding, build, get
from app.agents.capabilities.approval import approval_required_tools
from app.agents.capabilities.budget import (
    BudgetExceeded,
    BudgetGuard,
    BudgetScope,
    SpendLedger,
    SpendLimit,
)
from app.agents.capabilities.subagents import Delegation
from app.agents.capabilities.subagents._capability import MAX_DYNAMIC_SPECIALISTS
from app.agents.deps import AgentDeps
from app.agents.factory import build_agent
from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.agents.spec import AgentSpec
from app.agents.subagent_events import SubagentEvent
from app.agents.subagent_runtime import (
    SUBAGENT_RUNTIME_RESOURCE,
    DelegationOutcome,
    DynamicSpecialistBuilder,
    DynamicSpecialists,
    ResolvedSubagent,
    SubagentRuntime,
)
from app.core.secret_kinds import ApiKeySecret
from app.services.agent_runner import _RunBudget

pytestmark = pytest.mark.anyio

PROFILE = "GPT-4.1 (prod)"
"""The one model profile this organization holds, under the label an author sees."""

SPECIALIST_TOKENS = 1_000_000
"""What one request of a dynamic specialist consumes here.

Two orders of magnitude above the parent's, so `SpendLedger.entries` says which
agent spent which entry without the two models needing different names, and so
the cap below binds on a specialist's request and could not bind on the parent's
however the bundled price snapshot moves.
"""

PARENT_TOKENS = 10_000

CAP_USD = Decimal("1.00")
"""A ceiling well above the parent's own spend and well below the specialist's."""


def _usage(input_tokens: int) -> RequestUsage:
    return RequestUsage(input_tokens=input_tokens, output_tokens=0)


def delegating_model(tool: str, args: dict[str, Any]) -> FunctionModel:
    """A parent that makes one tool call, then answers with what came back.

    Two requests, and the second is the whole assertion in the metering test: it
    is the request the guard checks *after* a specialist has spent, so a
    delegation whose spend the guard never saw is a run that finishes normally.
    """

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        returned = [
            str(part.content)
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        parts = [TextPart(" ".join(returned))] if returned else [ToolCallPart(tool, args)]
        return ModelResponse(parts=parts, usage=_usage(PARENT_TOKENS))

    return FunctionModel(respond, model_name="gpt-4.1")


def specialist_model(
    answer: str = "the specialist answered",
    *,
    tools_seen: list[list[str]] | None = None,
    pause: float = 0,
) -> FunctionModel:
    """The model a dynamic specialist runs on, reporting a large request.

    `tools_seen` records what the specialist was actually handed, which is the
    only place that is observable: a capability contributes its toolset to the
    agent, and what reaches the model is what the run resolved from all of them.
    """

    async def respond(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if tools_seen is not None:
            tools_seen.append(sorted(tool.name for tool in info.function_tools))
        if pause:
            await anyio.sleep(pause)
        return ModelResponse(parts=[TextPart(answer)], usage=_usage(SPECIALIST_TOKENS))

    async def stream(_messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[str]:
        if pause:
            await anyio.sleep(pause)
        yield answer

    return FunctionModel(respond, stream_function=stream, model_name="gpt-4.1")


@dataclass(frozen=True)
class _Resolved(ModelRequestSpec):
    """A resolved model profile whose provider client is a `FunctionModel`.

    Subclassed rather than patched, because `build` is exactly the seam between a
    stored profile and a provider client, and a real one would construct an OpenAI
    client. Carrying the stand-in as a field is what lets the parent and its
    specialist run on two different ones through the one code path.
    """

    model_under_test: Model = field(default_factory=TestModel)

    def build(self) -> Model:
        return self.model_under_test


def _resolved(model: Model, *, label: str = PROFILE) -> _Resolved:
    return _Resolved(
        profile_id=uuid4(),
        label=label,
        provider="openai",
        model="gpt-4.1",
        params={},
        credential=ResolvedCredential(provider="openai", secret=ApiKeySecret(api_key="sk-test")),
        fallbacks=[],
        model_under_test=model,
    )


class Recorder:
    """Stands in for the runner, which writes a child run row for a delegation."""

    def __init__(self) -> None:
        self.outcomes: list[DelegationOutcome] = []

    async def __call__(self, outcome: DelegationOutcome) -> UUID | None:
        self.outcomes.append(outcome)
        return None


class Sink:
    """Stands in for a surface narrating a delegation as it happens."""

    def __init__(self) -> None:
        self.frames: list[SubagentEvent] = []

    async def __call__(self, frame: SubagentEvent) -> None:
        self.frames.append(frame)


def specialist_builder(
    budget: _RunBudget | None = None,
    *,
    runs_on: Model | None = None,
) -> DynamicSpecialistBuilder:
    """The build closure the runner assembles, with nothing left to look up.

    This is the whole of the phase in one function: a specialist a model invented
    is an `AgentSpec` like any other, built by the factory every agent here goes
    through, on a `ModelRequestSpec` resolved from one of the organization's own
    profiles - and handed the run's guard as `shared_budget`, which is what puts
    its requests under the parent's caps and into the parent's ledger.

    `budget` is the runner's own late-bound holder rather than a guard, because
    the guard is a product of `build_agent` while the runtime carrying this
    closure had to be inside the `resources` that same call read. `None` is a
    preview, where nothing is metering.
    """

    def build(*, name: str, instructions: str, model: str) -> PydanticAgent[Any, Any]:
        return build_agent(
            AgentSpec(name=name, instructions=instructions),
            _resolved(specialist_model() if runs_on is None else runs_on, label=model),
            organization_id=uuid4(),
            shared_budget=None if budget is None else budget.guard,
        ).agent

    return build


def a_runtime(
    *delegates: ResolvedSubagent,
    dynamic: DynamicSpecialists | None = None,
    ledger: SpendLedger | None = None,
    record: Recorder | None = None,
) -> SubagentRuntime:
    return SubagentRuntime(subagents=delegates, record=record, dynamic=dynamic, ledger=ledger)


def dynamic(
    build: DynamicSpecialistBuilder | None = None, *, allowed: tuple[str, ...] = (PROFILE,)
) -> DynamicSpecialists:
    """An agent whose author switched `allow_dynamic` on, as the runner resolves it."""
    return DynamicSpecialists(
        build=_never_built if build is None else build, allowed_models=allowed
    )


def a_capability(runtime: SubagentRuntime, config: dict[str, Any] | None = None) -> Delegation:
    """The capability as the factory builds it, through the registry."""
    built = build(
        [CapabilityBinding(capability_id="subagents", config=config or {})],
        resources={SUBAGENT_RUNTIME_RESOURCE: runtime},
    )
    capability = built[0]
    assert isinstance(capability, Delegation)
    return capability


def a_context(sink: Sink | None = None) -> RunContext[AgentDeps]:
    return RunContext(
        deps=AgentDeps(
            organization_id=uuid4(),
            run_id=uuid4(),
            kb_collection_names=["kb_only_the_parent_may_read"],
            subagent_events=sink,
        ),
        model=TestModel(),
        usage=RunUsage(),
        run_id="run-1",
        tool_call_id="the-parents-delegate-call",
    )


async def call_tool(
    capability: Delegation, ctx: RunContext[AgentDeps], tool: str, args: dict[str, Any]
) -> Any:
    """Call one of the capability's tools the way the model does."""
    toolset = capability.get_toolset()
    assert toolset is not None
    tools = await toolset.get_tools(ctx)
    return await toolset.call_tool(tool, args, ctx, tools[tool])


async def offered(capability: Delegation) -> set[str]:
    toolset = capability.get_toolset()
    assert toolset is not None
    return set(await toolset.get_tools(a_context()))


def delegate_args(**overrides: Any) -> dict[str, Any]:
    """What a model says when it invents a specialist and hands it work at once."""
    return {
        "description": "summarise the attached policy in three bullets",
        "instructions": "You summarise. Three bullets, no preamble.",
        "name": "summariser",
        "model": PROFILE,
        **overrides,
    }


def create_args(**overrides: Any) -> dict[str, Any]:
    """The same, for a specialist the model means to address again."""
    return {
        "name": "summariser",
        "description": "Summarises a document in three bullets",
        "instructions": "You summarise.",
        "model": PROFILE,
        **overrides,
    }


def a_delegate(name: str = "researcher") -> ResolvedSubagent:
    return ResolvedSubagent(
        name=name,
        description="Researches a topic and cites its sources.",
        build=lambda: PydanticAgent(TestModel()),
    )


def _never_built(*, name: str, instructions: str, model: str) -> PydanticAgent[Any, Any]:
    """A builder for the tests whose whole point is that nothing is built."""
    raise AssertionError(f"a specialist was built: {name} on {model} ({instructions})")


class TestADynamicSpecialistIsMetered:
    """The property this phase exists to preserve.

    Not "the factory was called" - that would pass over a factory building an
    agent with no guard at all, which is precisely the failure. What is asserted
    is the consequence: the money is on the run's ledger, and the cap somebody set
    on the run they started is what stops the next request.
    """

    async def test_a_dynamic_specialists_spend_lands_on_the_runs_shared_ledger(self):
        """One ledger for the whole run, delegates and invented specialists alike.

        A specialist metering into a ledger of its own reports a run that cost the
        parent's requests only - and the organization is then billed for the rest
        by its provider and by nothing here.
        """
        ledger = SpendLedger(run_id=uuid4())
        budget = _RunBudget(guard=BudgetGuard(ledger=ledger, provider="openai"))
        runtime = a_runtime(dynamic=dynamic(specialist_builder(budget)), ledger=ledger)

        await call_tool(a_capability(runtime), a_context(), "delegate", delegate_args())

        assert [entry.input_tokens for entry in ledger.entries] == [SPECIALIST_TOKENS]
        assert ledger.total_usd > 0

    async def test_the_runs_cap_sees_that_spend_before_the_parents_next_request(self):
        """Metered *and* enforced, which are two things and only one is a number.

        Driven through the parent's own agent rather than through the toolset,
        because the assertion is about the request *after* the delegation: the
        guard checks before each one, so a specialist whose spend never reached
        the ledger leaves the parent's second request affordable and the run
        answers normally. That is the shape of the failure, and it is silent.
        """
        budget = _RunBudget()
        runtime = a_runtime(dynamic=dynamic(specialist_builder(budget)))
        parent = build_agent(
            AgentSpec(
                name="Orchestrator",
                instructions="You delegate.",
                capabilities=[
                    {
                        "id": "subagents",
                        "config": {"allow_dynamic": True},
                        # Cleared explicitly, because the default is the opposite
                        # and that default is the subject of its own test below: a
                        # specialist a model invented needs approving, so an agent
                        # meant to run unattended has to say so. Without this the
                        # gate refuses the call - there is no channel here - and
                        # nothing spends.
                        "tool_approval": {"delegate": "never"},
                    }
                ],
                budget={"monthly_usd": float(CAP_USD)},
            ),
            _resolved(delegating_model("delegate", delegate_args())),
            organization_id=uuid4(),
            resources={SUBAGENT_RUNTIME_RESOURCE: runtime},
        )
        # The two assignments the runner makes after the build, for the reason it
        # makes them there: both are products of the build, and the runtime had to
        # be inside the resources the build read.
        budget.guard = parent.budget
        runtime.ledger = parent.ledger

        with pytest.raises(BudgetExceeded) as refused:
            await parent.agent.run("summarise the policy", deps=parent.deps)

        assert refused.value.scope is BudgetScope.AGENT
        assert refused.value.limit_usd == CAP_USD
        # In order: the parent's first request, then the specialist's - which is
        # what the parent's second request was refused over.
        assert [entry.input_tokens for entry in parent.ledger.entries] == [
            PARENT_TOKENS,
            SPECIALIST_TOKENS,
        ]

    async def test_a_specialist_prices_its_own_provider_against_the_shared_ledger(self):
        """`for_delegate` is what `build_agent` does with `shared_budget`, and the
        provider is the one thing it does not share: a specialist on Anthropic
        metered through a guard built for OpenAI is priced against the wrong
        catalog, silently and usually as unpriced."""
        ledger = SpendLedger()
        parent = BudgetGuard(
            ledger=ledger,
            provider="anthropic",
            limits=[SpendLimit(scope=BudgetScope.AGENT, limit_usd=CAP_USD)],
        )
        built = build_agent(
            AgentSpec(name="summariser"),
            _resolved(specialist_model()),
            organization_id=uuid4(),
            shared_budget=parent,
        )

        assert built.budget.ledger is ledger
        assert built.budget.limits is parent.limits
        assert built.budget.provider == "openai"


class TestInventingOneIsSomethingAPersonSeesFirst:
    async def test_both_entry_points_need_approval_by_default(self):
        """The one place delegation and *dynamic* delegation part company.

        `task` needs no approval, because what a delegate does is gated by the
        delegate's own reviewed spec - and asking a person to approve the
        delegation would ask them before the work that might need approving has
        been proposed. There is no reviewed spec here: the instructions were
        written by a model a moment ago, so the specialist itself is the thing
        worth seeing. An author who wants it unattended clears it per tool.
        """
        gated = approval_required_tools(
            AgentSpec(name="Orchestrator", capabilities=[{"id": "subagents", "config": {}}])
        )

        assert {"create_agent", "delegate"} <= gated
        assert "task" not in gated


class TestTheModelIsChosenFromTheOrganizationsOwnProfiles:
    async def test_a_model_the_organization_does_not_hold_is_refused_by_name(self):
        """A run that would die at its first request with a provider error.

        The model naming `openai:gpt-4.1` cannot know whether this organization
        holds an OpenAI key, so the refusal names what it may use instead - and it
        arrives before anything is built, because a specialist that exists and
        cannot run is worse than one that was never created.
        """
        ledger = SpendLedger()
        runtime = a_runtime(dynamic=dynamic(), ledger=ledger)

        answer = await call_tool(
            a_capability(runtime), a_context(), "delegate", delegate_args(model="openai:gpt-4.1")
        )

        assert "openai:gpt-4.1" in answer
        assert PROFILE in answer
        assert ledger.entries == []

    async def test_naming_no_model_at_all_is_refused_rather_than_defaulted(self):
        """There is no default model here, and that is the platform's own rule.

        `SubAgentCapability.default_model` is what the library falls back on, and
        it is a model string of the library's choosing. The rule publish validation
        already applies to every agent - a model an agent did not choose is one
        somebody else's change can swap underneath it - applies to a specialist a
        model invented too.

        Refused here rather than by handing the library an unusable `default_model`,
        because a tool result naming the models this organization holds is something
        the model can act on, and an exception raised from inside the library is not.
        """
        answer = await call_tool(
            a_capability(a_runtime(dynamic=dynamic())),
            a_context(),
            "delegate",
            delegate_args(model=None),
        )

        assert "Refused" in answer
        assert "no default model" in answer

    async def test_the_same_refusals_apply_to_a_specialist_kept_for_the_run(self):
        """`create_agent` and `delegate` are two doors onto one decision, and a
        check on one of them is a check with a second door beside it."""
        capability = a_capability(a_runtime(dynamic=dynamic()))
        ctx = a_context()

        unknown = await call_tool(capability, ctx, "create_agent", create_args(model="gpt-5"))
        missing = await call_tool(capability, ctx, "create_agent", create_args(model=None))

        assert PROFILE in unknown
        assert "no default model" in missing


class TestASpecialistCannotWidenWhatItWasGranted:
    async def test_a_capability_the_model_asks_for_is_refused(self):
        """Letting a model grant its own child a capability is the ungranted-scope
        failure wearing a new hat.

        `capabilities_map` is empty and stays empty: if it is ever populated it is
        from the *parent's* own bindings, intersected with an allowlist an author
        chose and publish validation checked. Until that exists, asking is refused
        rather than quietly ignored - a specialist that was going to search a
        knowledge base and cannot has to say so.
        """
        capability = a_capability(a_runtime(dynamic=dynamic()))
        ctx = a_context()

        one_shot = await call_tool(
            capability, ctx, "delegate", delegate_args(capabilities=["knowledge"])
        )
        kept = await call_tool(
            capability, ctx, "create_agent", create_args(capabilities=["knowledge"])
        )

        assert "knowledge" in one_shot
        assert "knowledge" in kept

    async def test_a_specialist_reaches_its_model_with_no_tools_at_all(self):
        """Which is also how it cannot delegate further.

        A dynamic specialist counts as a level of delegation like any other, and
        the level below it is closed structurally rather than by a ceiling a model
        could talk its way past: it is built from a spec that binds no
        capabilities, so there are no delegation tools to reach for, no knowledge
        to search and no workspace to write to.

        Both routes, because the library injects an `ask_parent` toolset into every
        agent it built itself - which both of these are - unless the config says the
        specialist cannot ask. That flag is a *model-supplied* argument defaulting
        to true, so it is forced off on the way through: with no `ask_user`
        configured, the tool would block for the ask timeout and then proceed
        anyway, which is a question with nowhere to arrive.
        """
        seen: list[list[str]] = []
        runtime = a_runtime(
            dynamic=dynamic(specialist_builder(runs_on=specialist_model(tools_seen=seen)))
        )
        capability = a_capability(runtime)
        ctx = a_context()

        await call_tool(capability, ctx, "delegate", delegate_args(name="one-shot"))
        await call_tool(capability, ctx, "create_agent", create_args(name="kept"))
        await call_tool(
            capability, ctx, "task", {"description": "summarise it", "subagent_type": "kept"}
        )

        assert seen == [[], []]

    async def test_a_specialist_cannot_take_a_published_delegates_handle(self):
        """Two delegates answering to one name leave the model no way to say which.

        The library only refuses a name already in its own registry, so a
        specialist called `researcher` beside a pinned delegate of that slug is
        accepted - and then every `task` call reaches the *delegate*, because the
        resolved ones are matched first. The model would be addressing an agent
        somebody else published while believing it wrote the instructions.
        """
        runtime = a_runtime(a_delegate("researcher"), dynamic=dynamic())
        capability = a_capability(runtime)
        ctx = a_context()

        kept = await call_tool(capability, ctx, "create_agent", create_args(name="researcher"))
        one_shot = await call_tool(capability, ctx, "delegate", delegate_args(name="researcher"))

        assert "researcher" in kept
        assert "researcher" in one_shot


class TestHowManyOneRunMayInvent:
    async def test_past_the_ceiling_a_further_kept_specialist_is_refused(self):
        """A model that can create agents can create a great many.

        The ceiling is on *kept* ones, which is the library's registry and nothing
        else. A one-shot `delegate` registers nothing, so what bounds those is
        `max_fanout` on how many run at once (below) and the agent's own `max_steps`
        on how many calls a turn can make at all.
        """
        capability = a_capability(a_runtime(dynamic=dynamic(specialist_builder())))
        ctx = a_context()

        answers = [
            await call_tool(capability, ctx, "create_agent", create_args(name=f"helper-{index}"))
            for index in range(MAX_DYNAMIC_SPECIALISTS + 1)
        ]

        assert all("created successfully" in answer for answer in answers[:-1])
        assert str(MAX_DYNAMIC_SPECIALISTS) in answers[-1]

    async def test_the_fanout_ceiling_covers_a_one_shot_specialist(self):
        """`delegate` starts a delegation without going near `task`, so a ceiling
        applied only to `task` is a ceiling with a second door beside it."""
        capability = a_capability(
            a_runtime(dynamic=dynamic(specialist_builder(runs_on=specialist_model(pause=30)))),
            {"max_fanout": 1, "mode": "async"},
        )
        ctx = a_context()

        await call_tool(capability, ctx, "delegate", delegate_args(name="first"))
        refused = await call_tool(capability, ctx, "delegate", delegate_args(name="second"))

        assert "Refused" in refused
        await _ends_the_run(capability, ctx)


class TestWhenTheEntryPointsAreOfferedAtAll:
    async def test_an_agent_whose_author_said_nothing_is_offered_neither(self):
        """Every tool in a list is context the model pays for on every turn, and a
        tool that can only refuse is the worst of them."""
        assert await offered(a_capability(a_runtime(a_delegate()))) == {
            "task",
            "check_task",
            "wait_tasks",
            "list_active_tasks",
            "send_message_to_subagent",
            "soft_cancel_task",
            "hard_cancel_task",
        }

    async def test_a_resolved_dynamic_runtime_offers_both_entry_points(self):
        capability = a_capability(a_runtime(a_delegate(), dynamic=dynamic()))

        assert {"create_agent", "delegate", "task"} <= await offered(capability)

    async def test_an_agent_with_no_delegates_but_dynamic_still_gets_the_capability(self):
        """`allow_dynamic` on its own is a complete configuration: an orchestrator
        that invents its specialists has nothing to pin, and returning `None` here
        would have made the switch do nothing at all for exactly that author."""
        capability = a_capability(a_runtime(dynamic=dynamic()))

        assert "delegate" in await offered(capability)

    async def test_the_model_reads_exactly_what_the_catalog_declares(self):
        """Both new descriptions, verbatim.

        The library composes its own for these two out of the models and
        capabilities it was configured with, and appends them - so left alone the
        catalog's copy would be a paraphrase of what the model reads, and the
        appended half would repeat a list the instructions already carry. It would
        also be wrong: the library's `delegate` text calls `model` optional,
        `capabilities` attachable and `mode` the model's choice.
        """
        capability = a_capability(a_runtime(a_delegate(), dynamic=dynamic()))
        toolset = capability.get_toolset()
        assert toolset is not None
        declared = {tool.id: tool.description for tool in get("subagents").tools}

        tools = await toolset.get_tools(a_context())

        assert {
            name: tools[name].tool_def.description for name in ("create_agent", "delegate")
        } == {name: declared[name] for name in ("create_agent", "delegate")}

    async def test_the_instructions_name_the_models_a_specialist_may_run_on(self):
        """The list has to reach the model somewhere, and a tool description is
        the wrong place: the catalog declares those, so one that grew a per-run
        list would be a description the Builder cannot show."""
        instructions = a_capability(a_runtime(a_delegate(), dynamic=dynamic())).get_instructions()

        assert PROFILE in instructions
        assert "researcher" in instructions

    async def test_an_agent_without_dynamic_specialists_says_nothing_about_them(self):
        assert PROFILE not in a_capability(a_runtime(a_delegate())).get_instructions()

    async def test_a_kept_specialist_is_told_it_lasts_only_for_this_reply(self):
        """The library's registry belongs to the built agent, not to the run.

        A run parked on an approval is built again when it is continued, so a
        specialist created before the park is unknown after it while the transcript
        still says it was created. The description is what keeps that from being a
        surprise - agenticos#175 is making the tool mean what its name says.
        """
        (create_agent,) = [tool for tool in get("subagents").tools if tool.id == "create_agent"]

        assert "lasts for this reply" in create_agent.description

    async def test_an_agent_with_only_dynamic_specialists_does_not_offer_an_empty_list(self):
        """An empty bulleted list under "delegate to one of these" is an
        instruction that reads as a mistake, and the model is left guessing
        whether it has delegates it cannot see."""
        instructions = a_capability(a_runtime(dynamic=dynamic())).get_instructions()

        assert "- **" not in instructions
        assert PROFILE in instructions


class TestADynamicDelegationIsAccountedForLikeAnyOther:
    async def test_it_is_recorded_with_no_agent_of_its_own(self):
        """An invented specialist has no agent row to attribute a run to, exactly
        as an inline specialist has none: its cost is the parent's, and the tool
        call in the transcript is the record."""
        ledger = SpendLedger()
        recorder = Recorder()
        budget = _RunBudget(guard=BudgetGuard(ledger=ledger, provider="openai"))
        runtime = a_runtime(
            dynamic=dynamic(specialist_builder(budget)), ledger=ledger, record=recorder
        )

        await call_tool(a_capability(runtime), a_context(), "delegate", delegate_args())

        (outcome,) = recorder.outcomes
        assert (outcome.subagent, outcome.status) == ("summariser", "completed")
        assert (outcome.agent_id, outcome.agent_version_id) == (None, None)
        assert outcome.cost_usd > 0

    async def test_the_authors_mode_is_forced_on_it_too(self):
        """`delegate` takes a `mode` argument whose default is `sync`, so the
        model's choice and the model's silence are the same call - and the
        author's setting is the one that was reviewed."""
        capability = a_capability(
            a_runtime(dynamic=dynamic(specialist_builder(runs_on=specialist_model(pause=30)))),
            {"mode": "async"},
        )
        ctx = a_context()

        answer = await call_tool(capability, ctx, "delegate", delegate_args(mode="sync"))

        assert "Task ID" in answer
        await _ends_the_run(capability, ctx)

    async def test_it_is_narrated_under_the_name_the_model_gave_it(self):
        """A surface renders a panel per delegation, and one with no name is a
        panel a reader cannot attach to anything."""
        sink = Sink()
        ledger = SpendLedger()
        budget = _RunBudget(guard=BudgetGuard(ledger=ledger, provider="openai"))
        runtime = a_runtime(dynamic=dynamic(specialist_builder(budget)), ledger=ledger)

        await call_tool(a_capability(runtime), a_context(sink), "delegate", delegate_args())

        assert {frame.subagent for frame in sink.frames} == {"summariser"}
        assert "subagent_start" in [frame.kind for frame in sink.frames]

    async def test_a_specialist_kept_for_the_run_is_addressed_through_task(self):
        """`create_agent` registers it and `task` reaches it,
        which is what puts it back under the mode, the ceiling and the recording
        every other delegation goes through."""
        ledger = SpendLedger()
        recorder = Recorder()
        budget = _RunBudget(guard=BudgetGuard(ledger=ledger, provider="openai"))
        runtime = a_runtime(
            dynamic=dynamic(specialist_builder(budget)), ledger=ledger, record=recorder
        )
        capability = a_capability(runtime)
        ctx = a_context()

        created = await call_tool(capability, ctx, "create_agent", create_args())
        answer = await call_tool(
            capability, ctx, "task", {"description": "summarise it", "subagent_type": "summariser"}
        )

        assert "created successfully" in created
        assert "the specialist answered" in answer
        assert [outcome.subagent for outcome in recorder.outcomes] == ["summariser"]
        assert ledger.entries != []


async def _ends_the_run(capability: Delegation, ctx: RunContext[AgentDeps]) -> None:
    """Finish the run the way Pydantic AI does, cancelling what is still going."""

    async def handler() -> str:
        return "the parent answered"

    await capability.wrap_run(ctx, handler=handler)
